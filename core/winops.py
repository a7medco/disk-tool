"""Backend operations for the GUI: run commands and stream output via a callback.

GUI panels call these with a `log(line)` function; the command output is fed
to it line by line so the window shows progress live. No input() anywhere.
"""
import os
import subprocess
import sys
import tempfile

from .system import PS, ps_json

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # no console flash


def run_stream(cmd, log, cwd=None):
    """Run a command, send each output line to log(), return exit code."""
    log("> " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=CREATE_NO_WINDOW, cwd=cwd,
                             stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        log("[X] command not found: %s" % (cmd[0] if isinstance(cmd, list) else cmd))
        return 127
    for raw in iter(p.stdout.readline, b""):
        raw = raw.replace(b"\x00", b"")          # sfc prints UTF-16
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.strip():
            log(line.split("\r")[-1])            # keep last progress update
    p.stdout.close()
    return p.wait()


def ps_stream(script, log):
    return run_stream(PS + [script], log)


def diskpart_stream(script_text, log):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(script_text)
        path = f.name
    try:
        log("> diskpart script:")
        for ln in script_text.splitlines():
            log("    " + ln)
        return run_stream(["diskpart", "/s", path], log)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---- high level operations ------------------------------------------------

DISKS_PS = (
    # one PowerShell start instead of two; Storage cmdlets first, WMI fallback if they fail
    "$h=@{}; Get-PhysicalDisk -ErrorAction SilentlyContinue | ForEach-Object { $h[[string]$_.DeviceId]=[string]$_.HealthStatus };"
    "$d=@(Get-Disk -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{"
    "Number=$_.Number; FriendlyName=$_.FriendlyName; Size=$_.Size; BusType=[string]$_.BusType;"
    "PartitionStyle=[string]$_.PartitionStyle; IsBoot=$_.IsBoot; IsSystem=$_.IsSystem;"
    "HealthStatus=$(if($h.ContainsKey([string]$_.Number)){$h[[string]$_.Number]}else{'Unknown'})} });"
    "if($d.Count -eq 0){ $sys=$env:SystemDrive;"
    " $d=@(Get-CimInstance Win32_DiskDrive | ForEach-Object { $dd=$_;"
    "  $boot=@(Get-CimAssociatedInstance -InputObject $dd -ResultClassName Win32_DiskPartition |"
    "   Get-CimAssociatedInstance -ResultClassName Win32_LogicalDisk | Where-Object DeviceID -eq $sys).Count -gt 0;"
    "  [pscustomobject]@{Number=$dd.Index; FriendlyName=$dd.Model; Size=$dd.Size;"
    "  BusType=$(if($dd.InterfaceType -eq 'USB' -or $dd.MediaType -like 'Removable*'){'USB'}else{[string]$dd.InterfaceType});"
    "  PartitionStyle=''; IsBoot=$boot; IsSystem=$boot; HealthStatus=$(if($dd.Status -eq 'OK'){'Healthy'}else{[string]$dd.Status})} }) }"
    "$d"
)

_disk_cache = {"t": 0.0, "rows": None}
_disk_lock = __import__("threading").Lock()


def list_disks(max_age=15):
    """All disks. Cached for a few seconds - several pages ask for the list."""
    import time
    with _disk_lock:
        if _disk_cache["rows"] is not None and time.time() - _disk_cache["t"] < max_age:
            return _disk_cache["rows"]
        t0 = time.time()
        rows = ps_json(DISKS_PS)
        _disk_cache.update(t=time.time(), rows=rows, took=round(time.time() - t0, 1))
        return rows


def disks_took():
    return _disk_cache.get("took", 0)


def format_disk(number, fs, scheme, label, log):
    """Erase a whole disk and create one partition. fs: NTFS/exFAT/FAT32."""
    script = "\n".join([
        "select disk %s" % number,
        "clean",
        "convert %s" % ("gpt" if scheme.upper() == "GPT" else "mbr"),
        "create partition primary",
        'format fs=%s quick label="%s"' % (fs.lower(), label),
        "assign",
        "exit",
    ]) + "\n"
    return diskpart_stream(script, log)


def chkdsk(drive_letter, level, log):
    """level: 'scan' (read-only), 'fix' (/f), 'full' (/r - bad sectors, slow)."""
    flag = {"scan": ["/scan"], "fix": ["/f"], "full": ["/r"]}[level]
    sysdrv = os.environ.get("SystemDrive", "C:")[:1].upper()
    if level != "scan" and drive_letter.upper() == sysdrv:
        # Windows drive is in use: answer Y to "schedule on next restart?"
        log("Windows drive is in use - the repair is scheduled for the next restart.")
        return run_stream(["cmd", "/c", "echo Y| chkdsk %s: %s" % (sysdrv, flag[0])], log)
    return run_stream(["chkdsk", drive_letter + ":"] + flag, log)


def robocopy(src, dst, log):
    # /Z resumable, /E all subfolders, /R:2 retry, /NP no per-file %, /TEE
    return run_stream(["robocopy", src, dst, "/Z", "/E", "/R:2", "/W:3", "/NP"], log)


# ========================= extra operations =============================
import os.path as _osp
from .system import capture as _capture


def _ps_lines(script):
    code, out = _capture(PS + [script])
    return out.splitlines() if code == 0 else []


def device_locks():
    """Read-only: is this PC clean or managed/locked? Returns list of dicts."""
    items = []

    # BitLocker (disk encryption)
    bl = ps_json("Get-BitLockerVolume | Select-Object MountPoint,ProtectionStatus,VolumeStatus")
    on = [b for b in bl if str(b.get("ProtectionStatus")) in ("1", "On")]
    if on:
        items.append({"label": "BitLocker", "value": "On (%s)" % ", ".join(
            str(b.get("MountPoint")) for b in on), "sev": "warn",
            "note": "Drive is encrypted - you need the password or recovery key."})
    else:
        items.append({"label": "BitLocker", "value": "Off", "sev": "ok", "note": ""})

    # Azure AD / organisation management
    reg = {}
    for ln in _ps_lines("dsregcmd /status"):
        if ":" in ln:
            k, v = ln.split(":", 1)
            reg[k.strip()] = v.strip()
    managed = reg.get("AzureAdJoined", "NO").upper() == "YES" or reg.get("MDMUrl")
    dom = reg.get("DomainJoined", "NO").upper() == "YES"
    if managed:
        items.append({"label": "Organisation (Azure AD / Intune)", "value": "Managed",
                      "sev": "bad", "note": "A company/school controls this PC via MDM."})
    elif dom:
        items.append({"label": "Domain", "value": "Joined", "sev": "warn",
                      "note": "Joined to a company Active Directory domain."})
    else:
        items.append({"label": "Organisation / Domain", "value": "None", "sev": "ok", "note": ""})

    # Secure Boot
    sb = _ps_lines("try{[string](Confirm-SecureBootUEFI)}catch{'NA'}")
    sbv = (sb[0].strip() if sb else "NA")
    items.append({"label": "Secure Boot",
                  "value": {"True": "On", "False": "Off"}.get(sbv, "Not supported (legacy BIOS)"),
                  "sev": "info", "note": ""})

    # Windows activation
    act = _ps_lines('cscript //nologo "%windir%\\System32\\slmgr.vbs" /xpr')
    actv = next((l.strip() for l in act if l.strip()), "Unknown")
    items.append({"label": "Windows activation", "value": actv, "sev": "info", "note": ""})
    return items


def list_local_users():
    users = ps_json("Get-LocalUser | Where-Object Enabled | Select-Object Name")
    return [u.get("Name") for u in users if u.get("Name")]


def reset_password(user, new_password, log):
    return run_stream(["net", "user", user, new_password], log)


def create_admin(user, password, log):
    c = run_stream(["net", "user", user, password, "/add"], log)
    if c == 0:
        c = run_stream(["net", "localgroup", "Administrators", user, "/add"], log)
    return c


def assign_remove_letter(disk_number, letter, action, log):
    """action 'assign' or 'remove' a drive letter on the first partition."""
    verb = "assign letter=%s" % letter if action == "assign" else "remove letter=%s" % letter
    script = "select disk %s\nselect partition 1\n%s\nexit\n" % (disk_number, verb)
    return diskpart_stream(script, log)


# ---- VeraCrypt (Windows) --------------------------------------------------
VC_DIRS = [r"C:\Program Files\VeraCrypt", r"C:\Program Files (x86)\VeraCrypt"]


def _vc(exe):
    """Installed VeraCrypt first, else the portable copy shipped in bin\\veracrypt."""
    for d in VC_DIRS:
        p = _osp.join(d, exe)
        if _osp.exists(p):
            return p
    from .paths import DATA
    arch = (os.environ.get("PROCESSOR_ARCHITEW6432") or
            os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    suffix = "-arm64" if arch == "ARM64" else "-x64"
    p = _osp.join(DATA, "bin", "veracrypt", exe.replace(".exe", suffix + ".exe"))
    return p if _osp.exists(p) else None


def veracrypt_create(path, size, fs, password, log):
    exe = _vc("VeraCrypt Format.exe")
    if not exe:
        log("[X] VeraCrypt not found (Program Files or bin\\veracrypt).")
        return 1
    return run_stream([exe, "/create", path, "/size", size, "/password", password,
                       "/encryption", "AES", "/hash", "sha512", "/filesystem", fs,
                       "/quick", "/silent", "/force"], log)


def veracrypt_mount(path, letter, password, log):
    exe = _vc("VeraCrypt.exe")
    if not exe:
        log("[X] VeraCrypt not found (Program Files or bin\\veracrypt).")
        return 1
    return run_stream([exe, "/q", "/s", "/v", path, "/l", letter, "/p", password], log)


def veracrypt_dismount(letter, log):
    exe = _vc("VeraCrypt.exe")
    if not exe:
        log("[X] VeraCrypt not found (Program Files or bin\\veracrypt).")
        return 1
    args = [exe, "/q", "/u"] + ([letter] if letter else [])
    return run_stream(args, log)


# ---- bootable Windows USB -------------------------------------------------
def bootable_windows_usb(iso, disk_number, letter, log):
    """Format the USB FAT32, copy the ISO, split install.wim if > 4GB. UEFI."""
    if not _osp.isfile(iso):
        log("[X] ISO not found: %s" % iso)
        return 1
    log("Preparing the USB (FAT32, bootable)...")
    script = ("select disk %s\nclean\nconvert mbr\ncreate partition primary\n"
              "format fs=fat32 quick label=WINUSB\nassign letter=%s\nactive\nexit\n"
              % (disk_number, letter))
    if diskpart_stream(script, log) != 0:
        return 1

    log("Mounting the ISO...")
    src = _ps_lines("$r=Mount-DiskImage -ImagePath '%s' -PassThru;"
                    "($r | Get-Volume).DriveLetter" % iso)
    srcL = next((l.strip() for l in src if l.strip()), "")
    if not srcL:
        log("[X] Could not mount the ISO.")
        return 1
    srcR, dstR = srcL + ":\\", letter + ":\\"
    try:
        log("Copying files (everything except the big install.wim)...")
        run_stream(["robocopy", srcR, dstR, "/s", "/max:3800000000", "/np", "/r:1", "/w:1"], log)
        wim = srcR + "sources\\install.wim"
        if _osp.exists(wim):
            log("Splitting install.wim into < 4GB parts...")
            run_stream(["dism", "/Split-Image", "/ImageFile:" + wim,
                        "/SWMFile:" + dstR + "sources\\install.swm", "/FileSize:3800"], log)
        log("[OK] Bootable Windows USB is ready (UEFI).")
        return 0
    finally:
        _ps_lines("Dismount-DiskImage -ImagePath '%s'" % iso)


# ========================= v2: drivers, raw image, partitions ==============
import sys as _sys
import time as _time


def export_drivers(folder, log):
    """Back up every third-party driver (DISM, built into Windows)."""
    os.makedirs(folder, exist_ok=True)          # DISM needs the folder to exist
    c = run_stream(["dism", "/online", "/export-driver", "/destination:" + folder], log)
    if c == 0:
        log("[OK] Drivers saved to %s" % folder)
    return c


def import_drivers(folder, log):
    """Install every .inf under the folder on matching devices."""
    if not _osp.isdir(folder):
        log("[X] Folder not found: %s" % folder)
        return 1
    c = run_stream(["pnputil", "/add-driver", _osp.join(folder, "*.inf"),
                    "/subdirs", "/install"], log)
    # pnputil returns 3010 when a restart is needed
    if c in (0, 3010):
        log("[OK] Drivers installed%s." % (" - restart to finish" if c == 3010 else ""))
        return 0
    return c


def write_image(img, disk_number, log, stop=None):
    """Write a raw .img/.iso to \\\\.\\PhysicalDriveN (like dd). Erases the disk."""
    if not _osp.isfile(img):
        log("[X] File not found: %s" % img)
        return 1
    log("Clearing the disk so Windows releases it...")
    if diskpart_stream("select disk %s\nclean\nexit\n" % disk_number, log) != 0:
        return 1
    total = _osp.getsize(img)
    block = 4 * 1024 * 1024
    done, last = 0, -1
    try:
        with open(img, "rb") as src, \
                open(r"\\.\PhysicalDrive%s" % disk_number, "r+b", buffering=0) as dst:
            while True:
                if stop is not None and stop.is_set():
                    log("[X] Stopped by user - the USB is not usable now.")
                    return 1
                buf = src.read(block)
                if not buf:
                    break
                if len(buf) % 512:                # raw disk writes must be whole sectors
                    buf += b"\0" * (512 - len(buf) % 512)
                dst.write(buf)
                done += len(buf)
                pct = min(100, done * 100 // max(total, 1))
                if pct // 5 != last:
                    last = pct // 5
                    log("  written %d%%  (%d / %d MB)" % (pct, done >> 20, total >> 20))
    except OSError as e:
        log("[X] Write error: %s" % e)
        return 1
    log("[OK] Image written. If Windows asks to format the disk, click Cancel - that's normal.")
    return 0


def format_volume(letter, fs, label, log):
    """Quick-format one partition (keeps the other partitions)."""
    return ps_stream("Format-Volume -DriveLetter %s -FileSystem %s -NewFileSystemLabel '%s' "
                     "-Confirm:$false -Force | Format-Table -AutoSize | Out-String -Width 200"
                     % (letter, fs, label.replace("'", "")), log)


def eject(letter, log):
    c = ps_stream("(New-Object -ComObject Shell.Application).Namespace(17)"
                  ".ParseName('%s:').InvokeVerb('Eject')" % letter, log)
    if c == 0:
        log("[OK] %s: ejected - safe to unplug." % letter)
    return c


# ---- RAM test ---------------------------------------------------------------
def ram_test(log):
    """Schedule the Windows Memory Diagnostic for the next boot and restart NOW."""
    if run_stream(["bcdedit", "/bootsequence", "{memdiag}"], log) != 0:
        log("[X] Could not schedule the memory test (run as Administrator).")
        return 1
    log("Memory test scheduled. Restarting in 5 seconds...")
    return run_stream(["shutdown", "/r", "/t", "5",
                       "/c", "Restarting to run the Windows Memory Diagnostic."], log)


def memtest_results():
    """Last results of the Windows Memory Diagnostic (System log)."""
    rows = ps_json("Get-WinEvent -FilterHashtable @{LogName='System';"
                   "ProviderName='Microsoft-Windows-MemoryDiagnostics-Results'} "
                   "-MaxEvents 6 -ErrorAction SilentlyContinue | "
                   "Select-Object @{n='Time';e={$_.TimeCreated.ToString('yyyy-MM-dd HH:mm')}},"
                   "Id,Message")
    out = []
    for r in rows:
        eid = int(r.get("Id") or 0)
        if eid in (1201, 1101):
            res = "pass"
        elif eid in (1202, 1102):
            res = "fail"
        else:
            res = "info"
        out.append({"time": r.get("Time", ""), "id": eid, "result": res,
                    "msg": (r.get("Message") or "").strip().splitlines()[0][:160]
                    if r.get("Message") else ""})
    return out


# ---- right-click context menu (registry) ----------------------------------
MENU_ITEMS = [("Format", "format"), ("FastCopy", "copy"), ("Repair", "repair")]
MENU_BASE = r"HKCU\Software\Classes\Drive\shell"


def install_context_menu(log):
    from . import paths
    for key, goto in MENU_ITEMS:
        exe, cmd = paths.launch_cmd("--goto", goto)
        k = MENU_BASE + "\\DiskTool" + key
        run_stream(["reg", "add", k, "/ve", "/d", "Disk Tool: " + key, "/f"], log)
        run_stream(["reg", "add", k, "/v", "Icon", "/d", exe, "/f"], log)
        run_stream(["reg", "add", k + "\\command", "/ve", "/d", cmd, "/f"], log)
    log("[OK] Right-click a drive in Explorer (Windows 11: 'Show more options').")
    return 0


def remove_context_menu(log):
    for key, _ in MENU_ITEMS:
        run_stream(["reg", "delete", MENU_BASE + "\\DiskTool" + key, "/f"], log)
    log("[OK] Removed.")
    return 0
