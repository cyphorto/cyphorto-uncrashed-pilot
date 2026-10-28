"""Turn-slow candidate: ease off slightly in a sharp turn so the drone
does not slide into the gate side.

p2_center_ground_v9 reached 23 gates (flight 20261027_164745). The user
asked for a slight slowdown when a sharp turn is detected. Sharpness is
the yaw demand (and the visible gate's offset): at full sharpness the
cruise target drops by turn_slow_ms (24 -> ~18 km/h), the regulator
eases pitch toward that lower target, and below it it boosts as usual.
Straight flight keeps the normal 24-30 km/h band.

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
VERSION = ROOT / "versions" / "p2_center_ground_v10"


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
        def __init__(self, x=0.0, y=0.35, size=0.30):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (-0.1, 0.15, 0.1, 0.55)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("turn_slow_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestTurnSlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_turn_slow(self):
        self.assertGreaterEqual(self.cfg["turn_slow_ms"], 1.5)
        self.assertLessEqual(self.cfg["turn_slow_ms"], 2.5)
        self.assertAlmostEqual(self.cfg["cruise_speed_ms"] * 3.6, 24.0, delta=0.2)
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)

    def _run(self, gate, speed, seconds=3.0):
        g = self.mod.GateGuidance(self.cfg)
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=speed, ground_h=None)
        return g, cmd

    def test_sharp_turn_eases_off(self):
        _, straight = self._run(self.Gate(x=0.0), speed=7.5)
        _, sharp = self._run(self.Gate(x=0.9), speed=7.5)
        self.assertLess(abs(sharp.pitch), abs(straight.pitch) - 0.1)
        self.assertGreaterEqual(abs(sharp.pitch), 0.3)

    def test_sharp_turn_still_boosts_when_slow(self):
        _, sharp_fast = self._run(self.Gate(x=0.9), speed=7.5)
        _, sharp_slow = self._run(self.Gate(x=0.9), speed=2.0)
        self.assertGreater(abs(sharp_slow.pitch), abs(sharp_fast.pitch))

    def test_straight_keeps_band(self):
        _, slow = self._run(self.Gate(x=0.0), speed=2.0)
        _, over = self._run(self.Gate(x=0.0), speed=12.0)
        self.assertGreater(abs(slow.pitch), abs(over.pitch))


if __name__ == "__main__":
    unittest.main()
