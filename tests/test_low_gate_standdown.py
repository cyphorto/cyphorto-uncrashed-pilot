"""Low-gate stand-down candidate: on the best pilot (v7), detector
lifts must not fight a sink toward a low gate at ANY gate size.

p2_finish_blindcap_v7 (flight 20261027_180059, 46 gates, no contact)
flew over its last gate: a steep downhill gate stayed at gate y
0.48-0.80 for 7 s while hillside detector readings of 0.99-1.47 m kept
firing the +0.7 climb bump and froze h_ref at 31.237 for 5 s. The
gate-wins exemption required gate size >= 0.7*near_size; that gate was
0.04-0.15 for most of the approach, so the lifts applied. This
candidate: a visible gate below the flight line stands the detector
down (no floor set, no climb bump, existing detector floor dropped)
whenever the drone is already sinking toward it - velocity down, a
large centre error, or a sinking command - regardless of gate size.
When it is not sinking toward the gate, protection is unchanged.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v8"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v7"


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
        def __init__(self, x=0.0, y=0.65, size=0.06):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (-0.05, 0.45, 0.05, 0.85)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("low_gate_standdown_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestLowGateStanddown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def test_config_unchanged_from_best(self):
        self.assertEqual(self.cfg, self.parent_cfg)
        self.assertEqual(self.cfg["ground_warn"], 1)

    def _run(self, gate, velocity, ground_h=1.1, seconds=3.0, height=30.0):
        g = self.mod.GateGuidance(self.cfg)
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, height, velocity, t, t, speed=5.5, ground_h=ground_h)
        return g, cmd

    def test_small_low_gate_sinking_no_detector_lift(self):
        # Gate 47's geometry: far, small, well below the line, sinking.
        g, cmd = self._run(self.Gate(), velocity=-1.0)
        self.assertFalse(cmd.abort)
        self.assertLess(cmd.climb, 0.0)  # sink preserved, not bumped to +0.7
        clearance = g.cfg["ground_clearance_m"]
        floor = 30.0 - 1.1 + clearance
        self.assertLess(cmd.height, floor - 0.1)  # reference not held up

    def test_same_gate_not_sinking_still_protects(self):
        g, cmd = self._run(self.Gate(), velocity=1.0, seconds=1.0)
        clearance = g.cfg["ground_clearance_m"]
        self.assertGreaterEqual(cmd.height, 30.0 - 1.1 + clearance - 0.01)

    def test_low_ground_no_gate_still_protects(self):
        g = self.mod.GateGuidance(self.cfg)
        cmd, t = None, 0.0
        gate = self.Gate(y=0.2, size=0.10)
        for _ in range(60):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=5.0, ground_h=0.75)
        self.assertGreaterEqual(cmd.climb, 0.0)
        clearance = g.cfg["ground_clearance_m"]
        self.assertGreaterEqual(cmd.height, 10.0 - 0.75 + clearance - 0.01)
        self.assertEqual(g.ground_contacts, [])


if __name__ == "__main__":
    unittest.main()
