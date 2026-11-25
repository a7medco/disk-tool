#!/usr/bin/env python3
"""Windows Disk Tool - premium desktop UI (web front-end in a native window).

Uses pywebview (one-time: pip install pywebview). The window itself is rendered
by Edge WebView2, which ships with Windows 10/11, so nothing else is needed.

Run (as Administrator):  python app.py
A no-dependency fallback is gui.py (plain Tkinter).
"""
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import capture, deploy, guard, health, watch, paths, settings, startup, sysinfo, system, ventoy, winops, yumi   # noqa: E402

VERSION = "2.10.0"


class Api:
    """Exposed to the web UI as window.pywebview.api.*"""
    def __init__(self, goto=""):
        self._window = None
        self._goto = goto
        self._stop = threading.Event()
        # start PowerShell + read the disks right away, while the window is still opening
        def _prefetch():
            system.warm_up()
            winops.list_disks()
        threading.Thread(target=_prefetch, daemon=True).start()

    # output streaming -> the page's console
    def _emit(self, line):
        if self._window:
            self._window.evaluate_js("window.onLog(%s)" % json.dumps(line))

    def _done(self, code):
        if self._window:
            self._window.evaluate_js("window.onDone(%s)" % json.dumps(code))

    def _bg(self, fn):
        self._stop.clear()

        def work():
            try:
                code = fn()
            except guard.Blocked as e:
                self._emit("[X] Blocked for safety: %s" % e)
                code = -1
            except Exception as e:
                self._emit("[X] error: %s" % e)
                code = -1
            self._done(code)
        threading.Thread(target=work, daemon=True).start()

    def _guarded(self, kind, target, fn):
        """Destructive job: needs a backend ticket from arm() (see core/guard.py)."""
        def job():
            guard.take(kind, target)
            return fn()
        self._bg(job)
        return True

    # ---- safety: the UI calls this right after the user confirms ----
    def arm(self, kind, target, typed):
        return guard.arm(kind, target, typed)

    # ---- called from JS ----
    def list_disks(self, fresh=False):
        rows = winops.list_disks(0 if fresh else 600)
        return {"rows": rows, "took": winops.disks_took()}

    def format_disk(self, number, fs, scheme, label):
        return self._guarded("disk", number, lambda: winops.format_disk(number, fs, scheme, label, self._emit))

    def chkdsk(self, letter, level):
        self._bg(lambda: winops.chkdsk(guard.letter(letter), guard.choice(level, ("scan", "fix", "full"), "level"),
                                       self._emit))
        return True

    def robocopy(self, src, dst):
        self._bg(lambda: winops.robocopy(src, dst, self._emit))
        return True

    def choose_folder(self):
        import webview
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return res[0] if res else ""

    def choose_file(self, kind="iso"):
        import webview
        types = {"iso": ("ISO (*.iso)", "All files (*.*)"),
                 "img": ("Disk images (*.img;*.iso;*.bin;*.raw)", "All files (*.*)"),
                 "exe": ("Ventoy2Disk (Ventoy2Disk.exe)", "Programs (*.exe)"),
                 "yumi": ("YUMI exFAT (YUMI*.exe)", "Programs (*.exe)"),
                 "win": ("Windows image (*.iso;*.wim;*.esd)", "All files (*.*)")}[kind]
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=types)
        return res[0] if res else ""

    def choose_files(self):
        import webview
        res = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=("Boot images (*.iso;*.wim;*.img;*.vhd;*.vhdx;*.efi)", "All files (*.*)"))
        return list(res) if res else []

    def start_info(self):
        return {"goto": self._goto, "version": VERSION, "theme": settings.get("theme", "sky"),
                "ui": settings.get("ui", {})}

    def set_ui(self, ui):
        """Only the Output console open/closed is stored (sidebar groups are not remembered)."""
        if isinstance(ui, dict):
            settings.put("ui", {"console": bool(ui.get("console", True))})
        return True

    def set_theme(self, theme):
        settings.put("theme", theme if theme in ("sky", "light", "nvidia") else "sky")
        return True

    def stop(self):
        self._stop.set()
        return True

    # read-only, returns data straight to the UI
    def list_local_users(self):
        return winops.list_local_users()

    # background (streamed) operations
    def reset_password(self, user, pw):
        return self._guarded("action", "password",
                             lambda: winops.reset_password(_user(user), _pw(pw), self._emit))

    def create_admin(self, user, pw):
        return self._guarded("action", "create_admin",
                             lambda: winops.create_admin(_user(user), _pw(pw), self._emit))

    def letter(self, number, letter, action):
        self._bg(lambda: winops.assign_remove_letter(number, letter, action, self._emit))  # checked in winops
        return True

    def bootable_usb(self, iso, number, letter):
        return self._guarded("disk", number, lambda: winops.bootable_windows_usb(
            guard.existing_file(iso, (".iso",)), number, letter, self._emit))


    # ---- v2: drivers, raw image, partitions, RAM, menu ----
    def export_drivers(self, folder):
        self._bg(lambda: winops.export_drivers(folder, self._emit)); return True

    def import_drivers(self, folder):
        return self._guarded("action", "import_drivers", lambda: winops.import_drivers(folder, self._emit))

    def write_image(self, img, number):
        return self._guarded("disk", number, lambda: winops.write_image(
            guard.existing_file(img), number, self._emit, self._stop))

    def save_image(self, number, size, path):
        self._bg(lambda: winops.save_image(guard.find_disk(number)["Number"], size, path, self._emit, self._stop))
        return True

    def choose_save(self, name):
        import webview
        res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=name,
                                              file_types=("Disk image (*.img)",))
        if not res:
            return ""
        return res if isinstance(res, str) else res[0]

    def format_volume(self, letter, fs, label):
        return self._guarded("volume", letter, lambda: winops.format_volume(letter, fs, label, self._emit))

    def eject(self, letter):
        self._bg(lambda: winops.eject(guard.check_volume(letter)[0], self._emit)); return True

    def ram_test(self):
        self._bg(lambda: winops.ram_test(self._emit)); return True

    def memtest_results(self):
        return winops.memtest_results()

    # ---- health & repair ----
    def smart_details(self):
        return health.smart_details()

    def surface_test(self, number, size):
        self._bg(lambda: health.surface_test(guard.find_disk(number)["Number"], size, self._emit, self._stop))
        return True

    def system_repair(self, kind):
        self._bg(lambda: health.system_repair(guard.choice(kind, ("sfc", "dism"), "repair"), self._emit))
        return True

    # ---- multi-ISO (Ventoy) ----
    def ventoy_info(self):
        return {"exe": ventoy.find_exe()}

    def ventoy_locate(self):
        p = self.choose_file("exe")
        return ventoy.set_exe(p) and p or ""

    def ventoy_install(self, number, mode, gpt, sb):
        if str(mode).upper() == "I":            # fresh install erases the USB
            return self._guarded("disk", number, lambda: ventoy.install(number, "I", gpt, sb, self._emit))
        self._bg(lambda: ventoy.install(number, "U", gpt, sb, self._emit)); return True

    def ventoy_add(self, number, files):
        self._bg(lambda: ventoy.add_isos(guard.find_disk(number)["Number"],
                                         [guard.existing_file(f) for f in (files or [])], self._emit))
        return True

    def ventoy_list(self, number):
        return ventoy.list_isos(number)

    # ---- multi-ISO (YUMI exFAT) - separate from Ventoy ----
    def yumi_info(self):
        return yumi.info()

    def yumi_locate(self):
        p = self.choose_file("yumi")
        return yumi.set_exe(p) and p or ""

    def yumi_launch(self):
        return yumi.launch(self._emit)

    def yumi_page(self):
        return yumi.open_page()

    # ---- OOBE & Windows To Go ----
    def sysprep(self, generalize, after):
        after = guard.choice(after, ("shutdown", "reboot"), "after")
        return self._guarded("action", "sysprep", lambda: deploy.sysprep_oobe(bool(generalize), after, self._emit))

    def wtg_editions(self, src):
        return deploy.list_editions(src)

    def wtg_create(self, src, index, number):
        return self._guarded("disk", number, lambda: deploy.windows_to_go(
            guard.existing_file(src, (".iso", ".wim", ".esd")), int(index), number, self._emit, self._stop))

    def install_to_disk(self, src, index, number, scheme, drivers, compact, recovery=True):
        return self._guarded("disk", number, lambda: deploy.install_to_disk(
            guard.existing_file(src, (".iso", ".wim", ".esd")), int(index), number, scheme, drivers,
            bool(compact), self._emit, self._stop, bool(recovery)))

    # ---- capture image ----
    def capture_targets(self):
        return capture.targets()

    def capture_info(self):
        return {"wimlib": __import__("os").path.isfile(capture.WIMLIB), "bitlocker": capture._bitlocker_on()}

    def capture_backup(self, letter):
        self._bg(lambda: capture.backup_image(guard.letter(letter), self._emit, self._stop)); return True

    def capture_deploy(self, letter):
        return self._guarded("action", "capture_deploy",
                             lambda: capture.deploy_image(guard.letter(letter), self._emit, self._stop))

    def bitlocker_off(self):
        return self._guarded("action", "bitlocker_off", lambda: capture.bitlocker_off(self._emit))

    # ---- battery & license ----
    def battery(self):
        return sysinfo.battery()

    def battery_report(self):
        return sysinfo.battery_report_html()

    def license_info(self):
        return sysinfo.license_info()

    # ---- startup apps ----
    def startup_list(self):
        return startup.list_items()

    def startup_set(self, item_id, enable):
        return startup.set_enabled(item_id, enable, self._emit) == 0


def _user(u):
    """Local account name: letters, digits, space . _ - (max 20, Windows limit)."""
    import re
    u = str(u or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9 ._\-]{1,20}", u):
        raise guard.Blocked("invalid user name (letters, digits, space . _ - ; max 20).")
    return u


def _pw(p):
    p = str(p or "")
    if not p or p == "*" or len(p) > 127 or any(c in p for c in "\r\n\x00"):
        raise guard.Blocked("invalid password (empty, '*', too long or has line breaks).")
    return p


def main():
    if sys.platform != "win32":
        print("This app is for Windows.")
        return
    from core import pe
    if pe.is_pe():                       # WinPE: no UAC, no PowerShell, no WebView2 -> simple window
        import gui
        gui.main()
        return
    if not system.is_admin() and system.relaunch_as_admin():
        return
    from core import webview2
    if not webview2.ensure():
        import gui                       # simple Tkinter window, no WebView2 needed
        gui.main()
        return
    try:
        import webview
    except ImportError:
        print("Please install the UI library once:\n\n    pip install pywebview\n")
        print("Or run the no-dependency version:  python gui.py")
        return
    goto = ""
    if "--goto" in sys.argv:
        i = sys.argv.index("--goto")
        goto = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    api = Api(goto)
    w, h = 1080, 720
    try:                                    # open at ~80% of the screen, never bigger
        sc = webview.screens() if callable(webview.screens) else webview.screens
        if sc:
            w = max(860, min(1180, int(sc[0].width * 0.80)))
            h = max(560, min(780, int(sc[0].height * 0.82)))
    except Exception:
        pass
    window = webview.create_window(
        "Disk Tool %s  -  Abuzaid   |   صدقة جارية على روح زينب عبد العليم مصطفى رحمها الله" % VERSION,
        os.path.join(paths.RES, "web", "index.html"),
        js_api=api, width=w, height=h, min_size=(820, 540))
    api._window = window

    def _devices_changed():
        winops.list_disks(0)                  # refresh the cache first, then tell the page
        try:
            window.evaluate_js("window.onDevices && window.onDevices()")
        except Exception:
            pass
    watch.start(_devices_changed)
    webview.start()


if __name__ == "__main__":
    main()
