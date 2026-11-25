"""Disk list without PowerShell/WMI - for Windows PE.

Reads every \\\\.\\PhysicalDriveN with documented Windows IOCTLs (works in any
language, no diskpart text parsing):
  IOCTL_STORAGE_QUERY_PROPERTY      model, serial, bus type, removable
  IOCTL_DISK_GET_LENGTH_INFO        exact size in bytes
  IOCTL_DISK_GET_DRIVE_LAYOUT_EX    MBR / GPT / RAW, Disk ID, partitions
  IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS   which disk each drive letter is on

Rows have the same keys as winops.DISKS_PS (Number, FriendlyName, Size, Serial,
Volumes, IsBoot, IsSystem ...) plus: DiskId, Partitions, HasWindows, IsVentoy.

Disk ID (what diskpart shows as "Disk ID"):
  MBR  -> 8 hex digits of the disk signature, e.g. 1A2B3C4D
  GPT  -> the disk GUID, e.g. 0F1E...-....
  empty/new disk (signature 00000000 or RAW) -> "" (never used to match a disk)
"""
import os
import struct
import sys

IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_DISK_GET_DRIVE_LAYOUT_EX = 0x00070050
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000

BUS = {0: "Unknown", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre Channel",
       7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC",
       14: "Virtual", 15: "File Backed Virtual", 16: "Storage Spaces", 17: "NVMe", 18: "SCM", 19: "UFS"}
STYLE = {0: "MBR", 1: "GPT", 2: "RAW"}

GPT_ESP = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"        # EFI system partition
GPT_MSR = "E3C9E316-0B5C-4DB8-817D-F92DF00215AE"        # Microsoft reserved
GPT_RECOVERY = "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC"   # Windows recovery
MBR_RECOVERY = 0x27
MBR_EFI = 0xEF

PART_SIZE = 144            # sizeof(PARTITION_INFORMATION_EX)
LAYOUT_HEAD = 48           # PartitionStyle + PartitionCount + 40-byte union


# ------------------------------------------------------------ pure parsing (tested on any OS) ----
def guid(b):
    """16 raw bytes -> 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX' (Windows GUID byte order)."""
    d1, d2, d3 = struct.unpack_from("<IHH", b, 0)
    d4 = b[8:16]
    return "%08X-%04X-%04X-%s-%s" % (d1, d2, d3, d4[:2].hex().upper(), d4[2:].hex().upper())


def disk_id(style, raw_union):
    """Disk ID for the 3 cases: MBR signature (8 hex), GPT GUID, empty/RAW -> ''."""
    if style == "MBR":
        sig = struct.unpack_from("<I", raw_union, 0)[0]
        return "" if sig == 0 else "%08X" % sig
    if style == "GPT":
        g = guid(raw_union[:16])
        return "" if g == "00000000-0000-0000-0000-000000000000" else g
    return ""


def parse_layout(buf):
    """DRIVE_LAYOUT_INFORMATION_EX bytes -> {Style, DiskId, Parts:[...]}."""
    style_n, count = struct.unpack_from("<II", buf, 0)
    style = STYLE.get(style_n, "RAW")
    out = {"Style": style, "DiskId": disk_id(style, buf[8:48]), "Parts": []}
    for i in range(count):
        o = LAYOUT_HEAD + i * PART_SIZE
        if o + PART_SIZE > len(buf):
            break
        pstyle, = struct.unpack_from("<I", buf, o)
        start, length, number = struct.unpack_from("<qqI", buf, o + 8)
        if length <= 0:
            continue
        u = o + 32
        p = {"Number": number, "Offset": start, "Size": length}
        if pstyle == 0:                                   # MBR entry
            ptype = buf[u]
            if ptype == 0:
                continue
            p.update(Type=ptype, Active=bool(buf[u + 1]), Name="")
        elif pstyle == 1:                                 # GPT entry
            p.update(Type=guid(buf[u:u + 16]),
                     Name=buf[u + 40:u + 112].decode("utf-16-le", "ignore").split("\x00")[0])
        else:
            continue
        out["Parts"].append(p)
    return out


def parse_descriptor(buf):
    """STORAGE_DEVICE_DESCRIPTOR bytes -> {FriendlyName, Serial, BusType, Removable}."""
    def s(off):
        if not off or off >= len(buf):
            return ""
        return buf[off:buf.index(b"\x00", off) if b"\x00" in buf[off:] else len(buf)] \
            .decode("ascii", "ignore").strip()
    removable = bool(buf[10])
    v_off, p_off, _r, ser_off, bus = struct.unpack_from("<IIIII", buf, 12)
    vendor, product = s(v_off), s(p_off)
    name = (vendor + " " + product).strip() if vendor and not product.startswith(vendor) else product
    return {"FriendlyName": name or "Disk", "Serial": s(ser_off).strip("."),
            "BusType": BUS.get(bus, "Unknown"), "Removable": removable}


def windows_signs(parts, style):
    """Partitions that only a Windows install (or another OS boot disk) creates."""
    why = []
    for p in parts:
        t = p.get("Type")
        if style == "GPT" and t == GPT_ESP:
            why.append("EFI system partition")
        elif style == "GPT" and t == GPT_RECOVERY:
            why.append("Windows recovery partition")
        elif style == "MBR" and t == MBR_RECOVERY:
            why.append("Windows recovery partition")
    return why


def is_ventoy(parts, volumes):
    labels = {str(v.get("Label") or "").upper() for v in volumes}
    names = {str(p.get("Name") or "").upper() for p in parts}
    return bool({"VENTOY", "VTOYEFI"} & (labels | names))


# ------------------------------------------------------------ Windows calls ----
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateFileW.restype = wintypes.HANDLE
    _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                     ctypes.c_void_p]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _INVALID = wintypes.HANDLE(-1).value


def _open(path, access=0x80000000):          # GENERIC_READ
    h = _k32.CreateFileW(path, access, 3, None, 3, 0, None)   # share R/W, OPEN_EXISTING
    return None if h in (None, _INVALID) else h


def _ioctl(h, code, inp=b"", size=4096, grow=True):
    while True:
        out = ctypes.create_string_buffer(size)
        got = wintypes.DWORD(0)
        ib = ctypes.create_string_buffer(inp, len(inp)) if inp else None
        ok = _k32.DeviceIoControl(h, code, ib, len(inp), out, size, ctypes.byref(got), None)
        if ok:
            return out.raw[:got.value]
        err = ctypes.get_last_error()
        if grow and err in (122, 234) and size < (1 << 20):     # buffer too small / more data
            size *= 4
            continue
        return None


def _volume_rows():
    """{disk_number: [volume dict, ...]} for every drive letter on a physical disk."""
    res = {}
    mask = _k32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        L = chr(65 + i)
        root = L + ":\\"
        if _k32.GetDriveTypeW(root) not in (2, 3):              # removable / fixed only
            continue
        h = _open("\\\\.\\%s:" % L, 0)
        if not h:
            continue
        try:
            ext = _ioctl(h, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, size=8 + 24 * 4)
        finally:
            _k32.CloseHandle(h)
        if not ext:
            continue
        n_ext, = struct.unpack_from("<I", ext, 0)
        if n_ext < 1:
            continue
        disk, offset, length = struct.unpack_from("<I4xqq", ext, 8)
        lab, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
        if not _k32.GetVolumeInformationW(root, lab, 261, None, None, None, fs, 261):
            lab.value, fs.value = "", ""
        free = ctypes.c_ulonglong(0)
        if not _k32.GetDiskFreeSpaceExW(root, None, None, ctypes.byref(free)):
            free = None
        res.setdefault(disk, []).append({
            "Letter": L, "Size": length, "Offset": offset, "Free": free.value if free else None,
            "Label": lab.value, "FS": fs.value, "Type": "",
            "Windows": os.path.isfile(root + r"Windows\System32\config\SYSTEM")})
    return res


def list_disks():
    """All physical disks (same shape as winops.list_disks rows)."""
    if sys.platform != "win32":
        return []
    vols = _volume_rows()
    rows = []
    misses = 0
    for n in range(64):
        h = _open("\\\\.\\PhysicalDrive%d" % n)
        if not h:
            misses += 1
            if misses > 8:                       # numbers can have gaps after hot-unplug
                break
            continue
        misses = 0
        try:
            desc = _ioctl(h, IOCTL_STORAGE_QUERY_PROPERTY, struct.pack("<IIB3x", 0, 0, 0), size=1024, grow=False)
            ln = _ioctl(h, IOCTL_DISK_GET_LENGTH_INFO, size=8, grow=False)
            lay = _ioctl(h, IOCTL_DISK_GET_DRIVE_LAYOUT_EX, size=LAYOUT_HEAD + PART_SIZE * 16)
        finally:
            _k32.CloseHandle(h)
        d = parse_descriptor(desc) if desc else {"FriendlyName": "Disk", "Serial": "", "BusType": "Unknown",
                                                 "Removable": False}
        layout = parse_layout(lay) if lay else {"Style": "RAW", "DiskId": "", "Parts": []}
        size = struct.unpack("<q", ln)[0] if ln and len(ln) >= 8 else 0
        v = sorted(vols.get(n, []), key=lambda x: x["Offset"])
        signs = windows_signs(layout["Parts"], layout["Style"])
        if any(x["Windows"] for x in v):
            signs.insert(0, "Windows folder on " + ", ".join(x["Letter"] + ":" for x in v if x["Windows"]))
        bus = d["BusType"]
        used = sum(p["Size"] for p in layout["Parts"])
        rows.append({
            "Number": n, "FriendlyName": d["FriendlyName"], "Size": size, "BusType": bus,
            "Serial": d["Serial"], "DiskId": layout["DiskId"], "Partitions": len(layout["Parts"]),
            "Bus": bus, "IsExternal": bus == "USB" or d["Removable"],
            "PartitionStyle": layout["Style"], "IsBoot": False, "IsSystem": False, "IsOffline": False,
            "Unallocated": layout["Style"] == "RAW" or size - used > 1 << 30,
            "HealthStatus": "Unknown", "Volumes": v,
            "HasWindows": bool(signs), "WindowsWhy": signs,
            "IsVentoy": is_ventoy(layout["Parts"], v)})
    return rows
