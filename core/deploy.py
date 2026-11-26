"""Sysprep to OOBE, and Windows To Go (Windows on a USB disk).

Commands follow Microsoft's docs:
  - Sysprep command-line options:  sysprep.exe /generalize /oobe /shutdown
  - Windows To Go / apply images:  dism /Apply-Image ... /ApplyDir:W:\\
                                   dism /Image:W:\\ /Apply-Unattend:W:\\san_policy.xml
                                   bcdboot W:\\Windows /s S: /f ALL
"""
import os
import string
import time

from .system import capture as _run_capture, ps_json
from . import pe
from .paths import DATA
from .winops import _ps_lines, diskpart_stream, run_stream

WIMLIB = os.path.join(DATA, "bin", "wimlib", "wimlib-imagex.exe")


def _remove_letter(letter, log, tries=3):
    """select volume <letter>; remove letter. A hidden partition can briefly
    be held open right after formatting (AV/indexing) - retry a couple of times."""
    script = "select volume %s\nremove letter=%s\nexit\n" % (letter, letter)
    for attempt in range(tries):
        if diskpart_stream(script, log) == 0:
            return 0
        if attempt < tries - 1:
            log("Drive %s: still in use - retrying..." % letter)
            time.sleep(2)
    return 1


# ---------------------------------------------------------------- OOBE ----
def _sysprep_exe():
    win = os.environ.get("WINDIR", r"C:\Windows")
    for sub in ("Sysnative", "System32"):          # Sysnative = 32-bit app on 64-bit Windows
        p = os.path.join(win, sub, "Sysprep", "sysprep.exe")
        if os.path.isfile(p):
            return p
    return ""


def sysprep_oobe(generalize, after, log):
    """after: 'shutdown' or 'reboot'. generalize=True also removes this PC's identity."""
    exe = _sysprep_exe()
    if not exe:
        log("[X] sysprep.exe not found.")
        return 1
    args = [exe, "/oobe", "/" + ("shutdown" if after == "shutdown" else "reboot")]
    if generalize:
        args.insert(1, "/generalize")
    log("Sysprep is running - the PC will %s by itself when it finishes." % after)
    code = run_stream(args, log, cwd=os.path.dirname(exe))
    err = os.path.join(os.path.dirname(exe), "Panther", "setuperr.log")
    try:
        with open(err, encoding="utf-16", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip()]
    except (OSError, UnicodeError):
        try:
            with open(err, encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f if l.strip()]
        except OSError:
            lines = []
    if lines:
        log("[!] Sysprep reported problems (Panther\\setuperr.log, last lines):")
        for l in lines[-10:]:
            log("  " + l)
        log("Common cause: a Store app updated for one user only - remove it, then retry.")
    return code


# --------------------------------------------------------- Windows To Go ----
def _used_letters():
    used = {L for L in string.ascii_uppercase if os.path.exists(L + ":\\")}
    try:                                            # also empty card readers / DVD drives
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        used |= {chr(65 + i) for i in range(26) if mask & (1 << i)}
    except (AttributeError, OSError):
        pass
    return used


def _free_letters(n):
    used = _used_letters()
    if not pe.is_pe():
        used |= {str(r.get("DriveLetter") or "").upper()
                 for r in ps_json("Get-Volume | Select-Object DriveLetter")}
    free = [L for L in "SWTUVRQPONM" if L not in used]
    return free[:n] if len(free) >= n else None


def _image_from_source(src, log):
    """Return (image_path, iso_to_unmount). src can be .iso / .wim / .esd."""
    if src.lower().endswith(".iso") and pe.is_pe():
        log("[X] An ISO can't be opened in WinPE (mounting needs PowerShell). "
            "Open the ISO's sources folder and pick install.wim or install.esd.")
        return "", None
    if src.lower().endswith(".iso"):
        lines = _ps_lines("$r=Mount-DiskImage -ImagePath '%s' -PassThru;"
                          "($r | Get-Volume).DriveLetter" % src.replace("'", "''"))
        L = next((l.strip() for l in lines if l.strip()), "")
        if not L:
            log("[X] Could not mount the ISO.")
            return "", None
        for name in ("install.wim", "install.esd"):
            p = "%s:\\sources\\%s" % (L, name)
            if os.path.exists(p):
                return p, src
        log("[X] No install.wim / install.esd inside this ISO.")
        _ps_lines("Dismount-DiskImage -ImagePath '%s'" % src.replace("'", "''"))
        return "", None
    return src, None


def list_editions(src):
    """Editions inside an ISO / WIM / ESD: [{Index, Name, Size}]."""
    class _L:  # silent logger
        def __call__(self, *_):
            pass
    img, iso = _image_from_source(src, _L())
    if not img:
        return []
    if pe.is_pe():
        return editions_no_ps(img)
    try:
        return ps_json("Get-WindowsImage -ImagePath '%s' | Select-Object "
                       "@{n='Index';e={$_.ImageIndex}},@{n='Name';e={$_.ImageName}},"
                       "@{n='Size';e={$_.ImageSize}}" % img.replace("'", "''"))
    finally:
        if iso:
            _ps_lines("Dismount-DiskImage -ImagePath '%s'" % iso.replace("'", "''"))


SAN_POLICY = """<?xml version='1.0' encoding='utf-8' standalone='yes'?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="offlineServicing">
    <component xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" language="neutral"
      name="Microsoft-Windows-PartitionManager" processorArchitecture="%s"
      publicKeyToken="31bf3856ad364e35" versionScope="nonSxS">
      <SanPolicy>4</SanPolicy>
    </component>
  </settings>
</unattend>
"""


def windows_to_go(src, index, disk_number, log, stop=None):
    """Erase the USB, apply Windows to it and make it bootable on BIOS + UEFI PCs."""
    from . import guard
    _d = guard.check_disk(disk_number)
    guard.file_not_on_disk(src, _d)
    disk_number = _d["Number"]
    letters = _free_letters(2)
    if not letters:
        log("[X] Not enough free drive letters.")
        return 1
    S, W = letters
    log("1/4  Partitioning Disk %s  (System %s:  +  Windows %s:)" % (disk_number, S, W))
    script = ("select disk %s\nclean\nconvert mbr\n"
              "create partition primary size=350\nformat fs=fat32 quick label=System\n"
              "assign letter=%s\nactive\n"
              "create partition primary\nformat fs=ntfs quick label=WindowsToGo\n"
              "assign letter=%s\nexit\n" % (disk_number, S, W))
    if diskpart_stream(script, log) != 0:
        return 1

    img, iso = _image_from_source(src, log)
    if not img:
        return 1
    try:
        log("2/4  Applying Windows (edition %s) - 15 to 60 minutes on a fast USB..." % index)
        if run_stream(["dism", "/Apply-Image", "/ImageFile:" + img,
                       "/Index:%s" % index, "/ApplyDir:%s:\\" % W], log) != 0:
            log("[X] DISM could not apply the image.")
            return 1
    finally:
        if iso:
            _ps_lines("Dismount-DiskImage -ImagePath '%s'" % iso.replace("'", "''"))

    log("3/4  Keeping the host PC's internal disks offline (SAN policy 4)...")
    arch = "arm64" if os.path.isdir(W + ":\\Windows\\SysArm32") else "amd64"
    pol = W + ":\\san_policy.xml"
    try:
        with open(pol, "w", encoding="utf-8") as f:
            f.write(SAN_POLICY % arch)
        run_stream(["dism", "/Image:%s:\\" % W, "/Apply-Unattend:" + pol], log)
    except OSError as e:
        log("[!] SAN policy skipped: %s" % e)

    log("4/4  Writing boot files for BIOS and UEFI...")
    bcd = os.path.join(W + ":\\Windows", "System32", "bcdboot.exe")
    if not os.path.isfile(bcd):
        bcd = "bcdboot"
    if run_stream([bcd, W + ":\\Windows", "/s", S + ":", "/f", "ALL"], log) != 0:
        log("[X] bcdboot failed.")
        return 1
    _remove_letter(S, log)
    log("[OK] Windows To Go is ready. Boot any PC from this USB "
        "(first start takes a few minutes while Windows sets up the hardware).")
    return 0


def parse_image_info(text):
    """'dism /Get-ImageInfo' or 'wimlib-imagex info' text -> [{Index, Name, Size}]."""
    out, cur = [], None
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "index" and v.isdigit():
            cur = {"Index": int(v), "Name": "", "Size": 0}
            out.append(cur)
        elif cur is not None and k == "name" and not cur["Name"]:
            cur["Name"] = v
        elif cur is not None and k in ("size", "total bytes"):
            digits = "".join(c for c in v.split(" bytes")[0] if c.isdigit())
            cur["Size"] = int(digits) if digits else 0
    return out


def editions_no_ps(img):
    """Editions without PowerShell: DISM (English output), else wimlib."""
    if pe.tool("dism"):
        code, out = _run_capture(["dism", "/English", "/Get-ImageInfo", "/ImageFile:" + img])
        rows = parse_image_info(out) if code == 0 else []
        if rows:
            return rows
    if os.path.isfile(WIMLIB):
        code, out = _run_capture([WIMLIB, "info", img])
        if code == 0:
            return parse_image_info(out)
    return []


def apply_image(img, index, target, compact, log):
    """dism /Apply-Image, or wimlib when this WinPE has no DISM. Returns exit code."""
    if pe.tool("dism"):
        args = ["dism", "/Apply-Image", "/ImageFile:" + img, "/Index:%s" % index, "/ApplyDir:%s:\\" % target]
        if compact:
            args.append("/Compact")
        return run_stream(args, log)
    if os.path.isfile(WIMLIB):
        log("[!] DISM is not in this WinPE - applying with wimlib.")
        args = [WIMLIB, "apply", img, str(index), "%s:\\" % target]
        if compact:
            args.append("--compact=xpress4k")
        return run_stream(args, log)
    log("[X] Neither DISM nor bin\\wimlib is available - can't apply the image.")
    return 127


def _clean_gpt(disk_number, log):
    """clean + convert gpt, then delete what diskpart added by itself (newer Windows auto-creates
    an MSR on convert gpt), so the layout below is exactly Microsoft's ESP, MSR, Windows, Recovery."""
    if diskpart_stream("select disk %s\nclean\nconvert gpt\nexit\n" % disk_number, log) != 0:
        return False
    from . import pe_disks
    try:
        parts = next(d for d in pe_disks.list_disks() if d["Number"] == disk_number)["Partitions"]
    except StopIteration:
        parts = 0
    if parts:
        log("Removing %d partition(s) diskpart created by itself..." % parts)
        cmds = "".join("select partition %d\ndelete partition override\n" % k for k in range(parts, 0, -1))
        if diskpart_stream("select disk %s\n%sexit\n" % (disk_number, cmds), log) != 0:
            return False
    return True


# ------------------------------------------- Install Windows to a disk ----
# WinNTSetup-style: prepare an (external) SSD/HDD that will go inside a PC.
# Layouts follow Microsoft's "UEFI/GPT-based hard drive partitions" and
# "BIOS/MBR-based hard drive partitions" docs.
def install_to_disk(src, index, disk_number, scheme, drivers, compact, log, stop=None, recovery=True):
    from . import guard
    _d = guard.check_disk(disk_number)
    guard.file_not_on_disk(src, _d)
    disk_number = _d["Number"]
    scheme = guard.choice(scheme, ("gpt", "mbr"), "partition scheme")
    letters = _free_letters(3)
    if not letters:
        log("[X] Not enough free drive letters.")
        return 1
    S, W, R = letters
    rec_mb = 1024                       # room for future WinRE updates
    if scheme == "mbr":
        fw = "BIOS"
        log("1/6  Partitioning Disk %s - MBR / Legacy BIOS%s" % (disk_number, " + Recovery" if recovery else ""))
        script = ("select disk %s\nclean\nconvert mbr\n"
                  "create partition primary size=100\nformat quick fs=ntfs label=System\n"
                  "assign letter=%s\nactive\n"
                  "create partition primary\n" % (disk_number, S))
        if recovery:
            script += "shrink minimum=%d\n" % rec_mb
        script += "format quick fs=ntfs label=Windows\nassign letter=%s\n" % W
        if recovery:
            script += ("create partition primary\nformat quick fs=ntfs label=Recovery\n"
                       "set id=27\nassign letter=%s\n" % R)
    else:
        fw = "UEFI"
        log("1/6  Partitioning Disk %s - GPT / UEFI%s" % (disk_number, " + Recovery" if recovery else ""))
        if not _clean_gpt(disk_number, log):
            return 1
        script = ("select disk %s\n"
                  "create partition efi size=260\nformat quick fs=fat32 label=System\n"
                  "assign letter=%s\n"
                  "create partition msr size=16\n"
                  "create partition primary\n" % (disk_number, S))
        if recovery:
            script += "shrink minimum=%d\n" % rec_mb
        script += "format quick fs=ntfs label=Windows\nassign letter=%s\n" % W
        if recovery:
            script += ("create partition primary\nformat quick fs=ntfs label=Recovery\n"
                       "set id=de94bba4-06d1-4d40-a16a-bfd50179d6ac\n"
                       "gpt attributes=0x8000000000000001\n"
                       "assign letter=%s\n" % R)
    if diskpart_stream(script + "exit\n", log) != 0:
        return 1

    img, iso = _image_from_source(src, log)
    if not img:
        return 1
    try:
        log("2/6  Applying Windows (edition %s)%s..." % (index, " as Compact OS" if compact else ""))
        if apply_image(img, index, W, compact, log) != 0:
            log("[X] DISM could not apply the image.")
            return 1
    finally:
        if iso:
            _ps_lines("Dismount-DiskImage -ImagePath '%s'" % iso.replace("'", "''"))

    if drivers:
        if os.path.isdir(drivers) and not pe.tool("dism"):
            log("[!] DISM is not in this WinPE - drivers skipped.")
        elif os.path.isdir(drivers):
            log("3/6  Adding drivers from %s ..." % drivers)
            run_stream(["dism", "/Image:%s:\\" % W, "/Add-Driver",
                        "/Driver:" + drivers, "/Recurse"], log)
        else:
            log("[!] Drivers folder not found - skipped.")
    else:
        log("3/6  No drivers folder - skipped.")

    log("4/6  Writing %s boot files to the new disk (this PC's boot is not touched)..." % fw)
    sys32 = os.path.join(W + ":\\Windows", "System32")
    bcd = os.path.join(sys32, "bcdboot.exe")
    if not os.path.isfile(bcd):
        bcd = "bcdboot"
    if run_stream([bcd, W + ":\\Windows", "/s", S + ":", "/f", fw], log) != 0:
        log("[X] bcdboot failed.")
        return 1

    if recovery:
        log("5/6  Setting up Windows Recovery (WinRE) on its own partition...")
        if not setup_winre(W, R, log):
            log("[!] Recovery was not set up - Windows still works, only the recovery menu is missing.")
    else:
        log("5/6  Recovery partition not requested - skipped.")

    log("6/6  Hiding the helper partitions...")
    _remove_letter(S, log)
    if recovery:
        _remove_letter(R, log)
    log("[OK] Done. Put this disk inside the PC and boot it in %s mode - Windows finishes "
        "setting up and shows the welcome screen." % ("UEFI" if fw == "UEFI" else "Legacy/CSM"))
    return 0


def setup_winre(W, R, log):
    """Copy Winre.wim to R:\\Recovery\\WindowsRE and register it (Microsoft 'Deploy Windows RE')."""
    import shutil
    src = os.path.join(W + ":\\Windows", "System32", "Recovery", "Winre.wim")
    if not os.path.isfile(src):
        log("[X] Winre.wim is not inside this Windows image (some trimmed ISOs remove it).")
        return False
    dst_dir = R + ":\\Recovery\\WindowsRE"
    try:
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copyfile(src, os.path.join(dst_dir, "Winre.wim"))
    except OSError as e:
        log("[X] Could not copy Winre.wim: %s" % e)
        return False
    ra = os.path.join(W + ":\\Windows", "System32", "Reagentc.exe")
    if not os.path.isfile(ra):
        ra = "reagentc"
    if run_stream([ra, "/setreimage", "/path", dst_dir, "/target", W + ":\\Windows"], log) != 0:
        return False
    run_stream([ra, "/info", "/target", W + ":\\Windows"], log)
    return True
