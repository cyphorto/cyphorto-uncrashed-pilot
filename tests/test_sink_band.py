"""Sink-band candidate: cap the approach speed to a band, raise the sink
authority, and close the flicker hole in the gate-wins test.

p2_center_ground_v8 (flight 20261027_164403, 7 gates) flew over gate 8.
It arrived at 8-10 m/s with the sink already pinned at the 3.0 m/s cap
while the gate dropped away downhill, so even maximum sink could not
hold the centre line; and at the bottom edge a flicker frame (gate
visible but failing the shape test) let the ground climb bump fire
again, because _gate_below required a fully valid gate. This candidate:
max_climb_rate 4.5, recover_rate 3.5, a cruise band (boost below
24 km/h, ease above 30 km/h, never below a moving pitch floor), and a
gate-wins test that works on the raw visible gate, flicker included.

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
VERSION = ROOT / "versions" / "p2_center_ground_v9"


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
        def __init__(self, x=0.0, y=0.35, size=0.10, clipped=False, bbox=None, corners=4):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * corners
            self.bbox = bbox if bbox is not None else (-0.1, 0.15, 0.1, 0.55)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("sink_band_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestSinkBand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_sink_and_band(self):
        self.assertGreaterEqual(self.cfg["max_climb_rate"], 4.5)
        self.assertGreaterEqual(self.cfg["recover_rate"], 3.5)
        self.assertAlmostEqual(self.cfg["cruise_speed_ms"] * 3.6, 24.0, delta=0.2)
        self.assertGreaterEqual(self.cfg["cruise_max_ms"] * 3.6, 29.0)
        self.assertLessEqual(self.cfg["cruise_max_ms"] * 3.6, 31.0)
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)

    def _run(self, speed, ground_h=None, seconds=3.0, gate=None, height=10.0):
        g = self.mod.GateGuidance(self.cfg)
        gate = gate or self.Gate()
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, height, 0.0, t, t, speed=speed, ground_h=ground_h)
        return g, cmd

    def test_max_sink_at_speed(self):
        low_gate = self.Gate(y=0.75, size=0.30)
        _, cmd = self._run(speed=9.0, gate=low_gate)
        self.assertLessEqual(cmd.climb, -4.0)

    def test_speed_band_eases_overspeed_keeps_moving(self):
        _, slow = self._run(speed=2.0)
        _, band = self._run(speed=6.67)
        _, over = self._run(speed=12.0)
        self.assertGreater(abs(slow.pitch), abs(over.pitch))
        self.assertLess(abs(over.pitch), abs(band.pitch))
        self.assertGreaterEqual(abs(over.pitch), 0.3)

    def test_flicker_gate_still_blocks_ground_bump(self):
        # Gate visible at the bottom edge but failing the shape test
        # (no corners): the ground bump must not fire through it.
        flick = self.Gate(y=0.8, size=0.32, clipped=True, corners=0,
                          bbox=(-0.4, 0.5, 0.4, 1.0))
        g = self.mod.GateGuidance(self.cfg)
        cmd, t = None, 0.0
        for _ in range(20):
            t += 0.05
            cmd = g.update(flick, 10.0, 0.0, t, t, speed=6.67, ground_h=0.62)
        self.assertLessEqual(cmd.climb, 0.0)

    def test_recover_sink_strong(self):
        gate = self.Gate(x=0.8, y=0.8, size=0.30, clipped=True,
                         bbox=(0.6, 0.6, 1.0, 0.95))
        gate.corners = [(0, 0)] * 4
        g, cmd = self._run(speed=6.67, gate=gate, seconds=1.0)
        self.assertEqual(cmd.state, "recover")
        self.assertLessEqual(cmd.climb, -3.5)


if __name__ == "__main__":
    unittest.main()
