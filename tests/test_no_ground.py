"""No-ground candidate: proactive camera ground floor on the Roadtrip
31-gate lineage, so the drone never reaches the ground.

p2_finish_blindcap_v6 (flight 20261027_175302, 16 gates) still bounced
on the ground. That lineage has no height-above-ground sensing at all:
the only ground handling is _on_ground, which fires after the drone has
already stopped descending on the ground. The camera ground detector
(core/ground_flow.GroundWarn, proven measuring 0.19 m in the v1 flight)
is ported in here with the authority limits learned in that lineage:
warn at the 1.5 m clearance itself, a detector floor that holds the
height reference, no pitch cap from detector floors (only real contacts
cap pitch), the gate wins near a low gate, and the floor is held
through a crossing.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v7"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v6"


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
        def __init__(self, x=0.0, y=0.2, size=0.10):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (-0.1, 0.6, 0.1, 0.95)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("no_ground_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestNoGround(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def test_config_detector_on_at_clearance(self):
        self.assertEqual(self.cfg["ground_warn"], 1)
        clearance = self.cfg.get("ground_clearance_m",
                                 self.mod.DEFAULTS["ground_clearance_m"])
        self.assertGreaterEqual(self.cfg["ground_warn_m"], clearance)
        self.assertEqual(self.cfg["look_ahead"], self.parent_cfg["look_ahead"])
        self.assertEqual(self.cfg["cross_hold"], self.parent_cfg["cross_hold"])

    def _approach(self, ground_h, seconds=3.0, gate=None):
        g = self.mod.GateGuidance(self.cfg)
        gate = gate or self.Gate()
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=5.0, ground_h=ground_h)
        return g, cmd

    def test_low_ground_stops_sink_before_contact(self):
        g, cmd = self._approach(ground_h=0.75)
        self.assertFalse(cmd.abort)
        self.assertGreaterEqual(cmd.climb, 0.0)
        clearance = g.cfg["ground_clearance_m"]
        self.assertGreaterEqual(cmd.height, 10.0 - 0.75 + clearance - 0.01)
        self.assertEqual(g.ground_contacts, [])  # floor engaged pre-contact

    def test_detector_floor_does_not_cap_pitch(self):
        g, cmd = self._approach(ground_h=0.75, gate=self.Gate(y=0.8, size=0.10))
        self.assertGreater(abs(cmd.pitch), g.cfg["ground_pitch"] + 0.05)

    def test_near_low_gate_gate_wins(self):
        low_gate = self.Gate(y=0.75, size=0.30)
        g, cmd = self._approach(ground_h=0.75, gate=low_gate)
        self.assertLess(cmd.climb, 0.0)
        clearance = g.cfg["ground_clearance_m"]
        self.assertLess(cmd.height, 10.0 - 0.75 + clearance - 0.1)

    def test_floor_survives_crossing(self):
        g, cmd = self._approach(ground_h=0.75, seconds=1.0)
        floor = g.height
        gate = self.Gate()
        gate.clipped = True
        g.crossing_since = g.crossing_start = 1.0
        g.near_size = 0.30
        t = 1.0
        for _ in range(80):
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
