"""Where things live - works both as 'python app.py' and as DiskTool.exe (PyInstaller).

RES  = read-only files bundled inside the exe (web\\index.html)
DATA = folder next to the exe (settings.json, bin\\...) - survives updates
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)
_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = getattr(sys, "_MEIPASS", _SRC) if FROZEN else _SRC
DATA = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else _SRC

