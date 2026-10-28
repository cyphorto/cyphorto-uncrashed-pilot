"""Virtual Xbox controller. The control mapping lives in config.json, never in code.

Throttle is 0..1 (0 = stick fully down). Yaw / pitch / roll are -1..1 (0 = centred).
"""
import time

CHANNELS = ("throttle", "yaw", "pitch", "roll")

BUTTONS = {
    "A": "XUSB_GAMEPAD_A", "B": "XUSB_GAMEPAD_B", "X": "XUSB_GAMEPAD_X", "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER", "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "START": "XUSB_GAMEPAD_START", "BACK": "XUSB_GAMEPAD_BACK",
    "LS": "XUSB_GAMEPAD_LEFT_THUMB", "RS": "XUSB_GAMEPAD_RIGHT_THUMB",
    "UP": "XUSB_GAMEPAD_DPAD_UP", "DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "LEFT": "XUSB_GAMEPAD_DPAD_LEFT", "RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
}


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def to_stick_values(controls_cfg, throttle, yaw=0.0, pitch=0.0, roll=0.0):
    """Map channel values to {('left'|'right', 'x'|'y'): -1..1}. Pure function (testable)."""
    sticks = {("left", "x"): 0.0, ("left", "y"): 0.0, ("right", "x"): 0.0, ("right", "y"): 0.0}
    values = {
        "throttle": _clamp(throttle, 0.0, 1.0) * 2.0 - 1.0,  # 0..1 -> -1..1
        "yaw": _clamp(yaw, -1.0, 1.0),
        "pitch": _clamp(pitch, -1.0, 1.0),
        "roll": _clamp(roll, -1.0, 1.0),
    }
    used = set()
    for ch in CHANNELS:
        m = controls_cfg[ch]
        key = (m["stick"], m["axis"])
        if key in used:
            raise ValueError(f"two channels mapped to the same stick axis {key}; fix config.json")
        used.add(key)
        v = values[ch]
        sticks[key] = -v if m.get("invert") else v
    return sticks


class Gamepad:
    def __init__(self, controls_cfg):
        try:
            import vgamepad as vg
        except ImportError as e:
            raise SystemExit("vgamepad is not installed. Run: pip install vgamepad") from e
        self.vg = vg
        self.cfg = controls_cfg
        self.pad = vg.VX360Gamepad()
        self.last = (0.0, 0.0, 0.0, 0.0)
        time.sleep(0.5)  # give Windows a moment to register the new controller
        self.send(0.0)

    def send(self, throttle, yaw=0.0, pitch=0.0, roll=0.0):
        s = to_stick_values(self.cfg, throttle, yaw, pitch, roll)
        self.pad.left_joystick_float(x_value_float=s[("left", "x")], y_value_float=s[("left", "y")])
        self.pad.right_joystick_float(x_value_float=s[("right", "x")], y_value_float=s[("right", "y")])
        self.pad.update()
        self.last = (throttle, yaw, pitch, roll)

    def min_throttle(self):
        self.send(0.0, 0.0, 0.0, 0.0)

    def trigger(self, side, value):
        """Set the left or right trigger, 0..1 (pushed with the next send)."""
        fn = self.pad.left_trigger_float if side.upper().startswith("L") else self.pad.right_trigger_float
        fn(value_float=_clamp(value, 0.0, 1.0))

    def press(self, name, hold_s=0.2):
        btn = getattr(self.vg.XUSB_BUTTON, BUTTONS[name.upper()])
        self.pad.press_button(button=btn)
        self.pad.update()
        time.sleep(hold_s)
        self.pad.release_button(button=btn)
        self.pad.update()

    def arm(self):
        name = self.cfg.get("arm_button")
        if name:
            self.press(name, self.cfg.get("arm_hold_s", 0.5))
