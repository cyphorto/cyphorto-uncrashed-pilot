"""List every connected Xbox (XInput) controller slot and what it is sending.

    python tools/xinput_list.py

Run it while the pilot or another controller script is running. Each virtual
controller from vgamepad takes one slot (0-3). Games often read slot 0 only.
"""
import ctypes
import sys
import time
from ctypes import wintypes


class GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", GAMEPAD)]


def load():
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return getattr(ctypes.windll, name)
        except OSError:
            continue
    raise SystemExit("no XInput DLL found")


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    x = load()
    for _ in range(3):
        print(time.strftime("%H:%M:%S"))
        for slot in range(4):
            s = STATE()
            if x.XInputGetState(slot, ctypes.byref(s)) != 0:
                print(f"  slot {slot}: not connected")
                continue
            g = s.Gamepad
            print(f"  slot {slot}: CONNECTED  left x {g.sThumbLX / 32767:+.2f} y {g.sThumbLY / 32767:+.2f}  "
                  f"right x {g.sThumbRX / 32767:+.2f} y {g.sThumbRY / 32767:+.2f}  buttons 0x{g.wButtons:04x}  "
                  f"triggers {g.bLeftTrigger}/{g.bRightTrigger}  packet {s.dwPacketNumber}")
        time.sleep(1)


if __name__ == "__main__":
    main()
