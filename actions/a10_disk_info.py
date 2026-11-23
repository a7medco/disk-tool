"""Show connected disks with details and SMART health."""
from core import disks, ui
from core.system import ps_json, powershell

ORDER = 10
TITLE = "Show disks & details (SMART health)"


def run_action():
    ui.header(TITLE)
    rows = disks.list_disks()
    if not rows:
        ui.err("No disks returned. Run the tool as Administrator.")
        return
    print()
    for d in rows:
        line = disks.describe(d)
        h = d.get("HealthStatus", "Unknown")
        if h == "Healthy":
            print("  " + line + ui.c("   [Healthy]", ui.GREEN))
        elif h in ("Warning", "Unhealthy"):
            print("  " + line + ui.c("   [%s - back up & replace]" % h, ui.RED))
        else:
            print("  " + line + "   [%s]" % h)

    if not ui.yes_no("\nShow SMART reliability details for one disk?", False):
        return
    d = disks.pick_disk("Which disk", external_only=False, allow_boot=True)
    if not d:
        return
    num = d.get("Number")
    powershell("Get-PhysicalDisk -DeviceNumber %s | Get-StorageReliabilityCounter | "
               "Format-List Temperature,Wear,ReadErrorsTotal,WriteErrorsTotal,"
               "PowerOnHours,StartStopCycleCount" % num)
    ui.info("Blank values mean the USB bridge doesn't pass SMART through (common).")
