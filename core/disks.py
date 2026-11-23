"""Disk discovery and selection on Windows (PowerShell Storage cmdlets)."""
from . import ui
from .system import ps_json


def list_disks():
    """All physical disks with number, model, size, bus, health, boot flag."""
    disks = ps_json("Get-Disk | Select-Object Number,FriendlyName,Size,BusType,"
                    "PartitionStyle,IsBoot,IsSystem,OperationalStatus")
    health = {}
    for p in ps_json("Get-PhysicalDisk | Select-Object DeviceId,MediaType,HealthStatus"):
        health[str(p.get("DeviceId"))] = p
    for d in disks:
        h = health.get(str(d.get("Number")), {})
        d["HealthStatus"] = h.get("HealthStatus", "Unknown")
        d["MediaType"] = h.get("MediaType", "")
    return disks


def describe(d):
    gb = (d.get("Size") or 0) / 1000 ** 3
    boot = "BOOT" if (d.get("IsBoot") or d.get("IsSystem")) else "data"
    return "Disk %-2s %7.1f GB  %-26s %-7s %-6s %s" % (
        d.get("Number"), gb, (d.get("FriendlyName") or "?")[:26],
        d.get("BusType", "?"), boot, d.get("PartitionStyle", ""))


def pick_disk(title="Select a disk", external_only=True, allow_boot=False):
    disks = list_disks()
    rows = []
    for d in disks:
        if external_only and d.get("BusType") not in ("USB",):
            continue
        if not allow_boot and (d.get("IsBoot") or d.get("IsSystem")):
            continue
        rows.append(d)
    if not rows:
        ui.warn("No %sdisks found." % ("external " if external_only else ""))
        return None
    idx = ui.choose(title + "   (num / size / model / bus / role / scheme)",
                    [describe(d) for d in rows])
    return None if idx is None else rows[idx]


def volumes_of(disk_number):
    """Partitions with a drive letter on the given physical disk."""
    return ps_json("Get-Partition -DiskNumber %s | Where-Object DriveLetter | "
                   "Select-Object PartitionNumber,DriveLetter,Size,Type" % disk_number)


def pick_volume(disk_number, title="Select a volume"):
    vols = volumes_of(disk_number)
    if not vols:
        ui.warn("No lettered volumes on disk %s." % disk_number)
        return None
    labels = ["%s:  %6.1f GB  %s" % (v.get("DriveLetter"),
              (v.get("Size") or 0) / 1000 ** 3, v.get("Type", "")) for v in vols]
    idx = ui.choose(title, labels)
    return None if idx is None else vols[idx]
