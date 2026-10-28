"""Center-aim candidate: fly through the gate centre, not above it.

p2_straight_recovery_v2 (aim_above_frac=0.15) steered 15% of the gate height
above centre and hit the top of gate 12 (user-watched, 2026-10-27). The
candidate sets aim_above_frac=0.0 so target_y is the centre: the flight path
then keeps half the gate height of margin from both the top and bottom bars,
the most margin the gate allows. Everything else (straight pitch floor,
cruise, recovery) is inherited unchanged from the parent.

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
VERSION = ROOT / "versions" / "p2_straight_center_v1"
PARENT = ROOT / "versions" / "p2_straight_recovery_v2"


def load_guidance(version):
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
            "center_guidance", version / "pilot" / "guidance.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for key, prev in saved.items():
            if prev is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = prev
    return mod


def cfg_of(version, mod):
    cfg = json.loads((version / "config.json").read_text(encoding="utf-8"))
    return cfg["gate_pilot"]


class TestCenterAim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_guidance(VERSION)
        cls.cfg = cfg_of(VERSION, cls.mod)

    def test_candidate_aims_at_centre_parent_above(self):
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        parent_cfg = cfg_of(PARENT, self.mod)
        self.assertEqual(parent_cfg["aim_above_frac"], 0.15)

    def test_inherited_straight_settings_unchanged(self):
        self.assertEqual(self.cfg["straight_pitch_floor"], 0.35)
        self.assertEqual(self.cfg["forward_pitch"], 0.7)
        self.assertEqual(self.cfg["near_brake"], 0)
        # frame_margin is a guidance DEFAULT (not a config override): the
        # crossing check keeps the flight path in the middle 60% of the gate.
        g = self.mod.GateGuidance(self.cfg)
        self.assertEqual(g.cfg["frame_margin"], 0.2)

    def test_target_y_is_gate_centre_with_max_margin(self):
        g = self.mod.GateGuidance(self.cfg)
        # Gate 12's last sighting in the 2026-10-27 run: y=-0.196, size=0.6547.
        for y, size in [(0.45, 0.10), (-0.196, 0.6547), (0.66, 0.226)]:
            self.assertAlmostEqual(g.target_y(y, size), y)
            # Centre -> equal margin to top and bottom bar: half the gate
            # height in image-y units (size*2*16/9 tall, so half is size*16/9).
            half = size * 16 / 9
            self.assertAlmostEqual(g.target_y(y, size) - (y - half), half)
            self.assertAlmostEqual((y + half) - g.target_y(y, size), half)

    def test_parent_target_was_above_centre(self):
        # The failure this candidate removes, on the parent's own config.
        g = self.mod.GateGuidance(cfg_of(PARENT, self.mod))
        self.assertLess(g.target_y(-0.196, 0.6547), -0.196)


if __name__ == "__main__":
    unittest.main()
