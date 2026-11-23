"""TEMPLATE for a new menu item (Windows).

1. Copy to e.g. actions\\a80_my_feature.py  (name must NOT start with _)
2. Set ORDER (menu position) and TITLE (menu text)
3. Write your code in run_action()
Appears in the menu automatically next run.
"""
from core import disks, ui
from core.system import powershell

ORDER = 80
TITLE = "My new feature"


def run_action():
    ui.header(TITLE)
    d = disks.pick_disk("Select a disk")
    if not d:
        return
    powershell("Get-Disk -Number %s | Format-List" % d.get("Number"))
