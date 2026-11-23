"""Drive health and repair: SMART counters, surface read test, Windows system repair.

All read-only except sfc / DISM (which only repair Windows' own files).
"""
import time

from .system import ps_json
from .winops import run_stream


def smart_details():
    """Per-disk reliability counters (Get-StorageReliabilityCounter).

    Fields can be empty: support depends on the disk, the USB bridge and the driver.
    """
    script = (
        "Get-PhysicalDisk | ForEach-Object { $p=$_; "
        "$c=$p | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{Id=$p.DeviceId; Name=$p.FriendlyName; Media=[string]$p.MediaType; "
        "Bus=[string]$p.BusType; Health=[string]$p.HealthStatus; Size=$p.Size; "
        "Temp=$c.Temperature; Wear=$c.Wear; Hours=$c.PowerOnHours; "
        "ReadErr=$c.ReadErrorsUncorrected; WriteErr=$c.WriteErrorsUncorrected} }"
    )
    rows = ps_json(script)
    for r in rows:
        bad = []
        if r.get("Health") not in (None, "", "Healthy"):
            bad.append("health")
        if (r.get("ReadErr") or 0) > 0 or (r.get("WriteErr") or 0) > 0:
            bad.append("errors")
        if (r.get("Wear") or 0) >= 80:
            bad.append("wear")
        if (r.get("Temp") or 0) >= 60:
            bad.append("hot")
        r["Verdict"] = "bad" if ("health" in bad or "errors" in bad) else ("warn" if bad else "ok")
    return rows


def surface_test(disk_number, size_bytes, log, stop):
    """Read the WHOLE disk block by block (read-only) and report bad / slow areas.

    Like the read test in Victoria/HD Tune: nothing is written to the disk.
    """
    block = 1024 * 1024                     # 1 MB, sector aligned
    slow_ms = 500
    total = int(size_bytes)
    pos, bad, slow, last = 0, [], 0, -1
    t0 = time.time()
    path = r"\\.\PhysicalDrive%s" % disk_number
    log("Surface read test on Disk %s (%d GB). Read-only - safe." % (disk_number, total // 10**9))
    try:
        f = open(path, "rb", buffering=0)
    except OSError as e:
        log("[X] Can't open the disk: %s (run as Administrator)" % e)
        return 1
    with f:
        while pos < total:
            if stop.is_set():
                log("[X] Stopped by user at %d%%." % (pos * 100 // total))
                break
            n = min(block, total - pos)
            n -= n % 512
            if n <= 0:
                break
            t = time.time()
            try:
                f.seek(pos)
                f.read(n)
                ms = (time.time() - t) * 1000
                if ms > slow_ms:
                    slow += 1
                    if slow <= 30:
                        log("  slow block at %d MB  (%d ms)" % (pos >> 20, ms))
            except OSError:
                bad.append(pos)
                if len(bad) <= 50:
                    log("[X] READ ERROR at %d MB" % (pos >> 20))
            pos += n
            pct = pos * 100 // total
            if pct != last:
                last = pct
                el = time.time() - t0
                speed = (pos / max(el, 0.001)) / 1e6
                eta = (total - pos) / max(speed * 1e6, 1)
                if pct % 2 == 0:
                    log("  %d%%  |  %.0f MB/s  |  left ~%d min  |  bad %d  slow %d"
                        % (pct, speed, eta // 60, len(bad), slow))
    log("-" * 50)
    if bad:
        log("[X] Result: %d unreadable blocks (1 MB each). Back up the data and replace the disk."
            % len(bad))
    elif slow > 20:
        log("[!] Result: no read errors, but %d slow blocks - the disk is getting weak." % slow)
    else:
        log("[OK] Result: whole disk readable, no bad blocks (%d slow)." % slow)
    return 0 if not bad else 2


def system_repair(kind, log):
    """kind: 'sfc' (check/fix Windows files) or 'dism' (repair the component store)."""
    if kind == "dism":
        log("DISM downloads clean files from Windows Update - keep the internet on.")
        return run_stream(["DISM", "/Online", "/Cleanup-Image", "/RestoreHealth"], log)
    return run_stream(["sfc", "/scannow"], log)
