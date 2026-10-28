"""Above-ground candidate: above-centre aim + ground detector that stays
live on the approach to a gate.

p2_center_ground_v1 (flight 20261027_160010, 25 gates, then failed at the
next gate) aimed at the gate centre and withheld every ground reading once
the gate reached size 0.15 or a crossing started. In that log the filtered
height above ground fell to 0.75 m on the final approach while guidance
received None, so no ground floor was ever set, and the drone hit the
bottom rung. The finishing versions (p2_overflight_no_bounce) aim 0.15 of
the gate height above centre; this candidate restores that, triggers the
ground floor at the clearance height itself, keeps detector readings live
during the approach (withheld only inside a crossing, where a latched
floor is held until the crossing ends).

Loads the frozen candidate's modules directly (stubbing imports) so the
test exercises exactly the code that flies.
"""
import importlib.util
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "versions" / "p2_center_ground_v2"


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
        def __init__(self, x=0.0, y=0.8, size=0.30):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (-0.1, 0.6, 0.1, 0.95)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("above_ground_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestAboveGround(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_aim_above_centre_and_detector_on(self):
        self.assertEqual(self.cfg["aim_above_frac"], 0.15)
        self.assertEqual(self.cfg["ground_warn"], 1)
        clearance = self.cfg.get("ground_clearance_m",
                                 self.mod.DEFAULTS["ground_clearance_m"])
        # The floor must engage at the clearance height, not below it.
        self.assertGreaterEqual(self.cfg["ground_warn_m"], clearance)

    def test_target_y_is_above_gate_centre(self):
        g = self.mod.GateGuidance(self.cfg)
        for y, size in [(0.45, 0.10), (-0.196, 0.6547), (0.66, 0.226)]:
            self.assertLess(g.target_y(y, size), y)

    def _approach(self, ground_h, seconds=3.0):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate()  # near gate (size 0.30), low in frame
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, -2.0, t, t, speed=5.0, ground_h=ground_h)
        return g, cmd

    def test_low_ground_near_gate_stops_sink_before_contact(self):
        g, cmd = self._approach(ground_h=0.75)
        self.assertFalse(cmd.abort)
        self.assertGreaterEqual(cmd.climb, 0.0)
        clearance = g.cfg["ground_clearance_m"]
        self.assertGreaterEqual(cmd.height, 10.0 - 0.75 + clearance - 0.01)
        self.assertEqual(g.ground_contacts, [])

    def test_floor_survives_crossing(self):
        # Set a floor on approach, then cross with no new readings: the
        # height reference must stay at/above the floor until the pass.
        g, cmd = self._approach(ground_h=0.75, seconds=1.0)
        floor = g.floor
        self.assertIsNotNone(floor)
        gate = self.Gate()
        gate.clipped = True
        g.crossing_since = g.crossing_start = 1.0
        t = 1.0
        for _ in range(80):  # 4 s of crossing, past the old floor expiry
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=5.0, ground_h=None)
        self.assertFalse(cmd.abort)
        self.assertGreaterEqual(cmd.height, floor - 0.01)

    def test_ground_sense_live_on_approach_blind_in_crossing(self):
        script = r"""
import sys, types
sys.path.insert(0, sys.argv[1])
import numpy as np
from pilot.hover_test import Flight

class Worker:
    def take(self): return []
class Warn:
    def height(self, t): return 0.75

def make(crossing):
    f = object.__new__(Flight)
    f.io = types.SimpleNamespace(frame=np.zeros((90, 160), np.uint8))
    f.ground_frames, f.next_ground, f.ground_h = [], 1e9, None
    f.ground_worker, f.ground_warn = Worker(), Warn()
    f.sticks = (0.0, 0.0, 0.0)
    guidance = types.SimpleNamespace(
        cfg={"camera_tilt_deg": 30.0},
        crossing_since=100.0 if crossing else None)
    gate = types.SimpleNamespace(visible=True, size=0.30)
    return f._ground_sense(10.0, 5.0, 0.0, 5.0, guidance, {"gate": gate})

print("approach:", make(False))
print("crossing:", make(True))
"""
        out = subprocess.run([sys.executable, "-c", script, str(VERSION)],
                             capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("approach: 0.75", out.stdout)
        self.assertIn("crossing: None", out.stdout)


if __name__ == "__main__":
    unittest.main()
