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


def _online_first(script):
    import re as _re
    return _re.sub(r"(select disk \d+\n)", r"\1online disk noerr\nattributes disk clear readonly noerr\n",
                   script, flags=_re.I)


def diskpart_stream(script_text, log):
    script_text = _online_first(script_text)
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

DISKS_PS = r"""
$dd=@(Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue)
$cur=@{}; $usb=@{}
foreach($x in $dd){ $cur[[int]$x.Index]=[string]$x.PNPDeviceID }
for($k=0; $k -lt 8; $k++){
  foreach($i in @($cur.Keys)){ if($cur[$i] -match '^USB'){ $usb[$i]=$true; $cur[$i]=$null } }
  $ids=@($cur.Keys | Where-Object { $cur[$_] } | ForEach-Object { $cur[$_] })
  if($ids.Count -eq 0){ break }
  $map=@{}
  Get-PnpDeviceProperty -InstanceId $ids -KeyName DEVPKEY_Device_Parent -ErrorAction SilentlyContinue |
    ForEach-Object { $map[[string]$_.InstanceId]=[string]$_.Data }
  foreach($i in @($cur.Keys)){ if($cur[$i]){ $cur[$i]=$map[$cur[$i]] } }
}
$ext=@{}
foreach($x in $dd){ $ext[[int]$x.Index]=@{usb=[bool]$usb[[int]$x.Index]; media=[string]$x.MediaType} }
$h=@{}; Get-PhysicalDisk -ErrorAction SilentlyContinue | ForEach-Object { $h[[string]$_.DeviceId]=[string]$_.HealthStatus }
$d=@(Get-Disk -ErrorAction SilentlyContinue | ForEach-Object {
  $n=[int]$_.Number; $e=$ext[$n]; $bus=[string]$_.BusType
  $isUsb = ($e -and $e.usb) -or $bus -eq 'USB'
  $vols=@(Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue | ForEach-Object {
    $v = $_ | Get-Volume -ErrorAction SilentlyContinue
    [pscustomobject]@{Letter=[string]$_.DriveLetter; Size=$_.Size; Free=$(if($v){$v.SizeRemaining}else{$null});
      Label=$(if($v){$v.FileSystemLabel}else{''}); FS=$(if($v){$v.FileSystem}else{''}); Type=[string]$_.Type} })
  [pscustomobject]@{
    Number=$n; FriendlyName=$_.FriendlyName; Size=$_.Size; BusType=$bus; Serial=([string]$_.SerialNumber).Trim();
    Bus=$(if($isUsb -and $bus -ne 'USB'){'USB (UASP)'}elseif($isUsb){'USB'}else{$bus});
    IsExternal=[bool]($isUsb -or ($e -and $e.media -like 'External*') -or ($e -and $e.media -like 'Removable*'));
    PartitionStyle=[string]$_.PartitionStyle; IsBoot=$_.IsBoot; IsSystem=$_.IsSystem; IsOffline=$_.IsOffline;
    Unallocated=($_.PartitionStyle -eq 'RAW' -or ($_.Size - $_.AllocatedSize) -gt 1GB);
    HealthStatus=$(if($h.ContainsKey([string]$n)){$h[[string]$n]}else{'Unknown'}); Volumes=$vols }
})
if($d.Count -eq 0){ $sys=$env:SystemDrive
  $d=@(Get-CimInstance Win32_DiskDrive | ForEach-Object { $dd=$_; $e=$ext[[int]$dd.Index]
    $boot=@(Get-CimAssociatedInstance -InputObject $dd -ResultClassName Win32_DiskPartition |
      Get-CimAssociatedInstance -ResultClassName Win32_LogicalDisk | Where-Object DeviceID -eq $sys).Count -gt 0
    [pscustomobject]@{Number=$dd.Index; FriendlyName=$dd.Model; Size=$dd.Size; BusType=[string]$dd.InterfaceType; Serial=([string]$dd.SerialNumber).Trim();
      Bus=$(if($e.usb){'USB'}else{[string]$dd.InterfaceType}); IsExternal=[bool]$e.usb;
      PartitionStyle=''; IsBoot=$boot; IsSystem=$boot; IsOffline=$false; Unallocated=$false;
      HealthStatus=$(if($dd.Status -eq 'OK'){'Healthy'}else{[string]$dd.Status}); Volumes=@()} }) }
$d
"""

_disk_cache = {"t": 0.0, "rows": None}
_disk_lock = __import__("threading").Lock()


def list_disks(max_age=600):
    """All disks. Cached for a few seconds - several pages ask for the list."""
    import time
    with _disk_lock:
        if _disk_cache["rows"] is not None and time.time() - _disk_cache["t"] < max_age:
            _disk_cache["cached"] = True
            return _disk_cache["rows"]
        _disk_cache["cached"] = False
        t0 = time.time()
        rows = ps_json(DISKS_PS)
        _disk_cache.update(t=time.time(), rows=rows, took=round(time.time() - t0, 1))
        return rows


def disks_took():
    return 0 if _disk_cache.get("cached") else _disk_cache.get("took", 0)


def format_disk(number, fs, scheme, label, log):
    """Erase a whole disk and create one partition. fs: NTFS/exFAT/FAT32."""
    from . import guard
    number = guard.check_disk(number)["Number"]
    fs = guard.choice(fs, guard.FS_DISK, "file system")
    scheme = guard.choice(scheme, guard.SCHEMES, "partition scheme")
    label = guard.label(label, fs)
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
    from .system import ps_text
    code, out = ps_text(script)
    return out.splitlines() if code == 0 else []


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
    from . import guard
    disk_number = guard.check_disk(disk_number)["Number"]
    letter = guard.letter(letter)
    action = guard.choice(action, ("assign", "remove"), "action")
    verb = "assign letter=%s" % letter if action == "assign" else "remove letter=%s" % letter
    script = "select disk %s\nselect partition 1\n%s\nexit\n" % (disk_number, verb)
    return diskpart_stream(script, log)


# ---- bootable Windows USB -------------------------------------------------
def bootable_windows_usb(iso, disk_number, letter, log):
    """Format the USB FAT32, copy the ISO, split install.wim if > 4GB. UEFI."""
    if not _osp.isfile(iso):
        log("[X] ISO not found: %s" % iso)
        return 1
    from . import guard
    d = guard.check_disk(disk_number)
    guard.file_not_on_disk(iso, d)
    disk_number, letter = d["Number"], guard.letter(letter)
    log("Preparing the USB (FAT32, bootable)...")
    script = ("select disk %s\nclean\nconvert mbr\ncreate partition primary\n"
              "format fs=fat32 quick label=WINUSB\nassign letter=%s\nactive\nexit\n"
              % (disk_number, letter))
    if diskpart_stream(script, log) != 0:
        return 1

    log("Mounting the ISO...")
    src = _ps_lines("$r=Mount-DiskImage -ImagePath '%s' -PassThru;"
                    "($r | Get-Volume).DriveLetter" % iso.replace("'", "''"))
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
        _ps_lines("Dismount-DiskImage -ImagePath '%s'" % iso.replace("'", "''"))


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
    from . import guard
    d = guard.check_disk(disk_number)
    guard.file_not_on_disk(img, d)
    disk_number = d["Number"]
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
    from . import guard
    letter = guard.check_volume(letter)[0]
    fs = guard.choice(fs, guard.FS_VOL, "file system")
    label = guard.label(label, fs)
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


def save_image(disk_number, size_bytes, out_path, log, stop=None):
    """Back up a whole disk/USB to a raw .img file (reverse of write_image). Read-only on the disk."""
    import shutil
    total = int(size_bytes)
    out_dir = _osp.dirname(_osp.abspath(out_path)) or "."
    if not _osp.isdir(out_dir):
        log("[X] Folder not found: %s" % out_dir)
        return 1
    letters = [str(r.get("DriveLetter") or "").upper() for r in ps_json(
        "Get-Partition -DiskNumber %d -ErrorAction SilentlyContinue | Select-Object DriveLetter"
        % int(disk_number))]
    if _osp.splitdrive(_osp.abspath(out_path))[0][:1].upper() in [L for L in letters if L]:
        log("[X] You can't save the image onto the same disk you are copying.")
        return 1
    free = shutil.disk_usage(out_dir).free
    if free < total:
        log("[X] Not enough space: need %d GB, free %d GB." % (total // 10**9 + 1, free // 10**9))
        return 1
    block = 4 * 1024 * 1024
    done, last, t0 = 0, -1, _time.time()
    log("Copying Disk %s (%d GB) to %s ..." % (disk_number, total // 10**9, out_path))
    try:
        with open(r"\\.\PhysicalDrive%s" % disk_number, "rb", buffering=0) as src, \
                open(out_path, "wb") as dst:
            while done < total:
                if stop is not None and stop.is_set():
                    log("[X] Stopped by user - the .img file is incomplete.")
                    return 1
                n = min(block, total - done)
                n -= n % 512
                if n <= 0:
                    break
                buf = src.read(n)
                if not buf:
                    break
                dst.write(buf)
                done += len(buf)
                pct = done * 100 // max(total, 1)
                if pct // 2 != last:
                    last = pct // 2
                    sp = done / max(_time.time() - t0, 0.001) / 1e6
                    log("  %d%%  |  %.0f MB/s  |  left ~%d min" % (pct, sp, (total - done) / max(sp * 1e6, 1) // 60))
    except OSError as e:
        log("[X] Read/write error at %d MB: %s" % (done >> 20, e))
        return 1
    log("[OK] Saved %d MB to %s. Restore it later with 'Write image'." % (done >> 20, out_path))
    return 0
