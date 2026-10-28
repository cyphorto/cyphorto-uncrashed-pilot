"""Connect the virtual Xbox controller and hold it in a safe state for setup.

    python tools/hold_controller.py                 # throttle 0, sticks centred, button A blinking
    python tools/hold_controller.py --blink 0       # hold button A down instead of blinking
    python tools/hold_controller.py --button B --minutes 5

Use it while Uncrashed is on Options > Controls:
  - pick "XboxController" as the RC-Controller and check the live stick display:
    throttle should sit at the BOTTOM, the other three centred.
  - bind a mode switch (e.g. Angle) to the blinking button.
Hold F12 or press Ctrl+C to quit. The controller disappears when the script exits.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import config as C
from core.gamepad import BUTTONS, Gamepad

VK_F12 = 0x7B


def f12_down():
    if sys.platform != "win32":
        return False
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_F12) & 0x8000)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--button", default="A", choices=sorted(BUTTONS))
    p.add_argument("--blink", type=float, default=1.0, help="seconds per on/off half-cycle; 0 = hold down")
    p.add_argument("--minutes", type=float, default=10.0)
    args = p.parse_args()

    pad = Gamepad(C.load()["controls"])
    btn = getattr(pad.vg.XUSB_BUTTON, BUTTONS[args.button])
    print(f"Virtual controller connected. Throttle 0, sticks centred, button {args.button} "
          f"{'held down' if args.blink <= 0 else f'blinking every {args.blink:g}s'}.")
    print("Hold F12 or press Ctrl+C to quit.", flush=True)
    end = time.monotonic() + args.minutes * 60
    on = None
    try:
        while time.monotonic() < end and not f12_down():
            want = True if args.blink <= 0 else int(time.monotonic() / args.blink) % 2 == 0
            if want != on:
                (pad.pad.press_button if want else pad.pad.release_button)(button=btn)
                on = want
            pad.send(0.0, 0.0, 0.0, 0.0)  # also pushes the button state
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        pad.pad.release_button(button=btn)
        pad.min_throttle()
    print("Stopped.")


if __name__ == "__main__":
    main()
