"""Screen capture. Every frame is timestamped at GRAB time (time.perf_counter)."""
import sys
import time

import numpy as np

_dpi_done = False


def make_dpi_aware():
    """Without this, Windows display scaling (125%, 150%...) shifts screen coordinates."""
    global _dpi_done
    if _dpi_done or sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _dpi_done = True


class MonitorCapture:
    """Whole-monitor grab with the same grab() interface as core.window.WindowCapture.
    Fallback only: anything on top of the game shows up in these frames."""

    def __init__(self, monitor=1):
        make_dpi_aware()
        import mss
        self.sct = mss.mss()
        self.mon = self.sct.monitors[int(monitor)]
        self.count = 0

    def grab(self, newer_than=None, timeout=1.0):
        t = time.perf_counter()
        img = np.asarray(self.sct.grab(self.mon))[:, :, :3]
        self.count += 1
        return t, img, self.count

    def close(self):
        self.sct.close()


class ScreenGrabber:
    def __init__(self, region=None, monitor=1):
        make_dpi_aware()
        import mss
        self.sct = mss.mss()
        self.monitor_index = monitor
        if region and region.get("width", 0) > 0 and region.get("height", 0) > 0:
            self.box = {k: int(region[k]) for k in ("left", "top", "width", "height")}
        else:
            self.box = None

    def full_monitor(self):
        mon = self.sct.monitors[self.monitor_index]
        img = np.asarray(self.sct.grab(mon))[:, :, :3]
        return img, mon

    def grab(self):
        """Returns (t_grab, BGR image of the region)."""
        if self.box is None:
            raise RuntimeError("osd.region is not set. Run: python tools/pick_region.py")
        t = time.perf_counter()
        img = np.asarray(self.sct.grab(self.box))[:, :, :3]
        return t, img
