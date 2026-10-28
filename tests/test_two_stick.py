"""Two-stick candidate: every yaw is a banked turn (yaw + roll together).

p2_center_ground_v6 (flight 20261027_163251, 5 gates, then lost) yawed
with no roll at all in the states that had to recover the flight: search
was yaw-only in 256/256 rows and reacquire_search in 71/71, a flat spin
at pitch ~0 while the drone kept sliding straight and crashed out. In
approach and crossing the bank already followed the yaw. This candidate
centralises the coordination in update(): any commanded yaw carries a
bank roll in the same direction (bank_per_yaw, capped at max_bank),
keeping whichever roll is stronger, in every state.

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
VERSION = ROOT / "versions" / "p2_center_ground_v7"


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
    mod = _load("two_stick_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestTwoStick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_retained(self):
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        self.assertGreaterEqual(self.cfg["bank_per_yaw"], 1.0)
        self.assertGreaterEqual(self.cfg["max_yaw"], 0.75)

    def _guidance_with_seen(self, sx):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate(x=sx)
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=6.67, ground_h=None)
        return g

    def test_search_yaw_is_banked(self):
        g = self._guidance_with_seen(-0.8)
        cmd = None
        for t in (1.0, 2.0, 3.0):
            cmd = g.update(None, 10.0, 0.0, t, t, speed=6.67, ground_h=None)
        self.assertEqual(cmd.state, "search")
        self.assertGreaterEqual(abs(cmd.yaw), 0.3)
        self.assertLessEqual(cmd.roll, -0.4)  # bank follows yaw, same sign
        self.assertEqual(cmd.yaw > 0, cmd.roll > 0)

    def test_recover_yaw_is_banked(self):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate(x=0.8, y=0.8, size=0.30, clipped=True,
                         bbox=(0.6, 0.6, 1.0, 0.95))
        cmd, t = None, 0.0
        for _ in range(20):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=6.67, ground_h=None)
        self.assertEqual(cmd.state, "recover")
        self.assertNotEqual(cmd.yaw, 0.0)
        self.assertEqual(cmd.yaw > 0, cmd.roll > 0)
        self.assertGreaterEqual(abs(cmd.roll), 0.3)

    def test_approach_stays_banked(self):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate(x=0.5)
        cmd, t = None, 0.0
        for _ in range(60):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=6.67, ground_h=None)
        self.assertGreaterEqual(abs(cmd.yaw), 0.6)
        self.assertEqual(cmd.yaw > 0, cmd.roll > 0)
        self.assertGreaterEqual(abs(cmd.roll), 0.3)


if __name__ == "__main__":
    unittest.main()
