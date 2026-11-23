"""Capture the running Windows to an image file (.esd) on an external USB drive.

Mode 1 - Backup image (same PC / same hardware)
    wimlib-imagex capture C:\\ <file> --snapshot --solid      (VSS snapshot, no restart)

Mode 2 - Deployment image (for other PCs, boots to OOBE)
    1. build a small WinPE from this PC's own Windows RE (winre.wim) + wimlib + capture script
    2. add a one-time RAM-disk boot entry for it (bcdedit, Microsoft "boot WinPE from a RAM disk")
    3. sysprep /generalize /oobe /quit  (auto-fix: per-user Store apps, stale sysprep state)
    4. restart -> WinPE captures C:\\ to the USB -> PC turns off

wimlib (LGPL) ships in bin\\wimlib, added by the build.
"""
import datetime
import glob
import os
import re
import shutil
import subprocess

from .paths import DATA
from .system import NOWIN, ps_json
from .winops import _ps_lines, run_stream

WIMLIB_DIR = os.path.join(DATA, "bin", "wimlib")
WIMLIB = os.path.join(WIMLIB_DIR, "wimlib-imagex.exe")
SYSDRV = os.environ.get("SystemDrive", "C:")[:2]
PE_DIR = SYSDRV + "\\DiskToolPE"
OS_MARK = "DiskTool_OS.marker"
TGT_MARK = "DiskTool_TARGET.marker"
IMG_DIR = "DiskToolImages"

EXCLUDE = """[ExclusionList]
\\$ntfs.log
\\hiberfil.sys
\\pagefile.sys
\\swapfile.sys
\\System Volume Information
\\RECYCLER
\\$RECYCLE.BIN
\\Windows\\CSC
\\DiskToolPE
\\DiskTool_OS.marker
"""


# ------------------------------------------------------------ helpers ----
def _ps(script):
    return [l for l in _ps_lines(script) if l.strip()]


def targets():
    """Drive letters on external USB disks (the only allowed destinations)."""
    return ps_json(
        "Get-Disk | Where-Object BusType -eq 'USB' | Get-Partition | Where-Object DriveLetter |"
        " ForEach-Object { $v = $_ | Get-Volume; [pscustomobject]@{Letter=[string]$_.DriveLetter;"
        " Label=$v.FileSystemLabel; FS=$v.FileSystem; Size=$v.Size; Free=$v.SizeRemaining;"
        " Disk=$_.DiskNumber} }")


def _check_target(letter, log):
    letter = (letter or "").strip(":\\ ").upper()[:1]
    t = next((x for x in targets() if x.get("Letter", "").upper() == letter), None)
    if not t:
        log("[X] %s: is not on an external USB drive. Only USB drives are allowed." % letter)
        return None
    if str(t.get("FS", "")).upper() not in ("NTFS", "EXFAT"):
        log("[X] %s: is %s - format it NTFS or exFAT first (FAT32 can't hold files over 4 GB)."
            % (letter, t.get("FS")))
        return None
    used = ps_json("Get-Volume -DriveLetter %s | Select-Object Size,SizeRemaining" % SYSDRV[0])
    if used:
        need = (int(used[0]["Size"]) - int(used[0]["SizeRemaining"])) * 0.45   # ESD ~ 40-50 %
        if int(t.get("Free") or 0) < need:
            log("[X] Not enough space on %s: (need about %d GB free)." % (letter, need // 10**9 + 1))
            return None
    return letter


def _image_name():
    r = ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption")
    cap = (r[0].get("Caption") if r else "Windows").replace("Microsoft ", "")
    return cap, datetime.datetime.now().strftime("%Y-%m-%d_%H%M")


def _have_wimlib(log):
    if os.path.isfile(WIMLIB):
        return True
    log("[X] wimlib-imagex.exe is missing from bin\\wimlib (re-download Disk Tool).")
    return False


def _bitlocker_on():
    r = ps_json("Get-BitLockerVolume -MountPoint %s -ErrorAction SilentlyContinue |"
                " Select-Object VolumeStatus" % SYSDRV)
    return bool(r) and str(r[0].get("VolumeStatus")) not in ("FullyDecrypted", "0", "None", "")


def bitlocker_off(log):
    log("Turning BitLocker off on %s - decryption runs in the background and can take a while." % SYSDRV)
    return run_stream(["manage-bde", "-off", SYSDRV], log)


# --------------------------------------------------- mode 1: backup ----
def backup_image(letter, log, stop=None):
    if not _have_wimlib(log):
        return 1
    L = _check_target(letter, log)
    if not L:
        return 1
    name, stamp = _image_name()
    os.makedirs(L + ":\\" + IMG_DIR, exist_ok=True)
    out = "%s:\\%s\\Backup_%s.esd" % (L, IMG_DIR, stamp)
    cfg = os.path.join(os.environ.get("TEMP", SYSDRV + "\\"), "disktool_exclude.ini")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(EXCLUDE)
    log("Capturing %s (live snapshot, no restart) -> %s" % (name, out))
    log("ESD compression is slow - about 20-60 minutes. You can keep using the PC.")
    code = run_stream([WIMLIB, "capture", SYSDRV + "\\", out, name, "Backup " + stamp,
                       "--snapshot", "--solid", "--config=" + cfg], log)
    if code == 0:
        log("[OK] Backup image saved: %s" % out)
        log("Restore it with 'Install to disk' (pick this .esd as the source).")
    else:
        log("[X] Capture failed (code %s)." % code)
    return code


# ------------------------------------------- mode 2: deployment image ----
def _winre_path(log):
    for line in _ps("reagentc /info"):
        m = re.search(r"(\\\\\?\\GLOBALROOT\\device\\[^\s]+)", line, re.I)
        if m:
            p = os.path.join(m.group(1), "Winre.wim")
            if os.path.isfile(p):
                return p
    p = os.path.join(os.environ.get("WINDIR", SYSDRV + "\\Windows"), "System32", "Recovery", "Winre.wim")
    return p if os.path.isfile(p) else ""


def _boot_sdi():
    win = os.environ.get("WINDIR", SYSDRV + "\\Windows")
    for sub in ("EFI", "PCAT"):
        p = os.path.join(win, "Boot", "DVD", sub, "boot.sdi")
        if os.path.isfile(p):
            return p
    return ""


def _is_uefi():
    r = ps_json("Get-ItemProperty HKLM:\\System\\CurrentControlSet\\Control | Select-Object PEFirmwareType")
    return bool(r) and int(r[0].get("PEFirmwareType") or 0) == 2


CAPTURE_CMD = r"""@echo off
title Disk Tool - capturing Windows image
set OS=
set TGT=
for %%d in (C D E F G H I J K L M N O P Q R S T U V W Y Z) do if exist %%d:\{os_mark} set OS=%%d:
for %%d in (C D E F G H I J K L M N O P Q R S T U V W Y Z) do if exist %%d:\{tgt_mark} set TGT=%%d:
if "%OS%"=="" goto fail
if "%TGT%"=="" goto fail
echo Capturing %OS%\ to %TGT%\{img_dir}\{file} ...
del /f /q %OS%\{os_mark} >nul 2>&1
"%SYSTEMDRIVE%\DiskTool\wimlib-imagex.exe" capture %OS%\ "%TGT%\{img_dir}\{file}" "{name}" "Sysprep OOBE {stamp}" --solid --config="%SYSTEMDRIVE%\DiskTool\exclude.ini" > "%TGT%\{img_dir}\capture-log.txt" 2>&1
if errorlevel 1 (echo FAILED >> "%TGT%\{img_dir}\capture-log.txt") else (echo OK >> "%TGT%\{img_dir}\capture-log.txt")
del /f /q %TGT%\{tgt_mark} >nul 2>&1
rd /s /q %OS%\DiskToolPE >nul 2>&1
wpeutil shutdown
exit
:fail
echo Disk Tool: Windows drive or USB target not found. > X:\fail.txt
echo Windows drive or USB target not found - the PC will restart in 60 seconds.
ping -n 60 127.0.0.1 >nul
wpeutil reboot
"""


def _build_pe(name, stamp, file, log):
    winre = _winre_path(log)
    sdi = _boot_sdi()
    if not winre:
        log("[X] This PC has no Windows Recovery image (Winre.wim) - can't make the capture environment.")
        return False
    if not sdi:
        log("[X] boot.sdi not found in Windows\\Boot\\DVD.")
        return False
    mnt = os.path.join(PE_DIR, "mount")
    shutil.rmtree(PE_DIR, ignore_errors=True)
    os.makedirs(mnt, exist_ok=True)
    log("Building the capture environment from this PC's Windows RE...")
    shutil.copyfile(winre, os.path.join(PE_DIR, "boot.wim"))
    shutil.copyfile(sdi, os.path.join(PE_DIR, "boot.sdi"))
    if run_stream(["dism", "/Mount-Image", "/ImageFile:" + os.path.join(PE_DIR, "boot.wim"),
                   "/Index:1", "/MountDir:" + mnt], log) != 0:
        return False
    ok = False
    try:
        dt = os.path.join(mnt, "DiskTool")
        os.makedirs(dt, exist_ok=True)
        for f in glob.glob(os.path.join(WIMLIB_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, dt)
        with open(os.path.join(dt, "exclude.ini"), "w", encoding="utf-8") as f:
            f.write(EXCLUDE)
        with open(os.path.join(dt, "capture.cmd"), "w", encoding="ascii", errors="replace") as f:
            f.write(CAPTURE_CMD.format(os_mark=OS_MARK, tgt_mark=TGT_MARK, img_dir=IMG_DIR,
                                       file=file, name=name.replace('"', ""), stamp=stamp))
        with open(os.path.join(mnt, "Windows", "System32", "winpeshl.ini"), "w", encoding="ascii") as f:
            f.write("[LaunchApps]\r\n%SYSTEMROOT%\\System32\\cmd.exe, /c %SYSTEMDRIVE%\\DiskTool\\capture.cmd\r\n")
        # storage drivers this PC boots with (Intel RST / VMD, RAID, NVMe vendor drivers)
        for inf in _ps("Get-WindowsDriver -Online | Where-Object { $_.ClassName -in 'SCSIAdapter','HDC' }"
                       " | ForEach-Object { $_.OriginalFileName }"):
            if os.path.isfile(inf.strip()):
                run_stream(["dism", "/Image:" + mnt, "/Add-Driver", "/Driver:" + inf.strip()], log)
        ok = True
    finally:
        run_stream(["dism", "/Unmount-Image", "/MountDir:" + mnt, "/Commit" if ok else "/Discard"], log)
    shutil.rmtree(mnt, ignore_errors=True)
    return ok


def _bcd_entry(log):
    """One-time RAM-disk boot entry for the capture WinPE. Returns its GUID."""
    run_stream(["bcdedit", "/create", "{ramdiskoptions}", "/d", "Disk Tool ramdisk"], log)  # may exist
    run_stream(["bcdedit", "/set", "{ramdiskoptions}", "ramdisksdidevice", "partition=" + SYSDRV], log)
    run_stream(["bcdedit", "/set", "{ramdiskoptions}", "ramdisksdipath", "\\DiskToolPE\\boot.sdi"], log)
    out = subprocess.run(["bcdedit", "/create", "/d", "Disk Tool Capture", "/application", "osloader"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=NOWIN).stdout.decode("utf-8", "replace")
    m = re.search(r"\{[0-9a-fA-F-]{36}\}", out)
    if not m:
        log("[X] bcdedit could not create the boot entry: " + out.strip())
        return ""
    g = m.group(0)
    dev = "ramdisk=[%s]\\DiskToolPE\\boot.wim,{ramdiskoptions}" % SYSDRV
    loader = "\\windows\\system32\\winload.efi" if _is_uefi() else "\\windows\\system32\\winload.exe"
    for args in (["device", dev], ["osdevice", dev], ["path", loader], ["systemroot", "\\windows"],
                 ["winpe", "yes"], ["detecthal", "yes"]):
        if run_stream(["bcdedit", "/set", g] + args, log) != 0:
            run_stream(["bcdedit", "/delete", g], log)
            return ""
    return g


def _reset_sysprep_state(log):
    # leftovers of an earlier failed run make Sysprep stop with "fatal error"
    _ps("$k='HKLM:\\SYSTEM\\Setup\\Status\\SysprepStatus';"
        "if(Test-Path $k){Set-ItemProperty $k GeneralizationState 7 -Type DWord;"
        "Set-ItemProperty $k CleanupState 2 -Type DWord}")
    _ps("Get-Process sysprep -ErrorAction SilentlyContinue | Stop-Process -Force")


def _sysprep_dir():
    win = os.environ.get("WINDIR", SYSDRV + "\\Windows")
    for sub in ("Sysnative", "System32"):
        p = os.path.join(win, sub, "Sysprep")
        if os.path.isfile(os.path.join(p, "sysprep.exe")):
            return p
    return ""


def _read_log(path):
    for enc in ("utf-16", "utf-8"):
        try:
            with open(path, encoding=enc, errors="replace") as f:
                return f.read()
        except (OSError, UnicodeError):
            continue
    return ""


def _run_sysprep(log, tries=3):
    d = _sysprep_dir()
    if not d:
        log("[X] sysprep.exe not found.")
        return False
    tag = os.path.join(d, "Sysprep_succeeded.tag")
    for n in range(1, tries + 1):
        _reset_sysprep_state(log)
        try:
            os.remove(tag)
        except OSError:
            pass
        log("Sysprep attempt %d/%d: /generalize /oobe /quit ..." % (n, tries))
        run_stream([os.path.join(d, "sysprep.exe"), "/generalize", "/oobe", "/quit", "/quiet"], log, cwd=d)
        if os.path.isfile(tag):
            log("[OK] Sysprep finished.")
            return True
        text = _read_log(os.path.join(d, "Panther", "setupact.log"))
        pkgs = sorted(set(re.findall(r"Package (\S+) was installed for a user, but not provisioned", text)))
        if pkgs:
            log("Fixing %d Store app(s) installed for one user only:" % len(pkgs))
            for p in pkgs:
                log("  removing " + p)
                _ps("Get-AppxPackage -AllUsers -Name '%s' -ErrorAction SilentlyContinue |"
                    " Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue" % p.split("_")[0])
            continue
        if re.search(r"upgrad", text, re.I) and re.search(r"not supported|will not run", text, re.I):
            log("Sysprep refuses an upgraded Windows - clearing the upgrade flag and retrying.")
            _ps("Remove-ItemProperty -Path HKLM:\\SYSTEM\\Setup -Name Upgrade -ErrorAction SilentlyContinue")
            continue
        break
    err = _read_log(os.path.join(d, "Panther", "setuperr.log"))
    log("[X] Sysprep could not finish. Last errors:")
    for line in [l for l in err.splitlines() if l.strip()][-8:]:
        log("  " + line.strip())
    return False


def deploy_image(letter, log, stop=None):
    if not _have_wimlib(log):
        return 1
    L = _check_target(letter, log)
    if not L:
        return 1
    if _bitlocker_on():
        log("[X] BitLocker / device encryption is on for %s. The capture environment can't read an "
            "encrypted drive. Press 'Turn BitLocker off', wait until it finishes, then run this again." % SYSDRV)
        return 1
    name, stamp = _image_name()
    file = "Deploy_%s.esd" % stamp
    os.makedirs(L + ":\\" + IMG_DIR, exist_ok=True)

    if not _build_pe(name, stamp, file, log):
        shutil.rmtree(PE_DIR, ignore_errors=True)
        return 1
    guid = _bcd_entry(log)
    if not guid:
        shutil.rmtree(PE_DIR, ignore_errors=True)
        return 1

    if not _run_sysprep(log):
        run_stream(["bcdedit", "/delete", guid], log)
        shutil.rmtree(PE_DIR, ignore_errors=True)
        log("Nothing was changed on the boot menu; this Windows still starts normally.")
        return 1

    with open(SYSDRV + "\\" + OS_MARK, "w") as f:
        f.write(stamp)
    with open(L + ":\\" + TGT_MARK, "w") as f:
        f.write(stamp)
    run_stream(["bcdedit", "/bootsequence", guid], log)
    log("[OK] Ready. The PC restarts now, captures Windows to %s:\\%s\\%s and turns OFF by itself."
        % (L, IMG_DIR, file))
    log("Leave the USB plugged in. Next power-on goes to the Windows welcome screen (OOBE).")
    return run_stream(["shutdown", "/r", "/t", "10", "/c", "Disk Tool: capturing the Windows image."], log)
