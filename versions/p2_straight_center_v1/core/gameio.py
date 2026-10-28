"""The real game behind the same interface as the simulator:
now(), wait_until(t), read(), send(throttle, yaw, pitch, roll), min_throttle(), kill_pressed()."""
import sys
import time

from .capture import ScreenGrabber
from .config import resolve
from .gamepad import Gamepad
from .osd_reader import OSDReader

VK = {f"F{i}": 0x6F + i for i in range(1, 13)}
VK.update({"ESC": 0x1B, "END": 0x23, "PAUSE": 0x13})


class KillKey:
    def __init__(self, name):
        self.code = VK.get((name or "").upper())
        self.user32 = None
        if sys.platform == "win32" and self.code:
            import ctypes
            self.user32 = ctypes.windll.user32

    def pressed(self):
        return bool(self.user32 and (self.user32.GetAsyncKeyState(self.code) & 0x8000))


class GameIO:
    is_sim = False

    def __init__(self, cfg, need_osd=True):
        self.pad = Gamepad(cfg["controls"])
        self.kill = KillKey(cfg["controls"].get("kill_key", "F12"))
        self.grabber = None
        if need_osd:
            self.grabber = ScreenGrabber(cfg["osd"]["region"], cfg["capture"]["monitor"])
            self.osd = OSDReader(cfg["osd"], resolve(cfg["osd"]["templates_dir"]))
            if not self.osd.ready:
                raise SystemExit("OSD templates missing for digits " + ",".join(self.osd.missing())
                                 + ". Run: python tools/calibrate_osd.py")

    def now(self):
        return time.perf_counter()

    def wait_until(self, t):
        while True:
            left = t - time.perf_counter()
            if left <= 0:
                return
            time.sleep(left - 0.002 if left > 0.003 else 0)

    def read(self):
        t, img = self.grabber.grab()
        return t, self.osd.read_height(img), {}

    def send(self, throttle, yaw=0.0, pitch=0.0, roll=0.0):
        self.pad.send(throttle, yaw, pitch, roll)

    def min_throttle(self):
        self.pad.min_throttle()

    def arm(self):
        self.pad.arm()

    def kill_pressed(self):
        return self.kill.pressed()

    def close(self):
        self.pad.min_throttle()
