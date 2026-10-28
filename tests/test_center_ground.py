"""Center-ground candidate: aim at gate centre + proactive ground detector.

p2_straight_center_v1 aimed at the centre (aim_above_frac=0) but had no
camera ground detector at all (no core/ground_flow.py, ground warning
stripped from hover_test): the only ground handling was reactive, after
the drone had already sat on the ground for 1 s. This candidate keeps the
centre aim and adds the camera ground detector: a filtered height-above-
ground under ground_warn_m makes guidance hold ground+ground_clearance_m
and stop sinking *before* contact, without counting as a ground contact
(so the repeated-contact abort cannot fire from detector readings alone).

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
VERSION = ROOT / "versions" / "p2_center_ground_v1"


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
        def __init__(self, x=0.0, y=0.8, size=0.10):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (-0.1, 0.6, 0.1, 0.95)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("center_ground_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def load_ground_flow():
    attitude = types.ModuleType("core.attitude")
    attitude.attitude_deg = lambda stick: 25.2 * stick + 23.3 * stick ** 3
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    return _load("center_ground_flow", VERSION / "core" / "ground_flow.py",
                 {"core": core_pkg, "core.attitude": attitude})


def cfg():
    return json.loads((VERSION / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestCenterGround(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg()

    def test_config_centre_aim_and_detector_on(self):
        self.assertEqual(self.cfg["aim_above_frac"], 0.0)
        self.assertEqual(self.cfg["ground_warn"], 1)
        self.assertGreaterEqual(self.cfg["ground_warn_m"], 1.0)

    def test_target_y_is_gate_centre(self):
        g = self.mod.GateGuidance(self.cfg)
        for y, size in [(0.45, 0.10), (-0.196, 0.6547), (0.66, 0.226)]:
            self.assertAlmostEqual(g.target_y(y, size), y)

    def _approach(self, ground_h, seconds=3.0):
        g = self.mod.GateGuidance(self.cfg)
        gate = self.Gate()  # low in frame: pursuit would sink toward it
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, -2.0, t, t, speed=5.0, ground_h=ground_h)
        return g, cmd

    def test_low_ground_stops_sink_before_contact(self):
        # ALT 10 m but camera reads 0.5 m above ground (hill/road below):
        # ground ALT is 9.5 m, so the target must rise to 9.5+clearance
        # and the commanded climb must not keep sinking.
        g, cmd = self._approach(ground_h=0.5)
        self.assertFalse(cmd.abort)
        self.assertGreaterEqual(cmd.climb, 0.0)
        self.assertGreaterEqual(cmd.height, 9.5 + g.cfg["ground_clearance_m"] - 0.01)
        # Proactive avoidance is not a contact: no escalation/abort counting.
        self.assertEqual(g.ground_contacts, [])
        self.assertFalse(g.failure)

    def test_detector_repeated_warnings_do_not_abort(self):
        g, cmd = self._approach(ground_h=0.3, seconds=6.0)
        self.assertFalse(cmd.abort)
        self.assertFalse(g.failure)

    def test_high_ground_leaves_approach_alone(self):
        g, cmd = self._approach(ground_h=6.0)
        self.assertFalse(cmd.abort)
        # No ground floor in force: nothing forced the target up to 10+.
        self.assertTrue(g.floor is None or g.floor_until is None)

    def test_ground_warn_filter(self):
        flow = load_ground_flow()
        warn = flow.GroundWarn(warn_m=float(self.cfg["ground_warn_m"]))
        for t in (1.0, 1.1):
            warn.add(t, 1.0, {}, 5.0)  # 1.0 * 0.55 scale = 0.55 m: too low
        self.assertTrue(warn.warning(1.1))
        high = flow.GroundWarn(warn_m=float(self.cfg["ground_warn_m"]))
        for t in (1.0, 1.1):
            high.add(t, 10.0, {}, 5.0)
        self.assertFalse(high.warning(1.1))


if __name__ == "__main__":
    unittest.main()
