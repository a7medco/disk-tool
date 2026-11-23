"""Notice USB drives being plugged in / removed - without PowerShell (fast, every 1.5 s)."""
import ctypes
import sys
import threading
import time


def _signature():
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = ctypes.c_void_p
    present = []
    for n in range(24):
        h = k32.CreateFileW("\\\\.\\PhysicalDrive%d" % n, 0, 3, None, 3, 0, None)  # no access, share R/W
        if h not in (None, ctypes.c_void_p(-1).value):
            present.append(n)
            k32.CloseHandle(ctypes.c_void_p(h))
    return (k32.GetLogicalDrives(), tuple(present))


def start(on_change, every=1.5):
    if sys.platform != "win32":
        return

    def loop():
        last = _signature()
        while True:
            time.sleep(every)
            try:
                cur = _signature()
            except Exception:
                continue
            if cur != last:
                time.sleep(1.2)                 # let Windows finish mounting
                last = _signature()
                try:
                    on_change()
                except Exception:
                    pass
    threading.Thread(target=loop, daemon=True).start()
