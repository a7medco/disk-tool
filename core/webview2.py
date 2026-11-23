"""Make sure the Microsoft Edge WebView2 Runtime (needed by the window) is installed.

Detection + silent install as documented by Microsoft ("Distribute your app and
the WebView2 Runtime"): pv value under EdgeUpdate\\Clients\\{F3017226-...};
bootstrapper:  MicrosoftEdgeWebview2Setup.exe /silent /install  (needs internet).
"""
import os
import subprocess

from .paths import RES

GUID = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
KEYS = [("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" + "\\" + GUID),
        ("HKLM", r"SOFTWARE\Microsoft\EdgeUpdate\Clients" + "\\" + GUID),
        ("HKCU", r"Software\Microsoft\EdgeUpdate\Clients" + "\\" + GUID)]
SETUP = os.path.join(RES, "redist", "MicrosoftEdgeWebview2Setup.exe")


def installed():
    import winreg
    roots = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    for root, path in KEYS:
        try:
            with winreg.OpenKey(roots[root], path, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if pv and pv != "0.0.0.0":
                    return True
        except OSError:
            pass
    return False


def _box(text, flags=0x40):
    import ctypes
    return ctypes.windll.user32.MessageBoxW(None, text, "Disk Tool", flags)


def ensure():
    """True when WebView2 is ready (installing it first if needed)."""
    if installed():
        return True
    if not os.path.isfile(SETUP):
        return False
    if _box("Disk Tool needs Microsoft WebView2 (one time).\n\n"
            "It will be installed now - keep the internet on.\nPress OK to continue.",
            0x41) != 1:                                   # OK / Cancel
        return False
    try:
        subprocess.run([SETUP, "/silent", "/install"], timeout=900)
    except (OSError, subprocess.SubprocessError):
        pass
    if installed():
        return True
    _box("WebView2 could not be installed (no internet?).\n"
         "Disk Tool will open in the simple window instead.", 0x30)
    return False
