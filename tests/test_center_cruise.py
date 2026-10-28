"""Centre-cruise candidate: centre aim, and the ground detector must not
force a climb into a gate that lies below the flight path.

p2_center_ground_v3 (flight 20261027_161914, 6 gates, mean 5.36 m/s) flew
with aim_above_frac 0.0 confirmed in its meta.json, yet still flew over
gate 7: on that approach the gate sat low (y 0.60-0.84) while the detector
read ~1.0 m above ground, and guidance's post-step forced climb +0.7 m/s
(the logged climb at the moment the gate left the frame), overriding the
pursuit sink to the gate centre. The v3 gate-wins exemption only stopped
the height floor in _update; the climb bump in update() still fired. This
candidate keeps centre aim and the 24 km/h cruise, and makes the gate
win over both ground lifts near a low gate.

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
VERSION = ROOT / "versions" / "p2_center_ground_v4"


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
        def __init__(self, x=0.0, y=0.35, size=0.10):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (-0.1, 0.15, 0.1, 0.55)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("center_cruise_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestCenterCruise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_centre_aim_and_cruise(self):
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        self.assertAlmostEqual(self.cfg["cruise_speed_ms"] * 3.6, 24.0, delta=0.2)
        self.assertEqual(self.cfg["ground_warn"], 1)

    def test_target_y_is_gate_centre(self):
        g = self.mod.GateGuidance(self.cfg)
        for y, size in [(0.45, 0.10), (-0.196, 0.6547), (0.66, 0.226)]:
            self.assertAlmostEqual(g.target_y(y, size), y)

    def _run(self, speed, ground_h=None, seconds=3.0, gate=None, height=10.0):
        g = self.mod.GateGuidance(self.cfg)
        gate = gate or self.Gate()
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, height, 0.0, t, t, speed=speed, ground_h=ground_h)
        return g, cmd

    def test_low_gate_below_no_forced_climb(self):
        # Near gate well below the flight path, detector reading low: the
        # command must keep sinking toward the centre, not climb at +0.7.
        low_gate = self.Gate(y=0.75, size=0.30)
        g, cmd = self._run(speed=5.0, ground_h=0.75, gate=low_gate)
        self.assertFalse(cmd.abort)
        self.assertLess(cmd.climb, 0.0)
        clearance = g.cfg["ground_clearance_m"]
        floor = 10.0 - 0.75 + clearance
        self.assertLess(cmd.height, floor - 0.1)

    def test_low_ground_far_gate_still_protects(self):
        # No near low gate: the same low reading must still stop the sink.
        g, cmd = self._run(speed=5.0, ground_h=0.75)
        self.assertFalse(cmd.abort)
        self.assertGreaterEqual(cmd.climb, 0.0)
        clearance = g.cfg["ground_clearance_m"]
        self.assertGreaterEqual(cmd.height, 10.0 - 0.75 + clearance - 0.01)

    def test_cruise_still_regulates(self):
        _, slow = self._run(speed=2.0)
        _, fast = self._run(speed=10.0)
        self.assertGreater(abs(slow.pitch), abs(fast.pitch))


if __name__ == "__main__":
    unittest.main()
