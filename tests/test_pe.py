"""WinPE tests that run on any OS: disk-layout parsing (3 Disk ID cases), DISM/wimlib
edition parsing, and the WinPE guard rules (Windows disk / Ventoy / tool disk refused)."""
import os
import struct
import sys
import types
import uuid

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
os.environ["DISKTOOL_FORCE_PE"] = "1"
os.environ["SystemDrive"] = "X:"

from core import pe, pe_disks as P   # noqa: E402

assert pe.is_pe(), "forced WinPE"


def part(style, start, length, number, ptype, name=""):
    b = bytearray(P.PART_SIZE)
    struct.pack_into("<I", b, 0, style)
    struct.pack_into("<qqI", b, 8, start, length, number)
    if style == 0:
        b[32] = ptype
    else:
        b[32:48] = uuid.UUID(ptype).bytes_le
        nm = name.encode("utf-16-le")
        b[72:72 + len(nm)] = nm
    return bytes(b)


def layout(style, union, parts):
    head = struct.pack("<II", style, len(parts)) + union.ljust(40, b"\0")
    return head + b"".join(parts)


# --- MBR signature (8 hex) ---
L = P.parse_layout(layout(0, struct.pack("<II", 0x1A2B3C4D, 0), [
    part(0, 1 << 20, 100 << 20, 1, 0x07), part(0, 0, 0, 0, 0), part(0, 0, 0, 0, 0), part(0, 0, 0, 0, 0)]))
assert L["Style"] == "MBR" and L["DiskId"] == "1A2B3C4D" and len(L["Parts"]) == 1, L
# --- MBR empty signature 00000000 -> no id ---
L = P.parse_layout(layout(0, struct.pack("<II", 0, 0), [part(0, 0, 0, 0, 0)] * 4))
assert L["DiskId"] == "" and L["Parts"] == [], L
# --- GPT GUID ---
g = "0F1E2D3C-4B5A-6978-8796-A5B4C3D2E1F0"
L = P.parse_layout(layout(1, uuid.UUID(g).bytes_le, [
    part(1, 1 << 20, 260 << 20, 1, P.GPT_ESP, "EFI system partition"),
    part(1, 300 << 20, 16 << 20, 2, P.GPT_MSR),
    part(1, 400 << 20, 50 << 30, 3, "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7", "Basic data partition"),
    part(1, 60 << 30, 1 << 30, 4, P.GPT_RECOVERY)]))
assert L["Style"] == "GPT" and L["DiskId"] == g, L
assert P.windows_signs(L["Parts"], "GPT") == ["EFI system partition", "Windows recovery partition"]
# --- RAW (uninitialized) ---
L = P.parse_layout(layout(2, b"", []))
assert L["Style"] == "RAW" and L["DiskId"] == "" and L["Parts"] == []
# --- MBR recovery 0x27 ---
assert P.windows_signs([{"Type": 0x27}], "MBR") == ["Windows recovery partition"]
assert P.windows_signs([{"Type": 0x07}], "MBR") == []
# --- Ventoy ---
assert P.is_ventoy([{"Name": "VTOYEFI"}], [])
assert P.is_ventoy([], [{"Label": "Ventoy"}])
assert not P.is_ventoy([{"Name": "Basic data partition"}], [{"Label": "DATA"}])

# --- storage descriptor ---
d = bytearray(256)
struct.pack_into("<IIBBBBIIIII", d, 0, 1, 256, 0, 0, 1, 0, 64, 80, 0, 120, 7)
d[64:69] = b"WD\0\0\0"; d[80:96] = b"My Passport 25E2"; d[120:130] = b"WX12345678"
r = P.parse_descriptor(bytes(d))
assert r == {"FriendlyName": "WD My Passport 25E2", "Serial": "WX12345678", "BusType": "USB",
             "Removable": True}, r

# --- edition parsing (DISM English + wimlib) ---
from core import deploy   # noqa: E402
dism = """Deployment Image Servicing and Management tool
Version: 10.0.19041.3636

Details for image : D:\\sources\\install.wim

Index : 1
Name : Windows 10 IoT Enterprise LTSC
Description : Windows 10 IoT Enterprise LTSC
Size : 14,893,245,123 bytes

Index : 2
Name : Windows 10 Enterprise LTSC
Description : Windows 10 Enterprise LTSC
Size : 14,800,000,000 bytes

The operation completed successfully.
"""
e = deploy.parse_image_info(dism)
assert e == [{"Index": 1, "Name": "Windows 10 IoT Enterprise LTSC", "Size": 14893245123},
             {"Index": 2, "Name": "Windows 10 Enterprise LTSC", "Size": 14800000000}], e
wl = """WIM Information:
----------------
Path:           install.esd
Image Count:    1

Available Images:
-----------------
Index:                  1
Name:                   Windows 11 Pro
Description:            Windows 11 Pro
Total Bytes:            20123456789
"""
assert deploy.parse_image_info(wl) == [{"Index": 1, "Name": "Windows 11 Pro", "Size": 20123456789}]

# --- WinPE guard rules ---
fake = types.ModuleType("core.winops")
DISKS = [
    {"Number": 0, "FriendlyName": "NVMe SSD", "Size": 500, "Serial": "S1", "DiskId": "AAAA", "Partitions": 4,
     "IsSystem": False, "IsBoot": False, "HasWindows": True, "WindowsWhy": ["Windows folder on C:"],
     "IsVentoy": False, "Volumes": [{"Letter": "C"}]},
    {"Number": 1, "FriendlyName": "SanDisk", "Size": 64, "Serial": "", "DiskId": "1A2B3C4D", "Partitions": 2,
     "IsSystem": False, "IsBoot": False, "HasWindows": False, "IsVentoy": True, "Volumes": [{"Letter": "E"}]},
    {"Number": 2, "FriendlyName": "Kingston", "Size": 32, "Serial": "", "DiskId": "", "Partitions": 1,
     "IsSystem": False, "IsBoot": False, "HasWindows": False, "IsVentoy": False, "Volumes": [{"Letter": "F"}]},
    {"Number": 3, "FriendlyName": "Blank HDD", "Size": 1000, "Serial": "", "DiskId": "", "Partitions": 0,
     "IsSystem": False, "IsBoot": False, "HasWindows": False, "IsVentoy": False, "Volumes": []},
    {"Number": 4, "FriendlyName": "Data HDD", "Size": 2000, "Serial": "", "DiskId": "11223344", "Partitions": 1,
     "IsSystem": False, "IsBoot": False, "HasWindows": False, "IsVentoy": False, "Volumes": [{"Letter": "G"}]},
]
fake.list_disks = lambda max_age=0: DISKS
sys.modules["core.winops"] = fake
from core import guard   # noqa: E402
guard._app_letters = lambda: {"F"}          # tool runs from F: (disk 2)


def refused(kind, t, typed):
    return not guard.arm(kind, t, typed)["ok"]


assert refused("disk", 0, "0"), "Windows disk must be refused in WinPE"
assert "Windows" in guard.arm("disk", 0, "0")["msg"]
assert refused("disk", 1, "1"), "Ventoy USB must be refused"
assert refused("disk", 2, "2"), "tool disk must be refused"
assert refused("volume", "C", "C") and refused("volume", "E", "E") and refused("volume", "F", "F")
assert refused("volume", "X", "X"), "X: (WinPE RAM drive)"
assert guard.arm("disk", 3, "3")["ok"]; guard.take("disk", 3)          # blank disk with no id
assert guard.arm("disk", 4, "4")["ok"]                                 # data disk
DISKS[4]["DiskId"] = "99999999"                                         # different disk now in slot 4
try:
    guard.take("disk", 4); raise SystemExit("fingerprint must catch a swapped disk")
except guard.Blocked:
    pass
DISKS[4]["DiskId"] = "11223344"
assert guard.arm("volume", "G", "G")["ok"]; guard.take("volume", "G")
DISKS[4]["HasWindows"] = True                                           # Windows appears -> refused
assert refused("volume", "G", "G") and refused("disk", 4, "4")
print("ALL WINPE TESTS PASSED")
