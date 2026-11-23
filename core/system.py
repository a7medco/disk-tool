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
                           stdin=subprocess.DEVNULL, creationflags=NOWIN)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return 127, ""


def powershell(script, stream=True):
    """Run a PowerShell script block. stream=True shows output live."""
    if stream:
        return run(PS + [script])
    return capture(PS + [script])


def ps_json(script):
    """Run PowerShell and parse '... | ConvertTo-Json' output into Python objects.

    Always returns a list (PowerShell emits a bare object for a single item).
    """
    code, out = capture(PS + [script + " | ConvertTo-Json -Depth 4 -Compress"])
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
