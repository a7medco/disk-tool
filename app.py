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

from core import capture, deploy, health, watch, paths, settings, startup, sysinfo, system, ventoy, winops   # noqa: E402

VERSION = "2.8"


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
            except Exception as e:
                self._emit("[X] error: %s" % e)
                code = -1
            self._done(code)
        threading.Thread(target=work, daemon=True).start()

    # ---- called from JS ----
    def list_disks(self, fresh=False):
        rows = winops.list_disks(0 if fresh else 15)
        return {"rows": rows, "took": winops.disks_took()}

    def format_disk(self, number, fs, scheme, label):
        self._bg(lambda: winops.format_disk(number, fs, scheme, label, self._emit))
        return True

    def chkdsk(self, letter, level):
        self._bg(lambda: winops.chkdsk(letter, level, self._emit))
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
        return {"goto": self._goto, "version": VERSION, "theme": settings.get("theme", "sky")}

    def set_theme(self, theme):
        settings.put("theme", theme if theme in ("sky", "light", "nvidia") else "sky")
        return True

    def stop(self):
        self._stop.set()
        return True

    # read-only, returns data straight to the UI
    def device_locks(self):
        return winops.device_locks()

    def list_local_users(self):
        return winops.list_local_users()

    # background (streamed) operations
    def reset_password(self, user, pw):
        self._bg(lambda: winops.reset_password(user, pw, self._emit))
        return True

    def create_admin(self, user, pw):
        self._bg(lambda: winops.create_admin(user, pw, self._emit))
        return True

    def letter(self, number, letter, action):
        self._bg(lambda: winops.assign_remove_letter(number, letter, action, self._emit))
        return True

    def vc_create(self, path, size, fs, pw):
        self._bg(lambda: winops.veracrypt_create(path, size, fs, pw, self._emit))
        return True

    def vc_mount(self, path, letter, pw):
        self._bg(lambda: winops.veracrypt_mount(path, letter, pw, self._emit))
        return True

    def vc_dismount(self, letter):
        self._bg(lambda: winops.veracrypt_dismount(letter, self._emit))
        return True

    def bootable_usb(self, iso, number, letter):
        self._bg(lambda: winops.bootable_windows_usb(iso, number, letter, self._emit))
        return True


    # ---- v2: drivers, raw image, partitions, RAM, menu ----
    def export_drivers(self, folder):
        self._bg(lambda: winops.export_drivers(folder, self._emit)); return True

    def import_drivers(self, folder):
        self._bg(lambda: winops.import_drivers(folder, self._emit)); return True

    def write_image(self, img, number):
        self._bg(lambda: winops.write_image(img, number, self._emit, self._stop)); return True

    def save_image(self, number, size, path):
        self._bg(lambda: winops.save_image(number, size, path, self._emit, self._stop)); return True

    def choose_save(self, name):
        import webview
        res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=name,
                                              file_types=("Disk image (*.img)",))
        if not res:
            return ""
        return res if isinstance(res, str) else res[0]

    def format_volume(self, letter, fs, label):
        self._bg(lambda: winops.format_volume(letter, fs, label, self._emit)); return True

    def eject(self, letter):
        self._bg(lambda: winops.eject(letter, self._emit)); return True

    def ram_test(self):
        self._bg(lambda: winops.ram_test(self._emit)); return True

    def memtest_results(self):
        return winops.memtest_results()

    def menu_install(self):
        self._bg(lambda: winops.install_context_menu(self._emit))
        return True

    def menu_remove(self):
        self._bg(lambda: winops.remove_context_menu(self._emit)); return True

    # ---- health & repair ----
    def smart_details(self):
        return health.smart_details()

    def surface_test(self, number, size):
        self._bg(lambda: health.surface_test(number, size, self._emit, self._stop)); return True

    def system_repair(self, kind):
        self._bg(lambda: health.system_repair(kind, self._emit)); return True

    # ---- multi-ISO (Ventoy) ----
    def ventoy_info(self):
        return {"exe": ventoy.find_exe()}

    def ventoy_locate(self):
        p = self.choose_file("exe")
        return ventoy.set_exe(p) and p or ""

    def ventoy_install(self, number, mode, gpt, sb):
        self._bg(lambda: ventoy.install(number, mode, gpt, sb, self._emit)); return True

    def ventoy_add(self, number, files):
        self._bg(lambda: ventoy.add_isos(number, files, self._emit)); return True

    def ventoy_list(self, number):
        return ventoy.list_isos(number)

    # ---- OOBE & Windows To Go ----
    def sysprep(self, generalize, after):
        self._bg(lambda: deploy.sysprep_oobe(bool(generalize), after, self._emit)); return True

    def wtg_editions(self, src):
        return deploy.list_editions(src)

    def wtg_create(self, src, index, number):
        self._bg(lambda: deploy.windows_to_go(src, index, number, self._emit, self._stop)); return True

    def install_to_disk(self, src, index, number, scheme, drivers, compact, recovery=True):
        self._bg(lambda: deploy.install_to_disk(src, index, number, scheme, drivers, bool(compact),
                                                self._emit, self._stop, bool(recovery))); return True

    # ---- capture image ----
    def capture_targets(self):
        return capture.targets()

    def capture_info(self):
        return {"wimlib": __import__("os").path.isfile(capture.WIMLIB), "bitlocker": capture._bitlocker_on()}

    def capture_backup(self, letter):
        self._bg(lambda: capture.backup_image(letter, self._emit, self._stop)); return True

    def capture_deploy(self, letter):
        self._bg(lambda: capture.deploy_image(letter, self._emit, self._stop)); return True

    def bitlocker_off(self):
        self._bg(lambda: capture.bitlocker_off(self._emit)); return True

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


def main():
    if sys.platform != "win32":
        print("This app is for Windows.")
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
