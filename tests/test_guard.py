import sys, time, types
sys.path.insert(0, sys.argv[1])
fake = types.ModuleType("core.winops")
DISKS = [
 {"Number":0,"FriendlyName":"Samsung SSD","Size":500,"Serial":"S1","IsSystem":True,"IsBoot":True,"Volumes":[{"Letter":"C"}]},
 {"Number":1,"FriendlyName":"SanDisk","Size":32,"Serial":"U1","IsSystem":False,"IsBoot":False,"Volumes":[{"Letter":"E"}]},
 {"Number":2,"FriendlyName":"Kingston","Size":64,"Serial":"K1","IsSystem":False,"IsBoot":False,"Volumes":[{"Letter":"F"}]},
]
fake.list_disks = lambda max_age=0: DISKS
sys.modules["core.winops"] = fake
import os; os.environ["SystemDrive"] = "C:"
from core import guard
guard._app_letters = lambda: {"F"}          # tool runs from F: (disk 2)
B = guard.Blocked
def blocked(f):
    try: f(); return False
    except B: return True
assert not guard.arm("disk", 0, "0")["ok"], "system disk"
assert not guard.arm("disk", 2, "2")["ok"], "app disk"
assert not guard.arm("disk", 1, "2")["ok"], "typed mismatch"
assert not guard.arm("disk", "1\nclean", "1")["ok"], "injection number"
assert guard.arm("disk", 1, "1")["ok"]
assert blocked(lambda: guard.take("disk", 2)), "wrong target"
assert blocked(lambda: guard.take("disk", 1)), "ticket consumed by failed take"
assert guard.arm("disk", 1, "1")["ok"]; guard.take("disk", 1)
assert blocked(lambda: guard.take("disk", 1)), "single use"
assert guard.arm("disk", 1, "1")["ok"]; DISKS[1]["Serial"] = "OTHER"
assert blocked(lambda: guard.take("disk", 1)), "fingerprint changed"; DISKS[1]["Serial"] = "U1"
assert guard.arm("disk", 1, "1")["ok"]; guard._ticket["exp"] = time.time() - 1
assert blocked(lambda: guard.take("disk", 1)), "expired"
assert blocked(lambda: guard.take("disk", 1)), "no ticket"
assert not guard.arm("volume", "C", "C")["ok"] and not guard.arm("volume", "F", "F")["ok"]
assert guard.arm("volume", "e:", "E")["ok"]; guard.take("volume", "E")
assert not guard.arm("action", "sysprep", "yes")["ok"] and guard.arm("action", "sysprep", "oobe")["ok"]
guard.take("action", "sysprep")
assert not guard.arm("action", "format_c", "YES")["ok"]
assert guard.label('US"B\nclean\r', "FAT32") == "USBclean" and len(guard.label("x"*50)) == 32
assert blocked(lambda: guard.choice("ntfs; rm", guard.FS_DISK, "fs")) and guard.choice("ntfs", guard.FS_DISK, "fs") == "NTFS"
print("ALL GUARD TESTS PASSED")
