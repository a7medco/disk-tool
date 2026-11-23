"""Where things live - works both as 'python app.py' and as DiskTool.exe (PyInstaller).

RES  = read-only files bundled inside the exe (web\\index.html)
DATA = folder next to the exe (settings.json, bin\\ventoy) - survives updates
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)
_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = getattr(sys, "_MEIPASS", _SRC) if FROZEN else _SRC
DATA = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else _SRC


def launch_cmd(*args):
    """Command line that starts this tool again (for the right-click menu)."""
    if FROZEN:
        exe = sys.executable
        return exe, '"%s" %s' % (exe, " ".join(args))
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        pw = exe[:-len("python.exe")] + "pythonw.exe"
        exe = pw if os.path.exists(pw) else exe
    return exe, '"%s" "%s" %s' % (exe, os.path.join(_SRC, "app.py"), " ".join(args))
