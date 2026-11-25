#!/usr/bin/env python3
"""Windows Disk Tool - graphical interface (Tkinter, no extra install needed).

Run (as Administrator):  python gui.py
Labels are in English because Tk on Windows doesn't shape Arabic text well.
"""
import os
import queue
import sys
import threading

import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from core import deploy, guard, pe, system, winops   # noqa: E402

FS_TYPES = ["NTFS", "exFAT", "FAT32"]
SCHEMES = ["GPT", "MBR"]
BG, SIDE, ACCENT = "#f4f5f7", "#2c3e50", "#c0392b"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.pe = pe.is_pe()
        self.fw = pe.firmware()
        mode = "  [WinPE%s]" % (" - " + self.fw if self.fw else "") if self.pe else ""
        self.title("Windows Disk Tool%s  |  صدقة جارية على روح زينب عبد العليم مصطفى رحمها الله" % mode)
        self.geometry("920x620")
        self.minsize(820, 560)
        self.configure(bg=BG)
        self.q = queue.Queue()
        self.busy = False
        self._build()
        self.after(80, self._drain)

    # ---- layout -----------------------------------------------------------
    def _build(self):
        bar = tk.Frame(self, bg=SIDE, width=210)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)
        tk.Label(bar, text="  Disk Tool", bg=SIDE, fg="white",
                 font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x", pady=(16, 4))
        tk.Label(bar, text="  by Abuzaid", bg=SIDE, fg="#9fb0c0",
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(0, 14))

        if self.pe:
            tk.Label(bar, text="  WinPE mode" + (" (%s)" % self.fw if self.fw else ""), bg=SIDE,
                     fg="#f1c40f", font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", pady=(0, 10))
        self.items = [
            ("Disks & health", self.view_disks),
            ("Format a drive", self.view_format),
            ("Repair (chkdsk)", self.view_repair),
            ("Fast copy", self.view_fastcopy),
            ("Install Windows", self.view_install),
        ]
        if not self.pe:
            self.items += [("Bootable USB", self._soon), ("Reset password", self._soon)]
        self.btns = []
        for name, fn in self.items:
            b = tk.Button(bar, text=name, anchor="w", relief="flat", bg=SIDE,
                          fg="white", activebackground=ACCENT, activeforeground="white",
                          font=("Segoe UI", 11), padx=16, pady=9, bd=0,
                          command=lambda f=fn: self._open(f))
            b.pack(fill="x")
            self.btns.append(b)

        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(right, bg=BG)
        self.body.pack(side="top", fill="both", expand=True, padx=16, pady=14)

        logwrap = tk.Frame(right, bg=BG)
        logwrap.pack(side="bottom", fill="both", padx=16, pady=(0, 12))
        tk.Label(logwrap, text="Output", bg=BG, fg="#555",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.log = tk.Text(logwrap, height=11, bg="#1e1e1e", fg="#e6e6e6",
                           insertbackground="white", font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        self.view_disks()
        if self.pe and pe.single_exe():
            self.logline("[!] This is the single-exe build. In WinPE use DiskTool.zip (folder build) - "
                         "the single exe unpacks into X:\\ (RAM) which is very small.")

    def _clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _title(self, text):
        tk.Label(self.body, text=text, bg=BG, fg="#111",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 10))

    def _open(self, fn):
        if self.busy:
            return
        fn()

    def _soon(self):
        self._clear_body()
        self._title("Coming soon")
        tk.Label(self.body, text="This function is being added next.",
                 bg=BG, fg="#555", font=("Segoe UI", 11)).pack(anchor="w")

    # ---- logging & threading ---------------------------------------------
    def logline(self, line):
        self.q.put(line)

    def _drain(self):
        changed = False
        try:
            while True:
                line = self.q.get_nowait()
                if line is None:
                    self._set_busy(False)
                    continue
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
                changed = True
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _set_busy(self, b):
        self.busy = b
        for btn in self.btns:
            btn.configure(state="disabled" if b else "normal")

    def run_bg(self, target):
        if self.busy:
            return
        self._set_busy(True)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        def wrap():
            try:
                target()
            except guard.Blocked as e:
                self.logline("[X] Blocked for safety: %s" % e)
            except Exception as e:
                self.logline("[X] error: %s" % e)
            finally:
                self.q.put(None)   # signals done -> re-enable buttons
        threading.Thread(target=wrap, daemon=True).start()

    # ---- views ------------------------------------------------------------
    def view_disks(self):
        self._clear_body()
        self._title("Disks & health")
        top = tk.Frame(self.body, bg=BG); top.pack(fill="x")
        tk.Button(top, text="Refresh", command=self._load_disks,
                  bg=ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 10), padx=14, pady=5).pack(anchor="w")
        cols = ("num", "model", "size", "bus", "letters", "role")
        self.tree = ttk.Treeview(self.body, columns=cols, show="headings", height=9)
        for c, w in zip(cols, (40, 210, 80, 60, 70, 260)):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=10)
        self._load_disks()

    def _load_disks(self):
        def work():
            rows = winops.list_disks()
            self.after(0, lambda: self._fill_disks(rows))
        self.run_bg(work)

    def _fill_disks(self, rows):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for d in rows:
            gb = "%.1f GB" % ((d.get("Size") or 0) / 1000 ** 3)
            letters = " ".join(str(v.get("Letter")) + ":" for v in (d.get("Volumes") or []) if v.get("Letter"))
            try:
                guard.check_disk(d.get("Number"), rows)
                role = "can be erased"
            except guard.Blocked as e:
                role = "PROTECTED - " + str(e).split(" - ")[0].split(" (")[0].replace("Disk %s " % d.get("Number"), "")
            self.tree.insert("", "end", values=(
                d.get("Number"), (d.get("FriendlyName") or "?")[:34], gb,
                d.get("BusType", "?"), letters, role))

    def view_format(self):
        self._clear_body()
        self._title("Format a drive")
        tk.Label(self.body, text=("Disks with Windows, Ventoy or Disk Tool on them are hidden." if self.pe else
                                  "External USB disks only (the Windows drive is hidden)."),
                 bg=BG, fg="#777", font=("Segoe UI", 9)).pack(anchor="w")
        form = tk.Frame(self.body, bg=BG); form.pack(anchor="w", pady=12)
        self.fmt_disk = self._combo(form, 0, "Disk", [])
        self.fmt_fs = self._combo(form, 1, "Filesystem", FS_TYPES, FS_TYPES[0])
        self.fmt_scheme = self._combo(form, 2, "Scheme", SCHEMES, SCHEMES[0])
        self.fmt_label = self._entry(form, 3, "Label", "USB")
        tk.Button(self.body, text="Format", bg=ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 11, "bold"), padx=20, pady=7,
                  command=self._do_format).pack(anchor="w", pady=6)
        self._refresh_format_disks()

    def _refresh_format_disks(self):
        def work():
            rows = self._erasable(winops.list_disks(0), usb_only=not self.pe)
            opts = ["Disk %s  -  %s (%.0f GB)" % (
                d.get("Number"), d.get("FriendlyName"), (d.get("Size") or 0) / 1000 ** 3)
                for d in rows]
            self._fmt_rows = rows
            self.after(0, lambda: self.fmt_disk.configure(values=opts))
        self.run_bg(work)

    def _do_format(self):
        i = self.fmt_disk.current()
        if i < 0 or not getattr(self, "_fmt_rows", None):
            messagebox.showwarning("Format", "Pick a disk first.")
            return
        d = self._fmt_rows[i]
        num = d.get("Number")
        if self.fmt_fs.get() == "FAT32" and (d.get("Size") or 0) > 32 * 1000 ** 3:
            messagebox.showwarning("Format", "FAT32 is limited to 32 GB. Use exFAT or NTFS.")
            return
        typed = simpledialog.askstring(
            "Confirm erase",
            "ALL DATA on Disk %s (%s) will be destroyed.\n\nType the disk number %s to confirm:"
            % (num, d.get("FriendlyName"), num))
        if typed is None or typed.strip() != str(num):
            self.logline("Cancelled.")
            return
        if not self._arm("disk", num, typed):
            return
        fs, scheme, label = self.fmt_fs.get(), self.fmt_scheme.get(), self.fmt_label.get() or "USB"

        def work():
            guard.take("disk", num)
            code = winops.format_disk(num, fs, scheme, label, self.logline)
            self.logline("[OK] Done." if code == 0 else "[X] Format failed (code %s)." % code)
        self.run_bg(work)

    def view_repair(self):
        self._clear_body()
        self._title("Repair a drive (chkdsk)")
        form = tk.Frame(self.body, bg=BG); form.pack(anchor="w", pady=10)
        self.rep_drive = self._entry(form, 0, "Drive letter", "D")
        self.rep_level = tk.StringVar(value="scan")
        lv = tk.Frame(self.body, bg=BG); lv.pack(anchor="w")
        for val, txt in [("scan", "Scan (read-only, safe)"),
                         ("fix", "Fix errors (/f)"),
                         ("full", "Full + bad sectors (/r, slow)")]:
            tk.Radiobutton(lv, text=txt, variable=self.rep_level, value=val,
                           bg=BG, font=("Segoe UI", 10)).pack(anchor="w")
        tk.Button(self.body, text="Run chkdsk", bg=ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 11, "bold"), padx=18, pady=7,
                  command=self._do_repair).pack(anchor="w", pady=10)

    def _do_repair(self):
        drv = (self.rep_drive.get() or "").strip().rstrip(":")[:1].upper()
        if not ("A" <= drv <= "Z"):
            messagebox.showwarning("Repair", "Enter a drive letter, e.g. D.")
            return
        lvl = self.rep_level.get()

        def work():
            code = winops.chkdsk(drv, lvl, self.logline)
            self.logline("[OK] chkdsk finished (code %s)." % code)
        self.run_bg(work)

    def view_fastcopy(self):
        self._clear_body()
        self._title("Fast copy (robocopy - resumable)")
        form = tk.Frame(self.body, bg=BG); form.pack(anchor="w", pady=10)
        self.fc_src = self._path_row(form, 0, "From")
        self.fc_dst = self._path_row(form, 1, "To")
        tk.Button(self.body, text="Copy", bg=ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 11, "bold"), padx=20, pady=7,
                  command=self._do_copy).pack(anchor="w", pady=8)

    def _do_copy(self):
        src, dst = self.fc_src.get(), self.fc_dst.get()
        if not (os.path.isdir(src) and dst.strip()):
            messagebox.showwarning("Copy", "Pick a source folder and a destination.")
            return

        def work():
            code = winops.robocopy(src, dst, self.logline)
            self.logline("[OK] Copy finished." if code < 8 else "[X] robocopy error %s." % code)
        self.run_bg(work)

    def view_install(self):
        self._clear_body()
        self._title("Install Windows to a disk")
        tk.Label(self.body, text=("Pick sources\\install.wim or install.esd from a Windows ISO/USB. "
                                  "Only empty or data disks without Windows are listed."),
                 bg=BG, fg="#777", font=("Segoe UI", 9), wraplength=640, justify="left").pack(anchor="w")
        form = tk.Frame(self.body, bg=BG); form.pack(anchor="w", pady=10)
        self.in_src = self._path_row(form, 0, "Image", self._pick_image)
        tk.Button(form, text="Read editions", command=self._read_editions).grid(row=0, column=3, padx=4)
        self.in_ed = self._combo(form, 1, "Edition", [])
        self.in_disk = self._combo(form, 2, "Disk", [])
        default = "MBR" if self.fw == "BIOS" else "GPT"
        self.in_scheme = self._combo(form, 3, "Scheme", ["GPT", "MBR"], default)
        self.in_drv = self._path_row(form, 4, "Drivers")
        opts = tk.Frame(self.body, bg=BG); opts.pack(anchor="w")
        self.in_rec = tk.BooleanVar(value=True)
        self.in_cmp = tk.BooleanVar(value=False)
        tk.Checkbutton(opts, text="Recovery partition (WinRE)", variable=self.in_rec, bg=BG).pack(anchor="w")
        tk.Checkbutton(opts, text="Compact OS (smaller, for small disks)", variable=self.in_cmp, bg=BG).pack(anchor="w")
        tk.Label(self.body, text="Scheme: GPT = UEFI PCs, MBR = Legacy BIOS PCs%s." %
                 (" (this PC booted in %s)" % self.fw if self.fw else ""),
                 bg=BG, fg="#777", font=("Segoe UI", 9)).pack(anchor="w")
        tk.Button(self.body, text="Install", bg=ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 11, "bold"), padx=20, pady=7,
                  command=self._do_install).pack(anchor="w", pady=8)
        self._editions = []

        def work():
            rows = self._erasable(winops.list_disks(0), usb_only=False)
            self._in_rows = rows
            opts = ["Disk %s  -  %s (%.0f GB)" % (d.get("Number"), d.get("FriendlyName"),
                                                 (d.get("Size") or 0) / 1000 ** 3) for d in rows]
            self.after(0, lambda: self.in_disk.configure(values=opts))
            if not rows:
                self.logline("No disk can be used: every disk has Windows, Ventoy or Disk Tool on it.")
        self.run_bg(work)

    def _pick_image(self, entry):
        try:
            p = filedialog.askopenfilename(filetypes=[("Windows image", "*.wim *.esd"), ("All files", "*.*")])
        except tk.TclError:
            p = ""
            self.logline("[!] The file picker doesn't work here - type the full path, e.g. D:\\sources\\install.wim")
        if p:
            entry.delete(0, "end")
            entry.insert(0, os.path.normpath(p))

    def _read_editions(self):
        src = self.in_src.get().strip()
        if not src.lower().endswith((".wim", ".esd")) or not os.path.isfile(src):
            messagebox.showwarning("Install", "Pick an existing install.wim or install.esd.")
            return

        def work():
            self.logline("Reading editions from %s ..." % src)
            eds = deploy.list_editions(src)
            self._editions = eds
            opts = ["%s  -  %s" % (e.get("Index"), e.get("Name")) for e in eds]
            self.after(0, lambda: (self.in_ed.configure(values=opts), opts and self.in_ed.current(0)))
            self.logline(("%d editions found." % len(eds)) if eds else "[X] No editions found in this file.")
        self.run_bg(work)

    def _do_install(self):
        src = self.in_src.get().strip()
        e, i = self.in_ed.current(), self.in_disk.current()
        if not self._editions or e < 0:
            messagebox.showwarning("Install", "Pick the image and press 'Read editions' first.")
            return
        if i < 0 or not getattr(self, "_in_rows", None):
            messagebox.showwarning("Install", "Pick a disk.")
            return
        d = self._in_rows[i]
        num, index = d.get("Number"), self._editions[e].get("Index")
        drivers = self.in_drv.get().strip()
        typed = simpledialog.askstring(
            "Confirm erase",
            "ALL DATA on Disk %s (%s, %.0f GB) will be destroyed and Windows installed on it.\n\n"
            "Type the disk number %s to confirm:" % (num, d.get("FriendlyName"), (d.get("Size") or 0) / 1000 ** 3, num))
        if typed is None or typed.strip() != str(num):
            self.logline("Cancelled.")
            return
        if not self._arm("disk", num, typed):
            return
        scheme, rec, cmp_ = self.in_scheme.get(), self.in_rec.get(), self.in_cmp.get()

        def work():
            guard.take("disk", num)
            code = deploy.install_to_disk(guard.existing_file(src, (".wim", ".esd")), int(index), num,
                                          scheme, drivers, cmp_, self.logline, None, rec)
            self.logline("[OK] Finished." if code == 0 else "[X] Install failed (code %s)." % code)
        self.run_bg(work)

    # ---- safety helpers ----------------------------------------------------
    def _erasable(self, rows, usb_only=False):
        out = []
        for d in rows:
            if usb_only and not d.get("IsExternal") and d.get("BusType") != "USB":
                continue
            try:
                guard.check_disk(d.get("Number"), rows)
                out.append(d)
            except guard.Blocked:
                pass
        return out

    def _arm(self, kind, target, typed):
        r = guard.arm(kind, target, typed)
        if not r.get("ok"):
            self.logline("[X] Blocked for safety: %s" % r.get("msg"))
            messagebox.showerror("Blocked", r.get("msg") or "Blocked for safety.")
            return False
        return True

    # ---- small widget helpers --------------------------------------------
    def _combo(self, parent, row, label, values, default=None):
        tk.Label(parent, text=label, bg=BG, font=("Segoe UI", 10),
                 width=12, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        cb = ttk.Combobox(parent, values=values, state="readonly", width=40)
        if default:
            cb.set(default)
        cb.grid(row=row, column=1, sticky="w", pady=4)
        return cb

    def _entry(self, parent, row, label, default=""):
        tk.Label(parent, text=label, bg=BG, font=("Segoe UI", 10),
                 width=12, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        e = tk.Entry(parent, width=43)
        e.insert(0, default)
        e.grid(row=row, column=1, sticky="w", pady=4)
        return e

    def _path_row(self, parent, row, label, picker=None):
        tk.Label(parent, text=label, bg=BG, font=("Segoe UI", 10),
                 width=8, anchor="w").grid(row=row, column=0, sticky="w", pady=5)
        e = tk.Entry(parent, width=46)
        e.grid(row=row, column=1, sticky="w", pady=5)
        tk.Button(parent, text="...", width=3,
                  command=lambda: (picker or self._pick_dir)(e)).grid(row=row, column=2, padx=6)
        return e

    def _pick_dir(self, entry):
        try:
            d = filedialog.askdirectory()
        except tk.TclError:
            d = ""
            self.logline("[!] The folder picker doesn't work here - type the full path.")
        if d:
            entry.delete(0, "end")
            entry.insert(0, d)


def main():
    if sys.platform != "win32":
        print("This GUI is for Windows.")
        return
    if not pe.is_pe() and not system.is_admin() and system.relaunch_as_admin():
        return
    App().mainloop()


if __name__ == "__main__":
    main()
