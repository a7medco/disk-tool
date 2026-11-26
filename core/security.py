"""Anti-Virus Control: a few safe, reversible helpers for the repair bench.

The app itself already runs elevated (--uac-admin in build.bat), so nothing
here needs its own UAC prompt.

- open_av_settings(): opens Windows Security's own "Virus & threat protection"
  page. The technician flips any switch by hand there - nothing here disables
  protection automatically, and nothing here calls Set-MpPreference, because
  that mirrors a technique malware uses to blind the antivirus and Tamper
  Protection silently no-ops it anyway (Microsoft Learn: Set-MpPreference /
  Tamper Protection; Windows Central: "How to disable real-time protection").
- clear_scan_cache(): empties Defender's own Protection History cache
  (C:\\ProgramData\\Microsoft\\Windows Defender\\Scans\\History\\Service) -
  the documented manual method (Microsoft Learn Q&A; NinjaOne; TheWindowsClub).
  Only deletes inside that one folder.
- open_hosts_file(): opens the hosts file in Notepad for editing.
- open_firewall(): opens Windows Defender Firewall with Advanced Security
  (wf.msc), for the technician to add/inspect inbound & outbound rules.
"""
import os
import subprocess
import sys

from .system import NOWIN

HISTORY_SERVICE = os.path.join(
    os.environ.get("ProgramData", r"C:\ProgramData"),
    "Microsoft", "Windows Defender", "Scans", "History", "Service",
)
HOSTS_FILE = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts",
)


def open_av_settings():
    """Open Windows Security's Virus & threat protection page."""
    if sys.platform != "win32":
        return False
    try:
        os.startfile("windowsdefender://threat")
        return True
    except OSError:
        try:
            subprocess.Popen(["start", "windowsdefender://threat"], shell=True,
                              creationflags=NOWIN)
            return True
        except Exception:
            return False


def clear_scan_cache(log=None):
    """Delete the contents of Defender's Protection History\\Service folder.

    Returns (ok, deleted_count). Safe if the folder is empty, missing, or
    partly locked (in-use files are skipped, not an error).
    """
    def emit(msg):
        if log:
            log(msg)

    if not os.path.isdir(HISTORY_SERVICE):
        emit("[i] Nothing to clear: %s doesn't exist." % HISTORY_SERVICE)
        return True, 0

    deleted = 0
    errors = 0
    for root, dirs, files in os.walk(HISTORY_SERVICE, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            try:
                os.remove(path)
                deleted += 1
            except OSError as e:
                errors += 1
                emit("[!] couldn't delete %s: %s" % (path, e))
        for name in dirs:
            path = os.path.join(root, name)
            try:
                os.rmdir(path)
            except OSError:
                pass  # not empty (a file was in use) - leave it

    emit("[OK] Cleared %d file(s) from Protection History." % deleted)
    if errors:
        emit("[i] %d file(s) still locked (in use) - skipped." % errors)
    return True, deleted


def open_hosts_file():
    """Open the hosts file in Notepad. The app already runs elevated."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.Popen(["notepad.exe", HOSTS_FILE], creationflags=NOWIN)
        return True
    except Exception:
        return False


def open_firewall():
    """Open Windows Defender Firewall with Advanced Security (inbound/outbound rules)."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.Popen(["wf.msc"], shell=True, creationflags=NOWIN)
        return True
    except Exception:
        return False
