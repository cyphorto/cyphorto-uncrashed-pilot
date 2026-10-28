"""Blind-hold candidate: on candidate v10, guidance must not declare
the next gate lost while ALT is unreadable.

Flight 20261028_104659 (v10) passed 5 gates cleanly, then the game
was paused (the pilot's own view frames show the session map open)
on the approach to gate 6. ALT and the gate vanished from the frame
together; guidance went lost -> search and aborted "next gate lost"
6 s later, ending a healthy run, even though the flight loop
already tolerates ALT-blind steering for far longer
(BLIND_FLY_S/BLIND_MAX_S in hover_test.py) and owns the blind
timeout. This candidate holds "lost" while blind and never starts
the search clock; the loop's blind handling decides if the dropout
is real. Config is identical to v10; only the lost-gate branch of
guidance changes. A genuine (not blind) lost gate still aborts on
the same schedule as before.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v11"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v10"


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
        def __init__(self, x=0.0, y=0.3, size=0.10, clipped=False, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.1, 0.1, 0.1, 0.5)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load(f"blind_hold_{tag}_guidance",
                version / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))


class TestBlindHold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance("v11", VERSION)
        cls.parent_mod, _ = load_guidance("v10", PARENT)
        cls.full = cfg_of(VERSION)
        cls.parent_full = cfg_of(PARENT)
        cls.cfg = cls.full["gate_pilot"]

    def test_config_identical_to_v10(self):
        self.assertEqual(self.full, self.parent_full)
        self.assertAlmostEqual(self.cfg["forward_pitch"], 0.74)

    def _approach(self, mod, cfg, seconds=2.0):
        g = mod.GateGuidance(cfg)
        gate = self.Gate()
        cmd, t = None, 0.0
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=7.0)
        self.assertFalse(cmd.abort)
        return g, t

    def _blind_dropout(self, g, t, seconds, blind=True):
        cmd = None
        for _ in range(int(seconds / 0.05)):
            t += 0.05
            cmd = g.update(None, 10.0, 0.0, t, t, speed=None, blind=blind)
            if cmd.abort:
                break
        return cmd, t

    def test_blind_no_gate_holds_past_search_timeout(self):
        g, t = self._approach(self.mod, self.cfg)
        cmd, t = self._blind_dropout(g, t, 10.0)
        self.assertFalse(cmd.abort)
        self.assertEqual(cmd.state, "lost")
        # Unpause: the gate is back and the approach resumes.
        gate = self.Gate()
        for _ in range(20):
            t += 0.05
            cmd = g.update(gate, 10.0, 0.0, t, t, speed=7.0)
        self.assertFalse(cmd.abort)
        self.assertIn(cmd.state, ("approach", "align", "acquiring"))

    def test_parent_v10_aborted_blind(self):
        # The failure being fixed, reproduced on the parent's code.
        g, t = self._approach(self.parent_mod,
                              self.parent_full["gate_pilot"])
        cmd, _ = self._blind_dropout(g, t, 10.0)
        self.assertEqual(cmd.state, "aborted")
        self.assertIn("next gate lost", cmd.abort)

    def test_real_lost_gate_still_aborts(self):
        g, t = self._approach(self.mod, self.cfg)
        cmd, _ = self._blind_dropout(g, t, 10.0, blind=False)
        self.assertEqual(cmd.state, "aborted")
        self.assertIn("next gate lost", cmd.abort)


if __name__ == "__main__":
    unittest.main()
