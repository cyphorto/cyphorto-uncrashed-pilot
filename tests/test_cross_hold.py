"""Cross-hold candidate: a crossing keeps flying the gate centre
vertically instead of freezing the height reference.

Deep analysis of p2_finish_blindcap_v1 (flight 20261027_170655, 31
gates, the best run of the series): every damage onset - 53.3 s, 141.6 s
and gate 32 at 263.1 s - happened inside a crossing, where climb is
commanded 0 and the height reference is frozen, while the drone sank at
1.1-1.7 m/s through the gate. The recorded frame at gate 32 shows the
bottom bar across the bottom of the image: it drooped out of the lower
part of the gate, the same droop that scrapes the ground at low gates.
This candidate (from p2_finish_blindcap_v1, everything else unchanged)
keeps the approach pursuit running inside a crossing while the gate is
visible: climb toward the centre target and the reference integrated
exactly as on approach, so the crossing cannot droop.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v2"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v1"


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
        def __init__(self, x=0.0, y=0.5, size=0.40, clipped=True, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.4, 0.0, 0.4, 1.0)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("cross_hold_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestCrossHold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def test_config_is_blindcap_plus_cross_hold_only(self):
        added = {k for k in self.cfg if k not in self.parent_cfg}
        self.assertLessEqual(added, {"cross_hold"})
        for key, value in self.parent_cfg.items():
            self.assertEqual(self.cfg.get(key), value, key)
        self.assertEqual(self.cfg["blind_cross_s"], self.parent_cfg["blind_cross_s"])

    def _crossing(self, gate):
        g = self.mod.GateGuidance(self.cfg)
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=5.0)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, 0.40
        g.cross_last, g.cross_gone = (gate.x, gate.y), False
        cmd, t = None, 0.0
        for _ in range(20):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=5.0)
        return g, cmd

    def test_crossing_sinks_toward_low_gate(self):
        # Gate below the aim line inside a crossing: sink must not be 0
        # (in the flight it drooped only because climb was frozen at 0;
        # the pursuit itself would have sunk on purpose, on the line).
        _, cmd = self._crossing(self.Gate(y=0.5))
        self.assertEqual(cmd.state, "crossing")
        self.assertLess(cmd.climb, -0.3)

    def test_crossing_climbs_toward_high_gate(self):
        _, cmd = self._crossing(self.Gate(y=-0.6, bbox=(-0.4, -1.0, 0.4, 0.0)))
        self.assertEqual(cmd.state, "crossing")
        self.assertGreater(cmd.climb, 0.3)

    def test_crossing_height_reference_moves(self):
        g, cmd = self._crossing(self.Gate(y=0.5))
        self.assertLess(cmd.height, 10.0)

    def test_blind_crossing_guard_retained(self):
        g, _ = self._crossing(self.Gate(y=0.0))
        cmd, t = None, 1.0
        for _ in range(20):
            t += 0.05
            cmd = g.update(None, 10.0, 0.0, t, t, speed=5.0)
        self.assertLess(abs(cmd.pitch), self.cfg["forward_pitch"])


if __name__ == "__main__":
    unittest.main()
