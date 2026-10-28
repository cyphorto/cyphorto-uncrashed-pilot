"""Top-line candidate: no climb into the top bar inside a crossing, and
enough sink authority to follow a dropping gate.

p2_finish_blindcap_v2 (flight 20261027_171701, 11 gates) hit the top of
a gate. Two signatures: inside gate 11's crossing the new cross_hold
pursuit climbed at the +3.0 m/s cap toward a target 0.15 of the gate
height above centre; and gate 12's approach sank at the -3.0 cap for
four seconds at 8.3-8.9 m/s while the gate dropped downhill (y
0.72-0.93), so the drone arrived over its top. This candidate, from
p2_finish_blindcap_v2 with everything else unchanged: inside a crossing
the pursuit targets the gate CENTRE (equal top/bottom margin) and the
climb is capped at +1.0 m/s, and max_climb_rate rises 3.0 -> 4.5 so a
dropping gate can be followed at speed.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v3"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v2"


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
        def __init__(self, x=0.0, y=0.0, size=0.40, clipped=True, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.4, -0.5, 0.4, 1.0)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("top_line_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestTopLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def test_config_sink_authority(self):
        self.assertGreaterEqual(self.cfg["max_climb_rate"], 4.5)
        changed = {k for k in self.cfg
                   if self.cfg.get(k) != self.parent_cfg.get(k)}
        self.assertLessEqual(changed, {"max_climb_rate"})
        self.assertEqual(self.cfg["cross_hold"], 1)

    def _crossing(self, gate, speed=8.0, seconds=1.0):
        g = self.mod.GateGuidance(self.cfg)
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=speed)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, gate.size
        g.cross_last, g.cross_gone = (gate.x, gate.y), False
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=speed)
        return g, cmd

    def test_crossing_never_climbs_at_cap(self):
        # Gate 11's geometry: inside the crossing the pursuit climbed +3.
        _, cmd = self._crossing(self.Gate(y=-0.087, size=0.558))
        self.assertEqual(cmd.state, "crossing")
        self.assertLessEqual(cmd.climb, 1.0)
        self.assertGreater(cmd.climb, 0.0)  # still correcting upward

    def test_crossing_still_sinks_to_centre(self):
        _, cmd = self._crossing(self.Gate(y=0.5, size=0.40))
        self.assertEqual(cmd.state, "crossing")
        self.assertLess(cmd.climb, -0.3)

    def test_approach_sink_authority_at_speed(self):
        # Gate 12's geometry: dropping gate at 8 m/s needs more than -3.
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate(y=0.75, size=0.15, clipped=False,
                         bbox=(-0.1, 0.55, 0.1, 0.95))
        cmd, t = None, 0.0
        for _ in range(60):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=8.0)
        self.assertLessEqual(cmd.climb, -3.5)


if __name__ == "__main__":
    unittest.main()
