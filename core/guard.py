"""Backend safety gate for destructive / sensitive operations.

The UI confirmation (typed disk number, OOBE, CAPTURE...) is only the first step.
Nothing destructive runs unless the BACKEND also agrees:

  1. arm(kind, target, typed)  - called right after the user confirms in the UI.
     Re-reads the disks fresh, checks the typed text, checks the target is allowed,
     and stores ONE short-lived ticket (90 s) with the disk's fingerprint.
  2. take(kind, target)        - called inside the job, just before it runs.
     The ticket must match (same kind + target), not be expired, and the disk must
     still be the SAME physical disk (disk numbers can shift on hot-plug).
     The ticket is used up - every run needs a new confirmation.

Also: whitelists + sanitizing for every value that ends up in diskpart/PowerShell.
"""
import os
import re
import threading
import time

from .paths import DATA

TTL = 90                       # seconds a confirmation stays valid
_lock = threading.Lock()
_ticket = {}

FS_DISK = ("NTFS", "exFAT", "FAT32")
FS_VOL = ("NTFS", "exFAT", "FAT32", "ReFS")
SCHEMES = ("GPT", "MBR")
# action -> word the user must type (None = a yes/no confirm in the UI is enough)
ACTIONS = {"sysprep": "OOBE", "capture_deploy": "CAPTURE", "bitlocker_off": None,
           "password": None, "create_admin": None, "import_drivers": None}


class Blocked(Exception):
    """A destructive request the backend refused. Message is shown in Output."""


# ------------------------------------------------------------ helpers ----
def _sys_letter():
    return (os.environ.get("SystemDrive", "C:")[:1] or "C").upper()


def _app_letter():
    d = os.path.splitdrive(os.path.abspath(DATA))[0]
    return d[:1].upper() if d[1:2] == ":" else ""


def _disks():
    from .winops import list_disks
    return list_disks(0) or []          # always fresh for safety checks


def _letters(d):
    return {str(v.get("Letter") or "").upper() for v in (d.get("Volumes") or []) if v.get("Letter")}


def _fp(d):
    return (d.get("Size"), str(d.get("FriendlyName") or ""), str(d.get("Serial") or ""))


def disk_number(n):
    try:
        n = int(str(n).strip())
    except (TypeError, ValueError):
        raise Blocked("invalid disk number: %r" % (n,))
    if not 0 <= n < 256:
        raise Blocked("invalid disk number: %d" % n)
    return n


def letter(x):
    L = str(x or "").strip().rstrip(":\\").upper()
    if not re.fullmatch(r"[A-Z]", L):
        raise Blocked("invalid drive letter: %r" % (x,))
    return L


def label(x, fs="NTFS"):
    """Volume label safe for diskpart/PowerShell: no quotes/control chars, FS length limit."""
    s = re.sub(r'[\x00-\x1f"\'`$;&|<>^%*?\\/:\[\]=+,]', "", str(x or "")).strip()
    s = s[:11] if fs.upper() == "FAT32" else s[:32]
    return s or "USB"


def choice(x, allowed, what):
    for a in allowed:
        if str(x).lower() == a.lower():
            return a
    raise Blocked("invalid %s: %r" % (what, x))


def existing_file(p, exts=None):
    p = str(p or "")
    if not p or "\n" in p or "\r" in p or not os.path.isfile(p):
        raise Blocked("file not found: %s" % p)
    if exts and not p.lower().endswith(tuple(exts)):
        raise Blocked("wrong file type: %s" % p)
    return p


def find_disk(n, rows=None):
    n = disk_number(n)
    for d in (rows if rows is not None else _disks()):
        if int(d.get("Number", -1)) == n:
            return d
    raise Blocked("Disk %d not found - unplugged? Refresh the list." % n)


def check_disk(n, rows=None):
    """Target disk may be erased? Refuses Windows/boot disk and the disk this app runs from."""
    d = find_disk(n, rows)
    L = _letters(d)
    if d.get("IsSystem") or d.get("IsBoot") or _sys_letter() in L:
        raise Blocked("Disk %s holds Windows (%s:) - never erased." % (d["Number"], _sys_letter()))
    app = _app_letter()
    if app and app in L:
        raise Blocked("Disk %s holds Disk Tool itself (%s:) - run the tool from another drive." % (d["Number"], app))
    return d


def check_volume(x, rows=None):
    L = letter(x)
    if L == _sys_letter():
        raise Blocked("%s: is the Windows drive." % L)
    if L == _app_letter():
        raise Blocked("%s: holds Disk Tool itself." % L)
    for d in (rows if rows is not None else _disks()):
        if L in _letters(d):
            if d.get("IsSystem") or d.get("IsBoot"):
                raise Blocked("%s: is on the Windows/boot disk." % L)
            return L, d
    raise Blocked("%s: not found." % L)


def file_not_on_disk(path, d):
    drv = os.path.splitdrive(os.path.abspath(path))[0][:1].upper()
    if drv and drv in _letters(d):
        raise Blocked("The file is on the disk that would be erased.")


# ------------------------------------------------------------ tickets ----
def arm(kind, target, typed):
    """UI confirmed -> backend re-checks and issues one ticket. Returns {ok, msg}."""
    try:
        typed = str(typed or "").strip()
        if kind == "disk":
            n = disk_number(target)
            if typed != str(n):
                raise Blocked("confirmation text does not match the disk number.")
            d = check_disk(n)
            t = {"kind": kind, "target": n, "fp": _fp(d)}
        elif kind == "volume":
            L, d = check_volume(target)
            if typed.upper().rstrip(":") != L:
                raise Blocked("confirmation text does not match the drive letter.")
            t = {"kind": kind, "target": L, "fp": _fp(d)}
        elif kind == "action":
            if target not in ACTIONS:
                raise Blocked("unknown action: %r" % (target,))
            need = ACTIONS[target]
            if (need and typed.upper() != need) or (not need and typed.upper() != "YES"):
                raise Blocked("confirmation text does not match.")
            t = {"kind": kind, "target": target, "fp": None}
        else:
            raise Blocked("unknown kind: %r" % (kind,))
    except Blocked as e:
        return {"ok": False, "msg": str(e)}
    t["exp"] = time.time() + TTL
    with _lock:
        _ticket.clear()
        _ticket.update(t)
    return {"ok": True, "msg": ""}


def take(kind, target):
    """Inside the job: use up the ticket, re-check the target is the same disk. Raises Blocked."""
    with _lock:
        t = dict(_ticket)
        _ticket.clear()
    if not t:
        raise Blocked("not confirmed - confirm again in the window.")
    if t["exp"] < time.time():
        raise Blocked("confirmation expired (%d s) - confirm again." % TTL)
    if kind == "disk":
        target = disk_number(target)
    elif kind == "volume":
        target = letter(target)
    if t["kind"] != kind or t["target"] != target:
        raise Blocked("confirmation was for a different target.")
    if kind == "disk":
        if _fp(check_disk(target)) != t["fp"]:
            raise Blocked("Disk %d changed since you confirmed (re-plugged?). Refresh and confirm again." % target)
    elif kind == "volume":
        if _fp(check_volume(target)[1]) != t["fp"]:
            raise Blocked("%s: changed since you confirmed. Confirm again." % target)


def disarm():
    with _lock:
        _ticket.clear()
