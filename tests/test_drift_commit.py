"""Drift-commit candidate: steer where the slide is going, and never
commit to a crossing whose centre is off the flight line.

p2_center_ground_v7 (flight 20261027_163547, 15 gates) flew over the last
gate: the crossing was entered at gate size 0.26 with the centre at
y 0.647, far below the aim line - the frame-inside test passed because
the gate is tall, even though the flight path ran over its top. Across
that flight's successful entries the centre error at entry was almost
always <= 0.3. This candidate refuses a crossing when the centre error
exceeds alignment_y and recovers (strong sink/climb) instead. For drift:
turns steer at the predicted opening - the visible opening's position
plus its rate of movement times a lead - and yaw_kd / speed_kp are
raised so the turn and the speed are held while sliding.

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
VERSION = ROOT / "versions" / "p2_center_ground_v8"


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
        def __init__(self, x=0.0, y=0.35, size=0.30, clipped=False, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.4, -0.5, 0.4, 1.0)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("drift_commit_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestDriftCommit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_drift_gains(self):
        self.assertGreaterEqual(self.cfg["yaw_kd"], 0.3)
        self.assertGreaterEqual(self.cfg["speed_kp"], 0.15)
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        self.assertAlmostEqual(self.cfg["cruise_speed_ms"] * 3.6, 24.0, delta=0.2)

    def test_no_crossing_commit_when_centre_below_line(self):
        g = self.mod.GateGuidance(self.cfg)
        g.pitch_att = 0.7  # cruise attitude: aim line near the horizon
        gate = self.Gate(y=0.75, size=0.30, clipped=True)
        cmd, t = None, 0.0
        for _ in range(40):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=6.67, ground_h=None)
            self.assertNotEqual(cmd.state, "crossing")
        self.assertEqual(g.passes, 0)
        self.assertLess(cmd.climb, 0.0)  # recovering down toward the gate

    def test_crossing_commits_when_centre_on_line(self):
        g = self.mod.GateGuidance(self.cfg)
        g.pitch_att = 0.7
        gate = self.Gate(y=0.0, size=0.30, clipped=True)
        states, t = set(), 0.0
        for _ in range(40):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=6.67, ground_h=None)
            states.add(cmd.state)
        self.assertIn("crossing", states)

    def _crossing_yaw(self, moving):
        g = self.mod.GateGuidance(self.cfg)
        g.pitch_att = 0.7
        gate = self.Gate(y=0.0, size=0.40, clipped=True, bbox=(-0.2, -0.5, 0.4, 1.0))
        cmd = g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=6.67, ground_h=None)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, 0.40
        t = 0.0
        for i in range(40):
            t += 0.05
            a = -0.5 + (0.4 * (i / 39) if moving else 0.4)
            gate = self.Gate(y=0.0, size=0.40, clipped=True,
                             bbox=(a, -0.5, a + 0.6, 1.0))
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=6.67, ground_h=None)
        return cmd

    def test_crossing_steers_at_predicted_opening(self):
        moving = self._crossing_yaw(moving=True)
        still = self._crossing_yaw(moving=False)
        self.assertEqual(moving.state, "crossing")
        self.assertGreater(moving.yaw, still.yaw + 0.05)

    def test_turn_holds_speed(self):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate(x=0.5, y=0.35, size=0.10, clipped=False,
                         bbox=(0.3, 0.15, 0.7, 0.55))
        cmd, t = None, 0.0
        for _ in range(60):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=4.0, ground_h=None)
        self.assertGreaterEqual(abs(cmd.pitch), 0.35)


if __name__ == "__main__":
    unittest.main()
