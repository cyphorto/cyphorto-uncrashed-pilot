"""Faster-cruise candidate: on the best pilot (v8), one small speed
change only - cruise pitch 0.70 -> 0.74 (+5.7%).

p2_finish_blindcap_v8 is the best pilot (60 gates, 461.8 s, mean
5.67 m/s, no damage). Its flight log spends 79% of the run in
approach/crossing at or scaled by forward_pitch, while the sharp-turn
active brake fires for only 1.3 s total, so the cruise pitch is the
lever that moves the total time. Everything that keeps v8 safe -
turn brake, blind-crossing cap, search pitch, detector stand-down -
must stay exactly as it was: this candidate changes the two cruise
pitch values (forward_pitch/near_pitch, kept equal as in every
finisher config) and nothing else, in code or config.

Loads the frozen candidate's modules directly (stubbing imports) so
the test exercises exactly the code that flies.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "versions" / "p2_finish_blindcap_v9"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v8"
OLD_PITCH = 0.70
NEW_PITCH = 0.74


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


def load_guidance(tag, version):
    stub = types.ModuleType("core.gate_detector")

    class Gate:
        def __init__(self, x=0.0, y=0.2, size=0.15, clipped=False, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.1, 0.0, 0.1, 0.4)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load(f"faster_cruise_{tag}_guidance", version / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))


class TestFasterCruise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance("v9", VERSION)
        cls.parent_mod, _ = load_guidance("v8", PARENT)
        cls.full = cfg_of(VERSION)
        cls.parent_full = cfg_of(PARENT)
        cls.cfg = cls.full["gate_pilot"]
        cls.parent_cfg = cls.parent_full["gate_pilot"]

    def test_only_cruise_pitch_changed(self):
        self.assertAlmostEqual(self.parent_cfg["forward_pitch"], OLD_PITCH)
        self.assertAlmostEqual(self.parent_cfg["near_pitch"], OLD_PITCH)
        changed = {k for k in self.cfg
                   if self.cfg.get(k) != self.parent_cfg.get(k)}
        self.assertEqual(changed, {"forward_pitch", "near_pitch"})
        self.assertAlmostEqual(self.cfg["forward_pitch"], NEW_PITCH)
        self.assertAlmostEqual(self.cfg["near_pitch"], NEW_PITCH)
        for section, values in self.parent_full.items():
            if section != "gate_pilot":
                self.assertEqual(self.full.get(section), values, section)

    def _crossing_pitch(self, mod, cfg):
        g = mod.GateGuidance(cfg)
        gate = self.Gate(size=0.40, clipped=True, bbox=(-0.4, -0.5, 0.4, 1.0))
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=5.0)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, 0.40
        g.cross_last, g.cross_gone = (0.0, 0.0), False
        cmd = g.update(gate, 10.0, 0.0, 0.1, 0.1, speed=5.0)
        self.assertEqual(cmd.state, "crossing")
        return abs(cmd.pitch)

    def test_crossing_pitch_scales_by_the_one_change(self):
        new = self._crossing_pitch(self.mod, self.cfg)
        old = self._crossing_pitch(self.parent_mod, self.parent_cfg)
        self.assertAlmostEqual(old, OLD_PITCH)
        self.assertAlmostEqual(new, NEW_PITCH)
        self.assertAlmostEqual(new / old, NEW_PITCH / OLD_PITCH)

    def _run(self, mod, cfg, gate, speed, seconds=2.0):
        g = mod.GateGuidance(cfg)
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=speed)
        return cmd

    def test_sharp_turn_brake_unchanged(self):
        # Above turn_speed_ms a far-sideways gate still gets the same
        # active brake in both versions; the speed gain comes only
        # from straights/crossings, not from carrying speed into turns.
        for mod, cfg in ((self.mod, self.cfg),
                         (self.parent_mod, self.parent_cfg)):
            cmd = self._run(mod, cfg, self.Gate(x=0.7, y=0.7), speed=8.0)
            self.assertLess(cmd.pitch, 0.0)
            self.assertAlmostEqual(cmd.pitch, -cfg["turn_brake_pitch"])
            self.assertGreaterEqual(abs(cmd.yaw), 0.4)


if __name__ == "__main__":
    unittest.main()
