"""Startup apps: list, disable, enable - the same way Task Manager's Startup tab does.

Task Manager never deletes the Run entry. It writes a flag in
  ...\\CurrentVersion\\Explorer\\StartupApproved\\{Run, Run32, StartupFolder}
  02 00 00 00 00.. = enabled     03 00 00 00 + time = disabled
So everything here is reversible and shows up the same in Task Manager.
"""
import os
import struct
import time

try:
    import winreg
except ImportError:          # lets the file import on non-Windows for testing
    winreg = None

CV = r"Software\Microsoft\Windows\CurrentVersion"
APPROVED = CV + r"\Explorer\StartupApproved"


def _sources():
    if winreg is None:
        return []
    HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
    appdata = os.environ.get("APPDATA", "")
    progdata = os.environ.get("ProgramData", r"C:\ProgramData")
    sm = r"Microsoft\Windows\Start Menu\Programs"
    return [
        # kind, label, run-root, run-path, approved-root, approved-subkey, folder
        ("hkcu", "User", HKCU, CV + r"\Run", HKCU, "Run", None),
        ("hklm", "All users", HKLM, CV + r"\Run", HKLM, "Run", None),
        ("hklm32", "All users 32-bit", HKLM,
         r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", HKLM, "Run32", None),
        ("ufolder", "User folder", None, None, HKCU, "StartupFolder",
         os.path.join(appdata, sm, "Startup")),
        ("cfolder", "All users folder", None, None, HKLM, "StartupFolder",
         os.path.join(progdata, sm, "StartUp")),
    ]


def _open(root, path, write=False):
    access = (winreg.KEY_READ | winreg.KEY_SET_VALUE) if write else winreg.KEY_READ
    access |= winreg.KEY_WOW64_64KEY
    if write:
        return winreg.CreateKeyEx(root, path, 0, access)
    return winreg.OpenKey(root, path, 0, access)


def _values(root, path):
    out = {}
    try:
        with _open(root, path) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = data
                i += 1
    except OSError:
        pass
    return out


def list_items():
    items = []
    for kind, label, rroot, rpath, aroot, asub, folder in _sources():
        flags = _values(aroot, APPROVED + "\\" + asub)
        if folder is None:
            entries = [(n, str(v)) for n, v in _values(rroot, rpath).items() if n]
        else:
            try:
                entries = [(n, os.path.join(folder, n)) for n in os.listdir(folder)
                           if n.lower() != "desktop.ini"]
            except OSError:
                entries = []
        for name, cmd in entries:
            flag = flags.get(name)
            enabled = not (isinstance(flag, (bytes, bytearray)) and len(flag) and flag[0] & 1)
            items.append({"id": kind + "|" + name, "name": name, "cmd": cmd,
                          "where": label, "enabled": enabled})
    return sorted(items, key=lambda x: (not x["enabled"], x["name"].lower()))


def set_enabled(item_id, enable, log):
    kind, _, name = item_id.partition("|")
    src = next((s for s in _sources() if s[0] == kind), None)
    if not src:
        log("[X] Unknown item.")
        return 1
    aroot, asub = src[4], src[5]
    if enable:
        data = bytes([2]) + bytes(11)
    else:
        ft = int((time.time() + 11644473600) * 10**7)          # FILETIME now
        data = bytes([3, 0, 0, 0]) + struct.pack("<Q", ft)
    try:
        with _open(aroot, APPROVED + "\\" + asub, write=True) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)
    except OSError as e:
        log("[X] Could not change '%s': %s" % (name, e))
        return 1
    log("[OK] %s: %s at next sign-in." % (name, "will start" if enable else "won't start"))
    return 0
