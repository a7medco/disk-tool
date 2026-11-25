"""Windows PE detection and helpers (no PowerShell / WMI needed).

WinPE has no PowerShell or WMI unless they were added as optional components
(Microsoft: "WinPE: Add packages (Optional Components Reference)"), so on WinPE
the tool reads disks with Windows IOCTLs (core/pe_disks.py) and uses diskpart/dism.

Detection (any one is enough):
  - HKLM\\SYSTEM\\CurrentControlSet\\Control\\MiniNT exists (set by WinPE at boot)
  - SystemDrive is X: and X:\\Windows\\System32\\startnet.cmd exists
Firmware: HKLM\\System\\CurrentControlSet\\Control  PEFirmwareType  0x1 = BIOS, 0x2 = UEFI
(Microsoft: "Boot to UEFI Mode or legacy BIOS mode").

DISKTOOL_FORCE_PE=1 forces WinPE mode (used by the CI tests on normal Windows).
"""
import os
import shutil
import sys

_cache = {}


def _reg_key_exists(path):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except (OSError, ImportError):
        return False


def _reg_value(path, name):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except (OSError, ImportError):
        return None


def forced():
    return os.environ.get("DISKTOOL_FORCE_PE", "") == "1"


def is_pe():
    """True when running inside Windows PE (or forced for tests)."""
    if forced():
        return True
    if sys.platform != "win32":
        return False
    if "pe" not in _cache:
        sysdrv = os.environ.get("SystemDrive", "C:")[:1].upper()
        _cache["pe"] = (_reg_key_exists(r"SYSTEM\CurrentControlSet\Control\MiniNT") or
                        (sysdrv == "X" and os.path.isfile(r"X:\Windows\System32\startnet.cmd")))
    return _cache["pe"]


def firmware():
    """'UEFI' or 'BIOS' (None if unknown). Works on WinPE and on normal Windows."""
    v = _reg_value(r"SYSTEM\CurrentControlSet\Control", "PEFirmwareType")
    if v == 2:
        return "UEFI"
    if v == 1:
        return "BIOS"
    return None


def tool(name):
    """Full path of a command-line tool, or '' when it is not in this Windows/WinPE."""
    return shutil.which(name) or ""


def single_exe():
    """True when this is the one-file build (it unpacks itself into the Temp folder)."""
    from .paths import DATA, FROZEN, RES
    if not FROZEN:
        return False
    return os.path.normcase(os.path.abspath(RES)) != os.path.normcase(os.path.join(DATA, "_internal"))
