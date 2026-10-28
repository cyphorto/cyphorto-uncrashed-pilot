"""Gate-line candidate: hold the centre line at >=24 km/h, never lifted
over a gate and never dropped on the ground.

p2_center_ground_v4 (flight 20261027_162343, 11 gates) flew over gate 12.
That approach showed, in order: (1) the pursuit sink vanished on ticks
with no speed reading (_climb_rate multiplies by speed, and only climbs
got a speed-independent term) - logged climb dropped to -0.0 mid-approach;
(2) recover mode sank at only recover_rate 0.7 m/s with no forward pitch;
(3) at the bottom edge the ground climb bump fired again (climb +0.7 in
"flicker") because the gate-wins test compared against the attitude aim
line, which had moved as pitch decayed. This candidate: symmetric
speed-independent pursuit sink, gate-wins whenever a near gate's centre
is in the lower frame (not just past the aim line), strong recover sink
with forward pitch kept, and a cruise regulator that only ever boosts
pitch toward 24 km/h (never eases off, no post-pass slowdown), with
forward_pitch raised to the 0.77 of the pitch record version.

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
VERSION = ROOT / "versions" / "p2_center_ground_v5"


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
        def __init__(self, x=0.0, y=0.35, size=0.10, clipped=False, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.1, 0.15, 0.1, 0.55)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("gate_line_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestGateLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_speed_and_centre(self):
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        self.assertAlmostEqual(self.cfg["cruise_speed_ms"] * 3.6, 24.0, delta=0.2)
        self.assertEqual(self.cfg["post_pass_slow_s"], 0.0)
        self.assertGreaterEqual(self.cfg["forward_pitch"], 0.77)
        self.assertGreaterEqual(self.cfg["pursuit_down"], 1.3)
        self.assertGreaterEqual(self.cfg["recover_rate"], 2.0)
        self.assertEqual(self.cfg["ground_warn"], 1)

    def _run(self, speed, ground_h=None, seconds=3.0, gate=None, height=10.0):
        g = self.mod.GateGuidance(self.cfg)
        gate = gate or self.Gate()
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, height, 0.0, t, t, speed=speed, ground_h=ground_h)
        return g, cmd

    def test_sink_survives_missing_speed_reading(self):
        low_gate = self.Gate(y=0.75, size=0.30)
        _, cmd = self._run(speed=None, gate=low_gate)
        self.assertLess(cmd.climb, -0.5)

    def test_lower_frame_gate_no_ground_climb_bump(self):
        low_gate = self.Gate(y=0.60, size=0.30)
        g, cmd = self._run(speed=5.0, ground_h=0.75, gate=low_gate)
        self.assertFalse(cmd.abort)
        self.assertLess(cmd.climb, 0.0)

    def test_low_ground_far_gate_still_protects(self):
        g, cmd = self._run(speed=5.0, ground_h=0.75)
        self.assertGreaterEqual(cmd.climb, 0.0)
        clearance = g.cfg["ground_clearance_m"]
        self.assertGreaterEqual(cmd.height, 10.0 - 0.75 + clearance - 0.01)

    def test_recover_sinks_hard_and_keeps_moving(self):
        # Clipped gate off to the side and low: recover, not a crossing.
        gate = self.Gate(x=0.8, y=0.8, size=0.30, clipped=True,
                         bbox=(0.6, 0.6, 1.0, 0.95))
        g, cmd = self._run(speed=5.0, gate=gate, seconds=1.0)
        self.assertEqual(cmd.state, "recover")
        self.assertLessEqual(cmd.climb, -2.0)
        self.assertGreater(abs(cmd.pitch), 0.1)

    def test_cruise_only_boosts_never_eases(self):
        _, slow = self._run(speed=2.0)
        _, cruise = self._run(speed=6.67)
        _, fast = self._run(speed=10.0)
        self.assertGreater(abs(slow.pitch), abs(fast.pitch))
        self.assertGreaterEqual(abs(fast.pitch), abs(cruise.pitch) - 1e-9)
        self.assertLessEqual(abs(slow.pitch), self.cfg["forward_pitch"] + 1e-9)


if __name__ == "__main__":
    unittest.main()
