"""CI only (real Windows, DISKTOOL_FORCE_PE=1): the WinPE 'Install Windows' path end to end
on an attached virtual disk - guard ticket, diskpart, DISM editions + apply, bcdboot."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import deploy, guard, pe, pe_disks, winops   # noqa: E402

LOG = []


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    LOG.append(line)


def main():
    assert pe.is_pe(), "run with DISKTOOL_FORCE_PE=1"
    wim = os.path.abspath(sys.argv[1])
    eds = deploy.list_editions(wim)
    log("EDITIONS", eds)
    assert eds and eds[0]["Index"] == 1 and eds[0]["Name"] == "Test Windows", eds

    assert deploy.list_editions(wim[:-4] + ".iso") == [], "ISO must be refused in WinPE"

    vd = [d for d in winops.list_disks(0) if d["Size"] == 4096 * 1024 * 1024 and not d["Volumes"]]
    log("VHD", vd)
    assert len(vd) == 1, "virtual disk not found"
    n = vd[0]["Number"]
    r = guard.arm("disk", n, str(n))
    assert r["ok"], r
    guard.take("disk", n)
    code = deploy.install_to_disk(wim, 1, n, "gpt", "", False, log, None, True)
    log("INSTALL CODE", code)
    assert code == 0

    after = [d for d in pe_disks.list_disks() if d["Number"] == n][0]
    log("AFTER", after["PartitionStyle"], after["Partitions"], after["WindowsWhy"])
    assert after["PartitionStyle"] == "GPT" and after["Partitions"] == 4, after
    assert after["HasWindows"], "the new Windows disk must now be protected"
    r = guard.arm("disk", n, str(n))
    log("ARM AFTER", r)
    assert not r["ok"], "WinPE must refuse to erase the disk it just installed Windows on"
    log("WINPE INSTALL TEST PASSED")


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        import traceback
        tail = LOG[-40:] + traceback.format_exc().splitlines()[-6:]
        print("::error title=WinPE install test::" + "%0A".join(x.replace("%", "%25") for x in tail))
        sys.exit(1)
