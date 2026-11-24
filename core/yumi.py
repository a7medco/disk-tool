"""YUMI exFAT - multiboot USB creator (free, open source, yumiusb.com).

Fully separate from the Ventoy page: we only launch YUMI's own window.
YUMI exFAT is GUI-only (no documented command line), so all steps
(prepare USB, add ISOs, remove ISOs) happen inside YUMI itself.

Official download: https://yumiusb.com/yumi-exfat/
Bundled: bin\\yumi\\YUMI-exFAT-1.0.4.3.exe
SHA-256: c05319c4ff4f33d7284f105ffb8a716957ee277f01df186ed11949a9c30c345b
"""
import glob
import hashlib
import os
import subprocess
import webbrowser

from . import settings
from .paths import DATA

PAGE = "https://yumiusb.com/yumi-exfat/"
KNOWN = {"c05319c4ff4f33d7284f105ffb8a716957ee277f01df186ed11949a9c30c345b": "1.0.4.3"}


def find_exe():
    """Saved path, else bin\\yumi\\YUMI-exFAT*.exe next to the app (newest name wins)."""
    p = settings.get("yumi_exe", "")
    if p and os.path.isfile(p):
        return p
    hits = sorted(glob.glob(os.path.join(DATA, "bin", "yumi", "YUMI-exFAT*.exe")))
    return hits[-1] if hits else ""


def set_exe(path):
    if path and os.path.isfile(path) and os.path.basename(path).lower().startswith("yumi") \
            and path.lower().endswith(".exe"):
        settings.put("yumi_exe", path)
        return True
    return False


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def info():
    exe = find_exe()
    ver, ok = "", False
    if exe:
        try:
            s = _sha256(exe)
            ver, ok = KNOWN.get(s, ""), s in KNOWN
        except OSError:
            pass
    return {"exe": exe, "version": ver, "verified": ok, "page": PAGE}


def launch(log):
    exe = find_exe()
    if not exe:
        log("[X] YUMI exFAT not found. Download it from %s into the app's bin\\yumi folder"
            " (or click 'Locate')." % PAGE)
        return False
    try:
        # DiskTool already runs as admin, so YUMI starts elevated too (no 2nd UAC prompt).
        subprocess.Popen([exe], cwd=os.path.dirname(exe), close_fds=True)
    except OSError as e:
        log("[X] Could not start YUMI: %s" % e)
        return False
    log("[OK] YUMI exFAT opened in its own window: " + exe)
    return True


def open_page():
    webbrowser.open(PAGE)
    return True
