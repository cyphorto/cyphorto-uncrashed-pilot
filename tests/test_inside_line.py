"""Inside-line candidate: no lateral steering once inside a gate.

p2_center_ground_v10 (flight 20261027_165404) hit the side of the third
gate it crossed. The approach was centred (x 0.03-0.04); inside the
crossing, at gate size 0.49, the detected gate centre jumped to -0.52
(the post leaving the frame) and cross-steering yawed/rolled -0.14/-0.13
after it, into the post - the damaged icon appears a second later. Once
the gate is that big the drone is inside it and committed: this
candidate holds the entry line (yaw and roll zero) above
cross_freeze_size, and keeps the drift-lead steering below it.

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
VERSION = ROOT / "versions" / "p2_center_ground_v11"


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
        def __init__(self, x=-0.3, y=0.0, size=0.50, clipped=True, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.9, -0.5, 0.3, 1.0)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("inside_line_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestInsideLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_retained(self):
        self.assertGreater(self.cfg["cross_freeze_size"], 0.3)
        self.assertLess(self.cfg["cross_freeze_size"], 0.6)
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)

    def _crossing(self, size):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate(size=size)
        g.update(gate, 10.0, 0.0, 0.0, 0.0, speed=6.67, ground_h=None)
        g.crossing_since = g.crossing_start = 0.0
        g.near_size, g.cross_peak = 0.30, size
        cmd, t = None, 0.0
        for _ in range(10):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=6.67, ground_h=None)
        return cmd

    def test_inside_gate_holds_line(self):
        cmd = self._crossing(size=0.50)
        self.assertEqual(cmd.state, "crossing")
        self.assertAlmostEqual(cmd.yaw, 0.0, places=9)
        self.assertAlmostEqual(cmd.roll, 0.0, places=9)
        self.assertGreater(abs(cmd.pitch), 0.5)  # still flying through

    def test_before_gate_still_steers(self):
        cmd = self._crossing(size=0.35)
        self.assertEqual(cmd.state, "crossing")
        self.assertGreater(abs(cmd.yaw) + abs(cmd.roll), 0.1)


if __name__ == "__main__":
    unittest.main()
