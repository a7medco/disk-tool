"""Windows command helpers: PowerShell, diskpart, admin elevation."""
import ctypes
import json
import subprocess
import sys
import tempfile
import os

NOWIN = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]


def run(cmd):
    """Run a command list, stream output to the terminal. Returns exit code."""
    print("\n> " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
        return 130
    except FileNotFoundError:
        return 127


def capture(cmd):
    """Run a command, return (exit_code, stdout_text)."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, creationflags=NOWIN, timeout=180)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:          # a stuck WMI/storage query must not freeze the app
        return 124, ""


def powershell(script, stream=True):
    """Run a PowerShell script block. stream=True shows output live."""
    if stream:
        return run(PS + [script])
    return capture(PS + [script])


# ---------------------------------------------------------------------------
# One PowerShell kept open for the whole session. Starting powershell.exe costs
# 0.5-2 s on slow PCs; reusing one process makes every page fast.
import base64 as _b64
import queue as _queue
import threading as _threading
import uuid as _uuid


class _PSHost:
    def __init__(self):
        self.lock = _threading.Lock()
        self.proc = None
        self.q = None

    def _start(self):
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NoLogo", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=NOWIN, bufsize=0)
        self.q = _queue.Queue()
        out, q = self.proc.stdout, self.q

        def reader():
            for raw in iter(out.readline, b""):
                q.put(raw.decode("utf-8", errors="replace"))
            q.put(None)
        _threading.Thread(target=reader, daemon=True).start()
        self._send("[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue'")

    def _send(self, line):
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def kill(self):
        try:
            self.proc.kill()
        except Exception:
            pass
        self.proc = None

    def run(self, script, timeout=180):
        """Returns (code, text). code 124 = timeout, 125 = host not available."""
        with self.lock:
            try:
                if self.proc is None or self.proc.poll() is not None:
                    self._start()
                tok = _uuid.uuid4().hex
                b64 = _b64.b64encode(script.encode("utf-8")).decode("ascii")
                self._send(
                    "try { $__o = & ([scriptblock]::Create([Text.Encoding]::UTF8.GetString("
                    "[Convert]::FromBase64String('%s')))) 2>&1 | Out-String -Width 4096; $__c=0 }"
                    " catch { $__o = ($_ | Out-String); $__c=1 };"
                    " [Console]::Out.Write($__o); [Console]::Out.WriteLine('<<%s:' + $__c + '>>');"
                    " [Console]::Out.Flush()" % (b64, tok))
                buf = []
                import time as _t
                end = _t.time() + timeout
                while True:
                    try:
                        line = self.q.get(timeout=max(0.1, end - _t.time()))
                    except _queue.Empty:
                        self.kill()
                        return 124, ""
                    if line is None:
                        self.proc = None
                        return 125, "".join(buf)
                    if ("<<%s:" % tok) in line:
                        code = 1 if line.strip().endswith(":1>>") else 0
                        return code, "".join(buf)
                    buf.append(line)
            except OSError:
                self.kill()
                return 125, ""


_HOST = _PSHost()


def ps_text(script, timeout=180):
    """(code, output) of a PowerShell script, through the shared PowerShell."""
    if sys.platform != "win32":
        return capture(PS + [script])
    code, out = _HOST.run(script, timeout)
    if code == 125:                       # host broke - fall back to a one-off PowerShell
        return capture(PS + [script])
    return code, out


def warm_up():
    """Start the shared PowerShell early (and load the Storage module)."""
    ps_text("$null = Get-Command Get-Disk -ErrorAction SilentlyContinue")


def ps_json(script):
    """Run PowerShell and parse '... | ConvertTo-Json' output into Python objects.

    Always returns a list (PowerShell emits a bare object for a single item).
    """
    code, out = ps_text(script.rstrip() + " | ConvertTo-Json -Depth 5 -Compress")
    out = out.strip()
    if code != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


def diskpart(script_text):
    """Run a diskpart script (one command per line). Returns (code, output)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(script_text)
        path = f.name
    try:
        print("\n> diskpart /s (script):\n" + script_text)
        p = subprocess.run(["diskpart", "/s", path],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = p.stdout.decode("utf-8", errors="replace")
        print(text)
        return p.returncode, text
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin():
    """Re-launch this script elevated (UAC prompt). Returns True if a relaunch started."""
    if is_admin():
        return False
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    params = " ".join('"%s"' % a for a in args)
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return True
    except Exception:
        return False
