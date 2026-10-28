"""U-turn candidate (Docks): slower pace, and turn back when no gate
is seen instead of giving up.

The p2_finish_blindcap_v4 run on the new setting (flight
20261027_173842) crashed after 3 gates, stuck with the damaged icon,
after spending its ending in reacquire_search with no gate in view.
The user asked for: avoid side obstacles (stay centred - the v4
crossing deadband is kept), go slower so the course can be completed,
and do a U-turn when no gate is seen. This candidate, from
p2_finish_blindcap_v4: forward/near pitch 0.35, and when the search
(or a crossing reacquire) runs out without a gate, the pilot U-turns -
banked, at search pitch, toward the side the gate was last seen -
up to uturn_max times, instead of aborting. A gate back in view is
approached normally, and the U-turn count resets on a counted pass.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v5"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v4"


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
        def __init__(self, x=0.6, y=0.2, size=0.20):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = (0.4, 0.0, 0.8, 0.4)
            self.clipped = False

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load("uturn_guidance", VERSION / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))["gate_pilot"]


class TestUturnSlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance()
        cls.cfg = cfg_of(VERSION)
        cls.parent_cfg = cfg_of(PARENT)

    def _fast_cfg(self):
        c = dict(self.cfg)
        c["search_s"] = 1.0
        c["reacquire_s"] = 1.0
        return c

    def test_config_slower_and_uturn(self):
        self.assertAlmostEqual(self.cfg["forward_pitch"], 0.35)
        self.assertAlmostEqual(self.cfg["near_pitch"], 0.35)
        self.assertGreaterEqual(self.cfg["uturn_s"], 2.0)
        self.assertGreaterEqual(self.cfg["uturn_max"], 1)
        changed = {k for k in self.cfg
                   if self.cfg.get(k) != self.parent_cfg.get(k)}
        self.assertLessEqual(changed, {"forward_pitch", "near_pitch",
                                       "uturn_s", "uturn_max"})

    def _guidance_seen_gate(self):
        g = self.mod.GateGuidance(self._fast_cfg())
        g.update(self.Gate(), 10.0, 0.0, 0.0, 0.0, speed=3.0)
        return g

    def test_no_gate_triggers_uturn_not_abort(self):
        g = self._guidance_seen_gate()
        states, cmd, t = {}, None, 0.0
        for _ in range(80):  # 4 s with no gate
            t += 0.05
            cmd = g.update(None, 10.0, 0.0, t, t, speed=3.0)
            states[cmd.state] = states.get(cmd.state, 0) + 1
            if cmd.state == "uturn":
                break
        self.assertIn("uturn", states)
        self.assertFalse(cmd.abort)
        self.assertGreater(cmd.yaw, 0.2)   # toward last seen side (+x)
        self.assertGreater(cmd.roll, 0.0)  # banked, same direction
        self.assertLessEqual(abs(cmd.pitch), self.mod.DEFAULTS["search_pitch"] + 0.01)

    def test_gate_back_in_view_ends_uturn(self):
        g = self._guidance_seen_gate()
        t = 0.0
        for _ in range(40):
            t += 0.05
            cmd = g.update(None, 10.0, 0.0, t, t, speed=3.0)
            if cmd.state == "uturn":
                break
        cmd = g.update(self.Gate(), 10.0, 0.0, t + 0.05, t + 0.05, speed=3.0)
        self.assertNotEqual(cmd.state, "uturn")
        self.assertFalse(cmd.abort)

    def test_uturn_is_bounded_then_aborts(self):
        g = self._guidance_seen_gate()
        cmd, t, saw_uturn = None, 0.0, False
        for _ in range(2400):  # up to 120 s with no gate ever
            t += 0.05
            cmd = g.update(None, 10.0, 0.0, t, t, speed=3.0)
            saw_uturn = saw_uturn or cmd.state == "uturn"
            if cmd.abort:
                break
        self.assertTrue(saw_uturn)
        self.assertTrue(cmd.abort)


if __name__ == "__main__":
    unittest.main()
