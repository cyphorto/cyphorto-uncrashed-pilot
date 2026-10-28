"""Straight candidate: aligned-approach pitch floor must keep the drone moving
forward instead of stop/start settling into the ground, without breaking
default construction, misaligned approaches, or the post-contact pitch cap.

Loads the frozen candidate's guidance.py directly (stubbing its only import)
so the test exercises exactly the code that flies.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "versions" / "p2_straight_recovery_v2"


def load_guidance():
    stub = types.ModuleType("core.gate_detector")

    class Gate:
        def __init__(self, x=0.0, y=0.45, size=0.10):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (-0.1, 0.3, 0.1, 0.6)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    saved = {k: sys.modules.get(k) for k in ("core", "core.gate_detector")}
    sys.modules["core"] = core_pkg
    sys.modules["core.gate_detector"] = stub
    try:
        spec = importlib.util.spec_from_file_location(
            "straight_guidance", VERSION / "pilot" / "guidance.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:  # leave no stub behind for other tests in this process
        for key, prev in saved.items():
            if prev is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = prev
    return mod, Gate


def candidate_cfg(mod):
    cfg = json.loads((VERSION / "config.json").read_text(encoding="utf-8"))
    return cfg["gate_pilot"]


class TestStraightGuidance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()

    def test_defaults_construct(self):
        # Regression: the first build put straight_pitch_floor=0.35 in DEFAULTS
        # while default forward_pitch is 0.07, so GateGuidance() raised.
        g = self.mod.GateGuidance()
        self.assertLessEqual(g.cfg["straight_pitch_floor"], g.cfg["forward_pitch"])

    def test_candidate_config(self):
        g = self.mod.GateGuidance(candidate_cfg(self.mod))
        self.assertEqual(g.cfg["straight_pitch_floor"], 0.35)
        self.assertEqual(g.cfg["forward_pitch"], 0.7)
        self.assertEqual(g.cfg["near_brake"], 0)

    def _approach_pitch(self, gate_x, velocity):
        g = self.mod.GateGuidance(candidate_cfg(self.mod))
        gate = self.Gate(x=gate_x)
        cmd = None
        t = 0.0
        for _ in range(30):  # pass acquire_s, let filters settle on the gate
            t += 0.05
            cmd = g.update(gate, 0.0, velocity, t, t)
        return g, cmd

    def test_aligned_unsettled_keeps_forward_pitch(self):
        # Far, centred gate but a wild vertical-speed reading: the parent's
        # settled fade zeroes the pitch (stop/start that ends on the ground).
        _, cmd = self._approach_pitch(gate_x=0.0, velocity=-5.0)
        self.assertGreaterEqual(cmd.pitch, 0.35)

    def test_misaligned_gets_no_floor(self):
        _, cmd = self._approach_pitch(gate_x=0.5, velocity=-5.0)
        self.assertLess(cmd.pitch, 0.35)

    def test_ground_contact_cap_still_wins(self):
        g, cmd = self._approach_pitch(gate_x=0.0, velocity=0.0)
        g.ground_contact(0.0, 100.0)
        gate = self.Gate(x=0.0)
        cmd = g.update(gate, 0.0, -5.0, 100.05, 100.05)
        self.assertLessEqual(cmd.pitch, g.cfg["ground_pitch"] + 1e-9)


if __name__ == "__main__":
    unittest.main()
