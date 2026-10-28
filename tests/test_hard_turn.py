"""Hard-turn candidate: more yaw/roll authority and faster steering
response so a gate off to the side can still be made.

p2_center_ground_v5 (flight 20261027_162945, 3 gates) missed gate 4: after
the pass the next gate sat at x 0.54-0.62 through the crossing, yaw peaked
at only 0.437 (never reaching even the old 0.5 cap, thanks to the 0.12 s
steering filter lag), and the crossing then ran straight at full pitch
until speed built to 11.4 m/s, far too fast to turn back for it. This
candidate raises max_yaw to 0.75 and yaw_kp to 2.0, max_bank to 0.65,
roll_kp to 0.6 with max_roll 0.25, and halves the steering filter lag.

Loads the frozen candidate's modules directly (stubbing imports) so the
test exercises exactly the code that flies.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "versions" / "p2_center_ground_v6"


def _load(name, path, stubs):
    saved = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for key, prev in saved.items():
            if prev is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = prev
    return mod


def load_guidance():
    stub = types.ModuleType("core.gate_detector")

    class Gate:
        def __init__(self, x=0.5, y=0.35, size=0.30, clipped=False, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (0.3, 0.15, 0.7, 0.55)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("hard_turn_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestHardTurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_turn_authority(self):
        self.assertGreaterEqual(self.cfg["max_yaw"], 0.75)
        self.assertGreaterEqual(self.cfg["yaw_kp"], 2.0)
        self.assertGreaterEqual(self.cfg["max_bank"], 0.65)
        self.assertGreaterEqual(self.cfg["roll_kp"], 0.6)
        self.assertGreaterEqual(self.cfg["max_roll"], 0.25)
        self.assertLessEqual(self.cfg["filter_s"], 0.08)
        # Previous candidate behaviour is retained.
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        self.assertAlmostEqual(self.cfg["cruise_speed_ms"] * 3.6, 24.0, delta=0.2)

    def _run(self, gate, seconds=3.0, speed=6.67):
        g = self.mod.GateGuidance(self.cfg)
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=speed, ground_h=None)
        return g, cmd

    def test_approach_yaw_reaches_new_authority(self):
        _, cmd = self._run(self.Gate(x=0.5))
        self.assertGreaterEqual(abs(cmd.yaw), 0.6)

    def test_approach_roll_slides_harder(self):
        _, cmd = self._run(self.Gate(x=0.5))
        self.assertGreaterEqual(abs(cmd.roll), 0.2)

    def test_crossing_turn_yaw_and_bank(self):
        g = self.mod.GateGuidance(self.cfg)
        yaw, roll = g._turn(0.55)
        self.assertGreaterEqual(abs(yaw), 0.7)
        self.assertGreaterEqual(abs(roll), 0.6)


if __name__ == "__main__":
    unittest.main()
