"""Sharp-turn candidate (Roadtrip): detect the next gate early, slow
massively to turn, then go straight - on the 31-gate configuration.

p2_finish_blindcap_v1 reached 31 gates (best attempt) but crashed and
recovered; p2_finish_blindcap_v3 kept its ground/gate protection
(cross_hold, sink authority, blind guard). What neither had: the next
gate at a sharp angle was only reacted to once it turned green and the
drone was already carrying straight-line speed into the turn. This
candidate enables look_ahead (magenta next-gate detection, already
wired in the flight loop but switched off) and adds a turn brake:
while the gate is far off to the side and speed is above turn speed,
pitch goes negative (active braking in ANGLE mode) while yaw/roll
turn; once aligned or slow, full straight pitch resumes.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v6"
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
    mod = _load("sharp_turn_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestSharpTurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def test_config_lookahead_and_protection_kept(self):
        self.assertEqual(self.cfg["look_ahead"], 1)
        self.assertEqual(self.cfg["cross_hold"], 1)
        self.assertGreaterEqual(self.cfg["max_climb_rate"], 4.5)
        self.assertEqual(self.cfg["blind_cross_s"], self.parent_cfg["blind_cross_s"])
        self.assertAlmostEqual(self.cfg["forward_pitch"], 0.7)

    def _run(self, gate, speed, seconds=2.0, future=None):
        g = self.mod.GateGuidance(self.cfg)
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=speed, future=future)
        return g, cmd

    def test_straight_gate_full_pitch(self):
        _, cmd = self._run(self.Gate(x=0.0, y=0.7), speed=8.0)
        self.assertGreaterEqual(cmd.pitch, 0.4)

    def test_sharp_gate_brakes_hard_while_turning(self):
        _, cmd = self._run(self.Gate(x=0.7, y=0.7), speed=8.0)
        self.assertLess(cmd.pitch, 0.0)          # active brake, not just coast
        self.assertGreaterEqual(abs(cmd.yaw), 0.4)  # and turning at the same time

    def test_sharp_gate_slow_speed_no_brake(self):
        _, cmd = self._run(self.Gate(x=0.7, y=0.7), speed=3.0)
        self.assertGreaterEqual(cmd.pitch, 0.0)
        self.assertLessEqual(cmd.pitch, 0.25)

    def test_aligned_again_goes_straight(self):
        g, cmd = self._run(self.Gate(x=0.7, y=0.7), speed=8.0, seconds=1.0)
        gate = self.Gate(x=0.0, y=0.7)
        t = 1.0
        for _ in range(40):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=8.0)
        self.assertGreaterEqual(cmd.pitch, 0.4)

    def test_next_gate_seen_in_crossing_turns_early_and_slow(self):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate(x=0.0, size=0.40, clipped=True, bbox=(-0.4, -0.5, 0.4, 1.0))
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=8.0)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, 0.40
        g.cross_last, g.cross_gone = (0.0, 0.0), True
        nxt = self.Gate(x=0.8, size=0.10)
        cmd = g.update(None, 10.0, 0.0, 0.5, 0.5, speed=8.0, future=[nxt])
        self.assertGreater(abs(cmd.yaw), 0.2)
        self.assertLess(cmd.pitch, 0.25)


if __name__ == "__main__":
    unittest.main()
