"""Flow-line candidate: slow the crossing to the finisher's operating
point, stop steering at a centred gate, and smooth the crossing climb.

Deep analysis of p2_finish_blindcap_v3 (flight 20261027_172213, 16
gates, bottom-right crash) against the confirmed finisher
p2_overflight_no_bounce (9:13.796): stick channels are NOT bumpier in
the failing lineage (direction reversals -9..-22% vs finisher); the
crash was a velocity vector - crossing pitch saturated at 0.70, speed
8.6 m/s, continuous right roll +0.11..+0.30 with gate x only +0.05..+0.10,
sinking -1 m/s into a rotated gate's raised bottom-right, where the
finisher passed the same gates at 5.8 m/s, pitch 0.48, roll 0.027. The
bumpiness that does exist is in the crossing climb: raw detector y,
an asymmetric [-4.5,+1] clamp, and unslewed steps that bang the
throttle (which has no easing). This candidate: forward/near pitch
0.5, crossing lateral deadband |gx|<0.10 with yaw/roll caps 0.10/0.08,
crossing climb on filtered y clamped [-1,1] and slew-limited.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v4"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v3"


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
        def __init__(self, x=0.05, y=0.0, size=0.50, clipped=True, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.25, -0.5, 0.35, 1.0)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("flow_line_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestFlowLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def test_config_finisher_pace(self):
        self.assertAlmostEqual(self.cfg["forward_pitch"], 0.5)
        self.assertAlmostEqual(self.cfg["near_pitch"], 0.5)
        changed = {k for k in self.cfg
                   if self.cfg.get(k) != self.parent_cfg.get(k)}
        self.assertLessEqual(changed, {"forward_pitch", "near_pitch"})
        self.assertEqual(self.cfg["cross_hold"], 1)

    def _crossing(self, gate, seconds=1.0, speed=6.0):
        g = self.mod.GateGuidance(self.cfg)
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=speed)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, gate.size
        g.cross_last, g.cross_gone = (gate.x, gate.y), False
        cmd, t, climbs = None, 0.0, []
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=speed)
            climbs.append(cmd.climb)
        return g, cmd, climbs

    def test_centred_gate_no_lateral_drive(self):
        _, cmd, _ = self._crossing(self.Gate(x=0.05))
        self.assertEqual(cmd.state, "crossing")
        self.assertAlmostEqual(cmd.yaw, 0.0, places=9)
        self.assertAlmostEqual(cmd.roll, 0.0, places=9)

    def test_offset_gate_steering_capped(self):
        gate = self.Gate(x=0.30, bbox=(0.05, -0.5, 0.65, 1.0))
        _, cmd, _ = self._crossing(gate)
        self.assertEqual(cmd.state, "crossing")
        self.assertGreater(cmd.yaw, 0.0)
        self.assertLessEqual(cmd.yaw, 0.10 + 1e-9)
        self.assertLessEqual(cmd.roll, 0.08 + 1e-9)

    def test_crossing_climb_symmetric(self):
        _, cmd, _ = self._crossing(self.Gate(y=0.9, bbox=(-0.25, 0.4, 0.35, 1.4)))
        self.assertEqual(cmd.state, "crossing")
        self.assertGreaterEqual(cmd.climb, -1.0 - 1e-9)
        self.assertLess(cmd.climb, -0.5)

    def test_crossing_climb_slew_limited(self):
        g, cmd, climbs = self._crossing(self.Gate(y=-0.6, bbox=(-0.25, -1.1, 0.35, -0.1)))
        before = climbs[-1]
        gate = self.Gate(y=0.9, bbox=(-0.25, 0.4, 0.35, 1.4))
        cmd = g.update(gate, 10.0, 0.0, 1.05, 1.05, speed=6.0)
        self.assertGreaterEqual(cmd.climb, before - 0.08)


if __name__ == "__main__":
    unittest.main()
