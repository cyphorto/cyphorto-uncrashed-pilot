"""Cruise-ground candidate: 24 km/h cruise, slow only after a pass, and
the gate (not the ground floor) wins near a gate.

p2_center_ground_v2 (flight 20261027_161254, 5 gates, mean 2.55 m/s) was
slow because the detector floor inherited the post-contact pitch cap:
73.7% of gate-phase rows sat at pitch <= 0.13. It then flew over the last
gate because the floor kept raising the height reference (21.7 -> 23.8 m)
while the gate sat below the level line (y 0.61-0.69). This candidate:
centre aim again (the floor, now live on approach, guards the bottom
rung), no pitch cap from detector floors (contact floors keep it), a
speed regulator targeting 24 km/h (6.67 m/s) on approach/crossing with
pitch taken off only in a short window after each counted pass, and no
floor lift near a gate that lies below the flight path.

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
VERSION = ROOT / "versions" / "p2_center_ground_v3"


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
    mod = _load("cruise_ground_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestCruiseGround(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_cruise_and_centre_aim(self):
        self.assertAlmostEqual(self.cfg["cruise_speed_ms"] * 3.6, 24.0, delta=0.2)
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        self.assertEqual(self.cfg["ground_warn"], 1)
        self.assertEqual(self.cfg["vert_brake"], 0)
        self.assertGreater(self.cfg["post_pass_slow_s"], 0.0)

    def _run(self, speed, ground_h=None, seconds=3.0, gate=None, height=10.0):
        g = self.mod.GateGuidance(self.cfg)
        gate = gate or self.Gate()
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, height, 0.0, t, t, speed=speed, ground_h=ground_h)
        return g, cmd

    def test_detector_floor_does_not_cap_pitch(self):
        # Low ground on approach: height floor engages, forward pitch must not.
        g, cmd = self._run(speed=5.0, ground_h=0.75)
        self.assertIsNotNone(g.floor)
        self.assertGreater(abs(cmd.pitch), g.cfg["ground_pitch"] + 0.05)

    def test_contact_floor_still_caps_pitch(self):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate()
        cmd, t = None, 0.0
        for _ in range(60):
            t += 0.05
            if t == 0.05:
                g.ground_contact(9.0, t)
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=5.0, ground_h=None)
        self.assertLessEqual(abs(cmd.pitch), g.cfg["ground_pitch"] + 1e-9)

    def test_cruise_regulator_boosts_slow_and_eases_fast(self):
        _, slow = self._run(speed=2.0)
        _, cruise = self._run(speed=6.67)
        _, fast = self._run(speed=10.0)
        self.assertGreater(abs(slow.pitch), abs(cruise.pitch))
        self.assertGreater(abs(cruise.pitch), abs(fast.pitch))
        self.assertLessEqual(abs(slow.pitch), self.cfg["forward_pitch"] + 1e-9)

    def test_slowdown_only_after_a_pass(self):
        # Same slow speed: no pass yet -> cruise pitch; just passed -> capped.
        g, cmd = self._run(speed=2.0)
        self.assertGreater(abs(cmd.pitch), self.cfg["post_pass_pitch"] + 0.05)
        g2 = self.mod.GateGuidance(self.cfg)
        gate = self.Gate()
        cmd2, t = None, 0.0
        for _ in range(60):
            t += 0.05
            cmd2 = g2.update(gate, 10.0, 0.0, t, t, speed=2.0, ground_h=None)
            if abs(t - 1.0) < 1e-9:
                g2.passes, g2.last_pass_t = 1, t
            if abs(t - 1.5) < 1e-9:
                break  # still inside the post-pass slow window
        self.assertLessEqual(abs(cmd2.pitch), self.cfg["post_pass_pitch"] + 1e-9)

    def test_near_gate_below_wins_over_floor(self):
        # Near gate well below the level line: follow the gate down, do not
        # let the detector floor lift the reference over its top bar.
        low_gate = self.Gate(y=0.75, size=0.30)
        g, cmd = self._run(speed=5.0, ground_h=0.75, gate=low_gate)
        clearance = g.cfg["ground_clearance_m"]
        floor = 10.0 - 0.75 + clearance
        self.assertLess(cmd.height, floor - 0.1)

    def test_crossing_does_not_raise_height_to_floor(self):
        g, cmd = self._run(speed=5.0, ground_h=0.75, seconds=1.0)
        entry_height = g.height
        gate = self.Gate()
        gate.clipped = True
        g.near_size = gate.size
        g.crossing_since = g.crossing_start = 1.0
        t = 1.0
        for _ in range(40):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=5.0, ground_h=None)
        self.assertLessEqual(cmd.height, entry_height + 0.01)


if __name__ == "__main__":
    unittest.main()
