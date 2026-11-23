#!/usr/bin/env python3
"""Windows Disk Tool - numbered menu around diskpart / PowerShell / chkdsk / robocopy.

Run (as Administrator):  python disktool.py
Add a feature: drop a new file into actions\\ (copy actions\\_template.py).
"""
import importlib
import os
import pkgutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import ui          # noqa: E402
from core import system      # noqa: E402

VERSION = "1.0"

# Friendly names for the right-click context menu (env var WDT_GOTO)
GOTO = {"fastcopy": "a55_fastcopy", "format": "a20_format_disk"}


def load_actions():
    import actions
    found = []
    for m in pkgutil.iter_modules(actions.__path__):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module("actions." + m.name)
        except Exception as e:
            ui.warn("Skipped actions/%s.py: %s" % (m.name, e))
            continue
        if hasattr(mod, "run_action") and hasattr(mod, "TITLE"):
            found.append(mod)
    return sorted(found, key=lambda mod: getattr(mod, "ORDER", 999))


def run_goto(name):
    try:
        mod = importlib.import_module("actions." + GOTO[name])
        mod.run_action()
    except Exception as e:
        ui.err("Could not open '%s': %s" % (name, e))
    ui.pause()


def main():
    if sys.platform != "win32":
        ui.err("This tool is for Windows. (Use the Mac tool on macOS.)")
        sys.exit(1)
    if not system.is_admin():
        ui.warn("Administrator rights are needed for disk operations.")
        if ui.yes_no("Re-launch as Administrator now?", True):
            if system.relaunch_as_admin():
                return
        ui.info("Continuing without admin - some actions will fail.")

    goto = os.environ.get("WDT_GOTO")
    if goto in GOTO:
        run_goto(goto)
        return

    acts = load_actions()
    while True:
        ui.header("Windows Disk Tool v%s" % VERSION)
        print(ui.c("        صدقة جارية على روح زينب عبد العليم مصطفى رحمها الله", ui.DIM))
        idx = ui.choose("Main menu", [a.TITLE for a in acts], back_label="Exit")
        if idx is None:
            print("Bye.")
            return
        try:
            acts[idx].run_action()
        except KeyboardInterrupt:
            print()
            ui.warn("Cancelled (Ctrl+C).")
        except Exception as e:
            ui.err("Unexpected error: %s" % e)
        ui.pause()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")
