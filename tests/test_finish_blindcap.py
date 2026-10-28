"""Finish candidate: the proven finisher, plus one blind-crossing guard.

Across every p2_center_ground_v1..v11 failure the terminal pattern was
the same: a crossing went blind and the pilot held full pitch until the
next gate was lost (v1 after gate 25, v9 after gate 23, v10 gate 4, v11
gates 2 and 5). The only pilots that ever finished this course,
p2_fast_baseline and p2_overflight_no_bounce (annotations.csv confirmed),
share one identical config with none of the v-lineage features: no ground
detector authority, no cruise regulator, no turn slowdown, no cross
freeze. This candidate freezes from p2_overflight_no_bounce unchanged
except one addition: in a crossing, once the gate has been invisible for
blind_cross_s, stop holding full pitch blind - hand over to the existing
crossing reacquire (which brakes and searches toward the last sighting).

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v1"
PARENT = ROOT / "versions" / "p2_overflight_no_bounce"


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
    mod = _load("finish_blindcap_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestFinishBlindcap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def test_config_is_finisher_plus_blind_keys_only(self):
        added = {k for k in self.cfg if k not in self.parent_cfg}
        self.assertLessEqual(added, {"blind_cross_s", "blind_cross_pitch"})
        for key, value in self.parent_cfg.items():
            self.assertEqual(self.cfg.get(key), value, key)
        # The regressed v-lineage features must stay absent/inert.
        self.assertNotEqual(self.cfg.get("ground_warn"), 1)
        self.assertFalse(self.cfg.get("cruise_speed_ms"))
        self.assertFalse(self.cfg.get("turn_slow_ms"))
        self.assertFalse(self.cfg.get("cross_freeze_size"))
        self.assertFalse(self.cfg.get("cross_lead_s"))

    def _crossing_guidance(self):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate()
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=5.0)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, 0.40
        g.cross_last, g.cross_gone = (0.0, 0.0), False
        return g

    def test_visible_crossing_flies_full_pitch(self):
        g = self._crossing_guidance()
        gate = self.Gate()
        cmd = g.update(gate, 10.0, 0.0, 0.1, 0.1, speed=5.0)
        self.assertEqual(cmd.state, "crossing")
        self.assertAlmostEqual(abs(cmd.pitch), self.cfg["forward_pitch"])

    def test_blind_crossing_stops_holding_full_pitch(self):
        g = self._crossing_guidance()
        cmd, t = None, 0.0
        for _ in range(40):  # 2 s with no gate at all
            t += 0.05
            cmd = g.update(None, 10.0, 0.0, t, t, speed=5.0)
            if t >= 0.65:  # past blind_cross_s with no gate seen
                self.assertNotEqual(
                    (cmd.state, round(abs(cmd.pitch), 2)),
                    ("crossing", round(self.cfg["forward_pitch"], 2)),
                    f"still blind at full pitch at t={t}")
        # It must hand over to the reacquire search, not abort outright.
        self.assertIn(cmd.state, ("reacquire_search", "crossing"))
        self.assertLess(abs(cmd.pitch), self.cfg["forward_pitch"])


if __name__ == "__main__":
    unittest.main()
