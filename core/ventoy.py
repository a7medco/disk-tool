"""Multi-ISO bootable USB using Ventoy (free, GPLv3, ventoy.net).

Ventoy is installed on the USB once; after that you just COPY any number of
ISO/WIM/IMG/VHD files to it and choose one from a boot menu.

Command line (official, ventoy.net "Windows CLI"):
    Ventoy2Disk.exe VTOYCLI /I /PhyDrive:N [/GPT] [/NOSB]     install (erases USB)
    Ventoy2Disk.exe VTOYCLI /U /PhyDrive:N                    update, keeps the files
Exit code 0 = success, 1 = failed; details in cli_log.txt next to the exe.
"""
import glob
import json
import os

from .paths import DATA as HERE
from .system import ps_json
from .winops import run_stream

SETTINGS = os.path.join(HERE, "settings.json")


def _load():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except OSError:
        pass


def find_exe():
    """Saved path, else bin\\ventoy\\...\\Ventoy2Disk.exe inside the app folder."""
    p = _load().get("ventoy_exe", "")
    if p and os.path.isfile(p):
        return p
    hits = glob.glob(os.path.join(HERE, "bin", "ventoy", "**", "Ventoy2Disk.exe"), recursive=True)
    return hits[0] if hits else ""


def set_exe(path):
    if path and os.path.basename(path).lower() == "ventoy2disk.exe" and os.path.isfile(path):
        d = _load()
        d["ventoy_exe"] = path
        _save(d)
        return True
    return False


def _cli_log_tail(exe, log, n=12):
    p = os.path.join(os.path.dirname(exe), "cli_log.txt")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-n:]
        log("  --- Ventoy log (last lines) ---")
        for ln in lines:
            log("  " + ln)
    except OSError:
        pass


def install(disk_number, mode, gpt, secure_boot, log):
    """mode 'I' = fresh install (ERASES the USB), 'U' = update (keeps ISO files)."""
    exe = find_exe()
    if not exe:
        log("[X] Ventoy2Disk.exe not found. Download Ventoy for Windows from ventoy.net,"
            " extract it into the app's bin\\ventoy folder (or click 'Locate').")
        return 1
    from . import guard
    mode = guard.choice(mode, ("I", "U"), "Ventoy mode")
    disk_number = guard.check_disk(disk_number)["Number"]
    args = [exe, "VTOYCLI", "/" + mode, "/PhyDrive:%d" % disk_number]
    if mode == "I":
        if gpt:
            args.append("/GPT")
        if not secure_boot:
            args.append("/NOSB")
    log("Running Ventoy - this takes about a minute, the window may look idle...")
    code = run_stream(args, log, cwd=os.path.dirname(exe))
    _cli_log_tail(exe, log)
    if code == 0:
        log("[OK] Ventoy %s done. Now add ISO files below." % ("install" if mode == "I" else "update"))
    else:
        log("[X] Ventoy failed (code %s) - see the log lines above." % code)
    return code


def data_letter(disk_number):
    """Drive letter of Ventoy's big data partition (partition 1)."""
    r = ps_json("Get-Partition -DiskNumber %s -PartitionNumber 1 -ErrorAction SilentlyContinue"
                " | Select-Object DriveLetter" % int(disk_number))
    if r:
        L = str(r[0].get("DriveLetter") or "").strip()
        if L and L not in ("\x00", "0"):
            return L
    return ""


def add_isos(disk_number, files, log):
    """Copy the chosen images onto the Ventoy USB (robocopy, unbuffered for big files)."""
    L = data_letter(disk_number)
    if not L:
        log("[X] The Ventoy partition has no drive letter. Unplug/replug the USB and retry.")
        return 1
    dst = L + ":\\"
    fails = 0
    for i, f in enumerate(files, 1):
        if not os.path.isfile(f):
            log("[X] Missing: %s" % f)
            fails += 1
            continue
        log("(%d/%d) %s  ->  %s" % (i, len(files), os.path.basename(f), dst))
        c = run_stream(["robocopy", os.path.dirname(f), dst, os.path.basename(f),
                        "/J", "/NP", "/R:1", "/W:1"], log)
        if c >= 8:                       # robocopy: 0-7 = ok, 8+ = failure
            fails += 1
    if fails:
        log("[X] %d file(s) failed." % fails)
        return 1
    log("[OK] All images copied. Boot from the USB and pick one from the Ventoy menu.")
    return 0


def list_isos(disk_number):
    L = data_letter(disk_number)
    if not L:
        return []
    out = []
    for ext in ("iso", "wim", "img", "vhd", "vhdx", "efi"):
        for p in glob.glob(L + ":\\**\\*." + ext, recursive=True):
            try:
                out.append({"name": os.path.relpath(p, L + ":\\"), "size": os.path.getsize(p)})
            except OSError:
                pass
    return sorted(out, key=lambda x: x["name"].lower())
