"""Recover stand-down candidate: on the faster pilot (v9, cruise
pitch 0.74), a low gate being sunk toward in recover must not be
lifted over by the ground detector.

Flight 20261028_101958 (v9) passed 50 gates, then missed gate 51
over the top. After the pass the gate sat low (y 0.68-0.90), the
approach sank at up to -3.9 m/s, then the clipped gate entered
recover - where recover sank at -0.7 m/s but the post-update
detector lift in update() replaced that with +0.7 on every frame
with a hillside ground reading under 1.5 m. The sink was cancelled
for over a second, the gate left the bottom of the frame, and the
run ended. The lift survived because update() checked
_low_gate_ahead(gate) without the velocity that _update() itself
passes: with the attitude lagged, the centre error sat just under
alignment_y, so only the sinking-velocity branch identified the
gate - and the wrapper never saw it. This candidate passes the
velocity through, completing the v8 stand-down in recover. Config
(including the 0.74 cruise pitch) is identical to v9; one line of
guidance changes.

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
VERSION = ROOT / "versions" / "p2_finish_blindcap_v10"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v9"


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
        def __init__(self, x=0.0, y=0.0, size=0.40, clipped=True, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else (-0.4, -0.5, 0.4, 1.0)
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load(f"recover_standdown_{tag}_guidance",
                version / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))


class TestRecoverStanddown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance("v10", VERSION)
        cls.parent_mod, _ = load_guidance("v9", PARENT)
        cls.full = cfg_of(VERSION)
        cls.parent_full = cfg_of(PARENT)
        cls.cfg = cls.full["gate_pilot"]

    def test_config_identical_to_v9_speed_kept(self):
        self.assertEqual(self.full, self.parent_full)
        self.assertAlmostEqual(self.cfg["forward_pitch"], 0.74)
        self.assertAlmostEqual(self.cfg["near_pitch"], 0.74)

    def _gate51_recover(self, mod, cfg, velocity):
        # Gate 51 at recover entry in flight 20261028_101958: clipped,
        # x -0.101, y 0.676, size 0.2449, attitude faded to 0.35,
        # hillside ground reading 1.47 m.
        g = mod.GateGuidance(cfg)
        g.pitch_att = 0.35
        gate = self.Gate(x=-0.101, y=0.676, size=0.2449, clipped=True,
                         bbox=(-0.25, 0.50, 0.05, 0.80))
        cmd = g.update(gate, -11.85, velocity, 1.0, 1.0,
                       speed=9.0, ground_h=1.47)
        return g, cmd

    def test_gate51_recover_keeps_sinking(self):
        g, cmd = self._gate51_recover(self.mod, self.cfg, velocity=-3.3)
        self.assertEqual(cmd.state, "recover")
        self.assertAlmostEqual(cmd.climb, -g.cfg["recover_rate"])

    def test_parent_v9_lifted_here(self):
        # The failure being fixed, reproduced on the parent's code.
        _, cmd = self._gate51_recover(self.parent_mod,
                                      self.parent_full["gate_pilot"],
                                      velocity=-3.3)
        self.assertEqual(cmd.state, "recover")
        self.assertAlmostEqual(cmd.climb, 0.7)

    def test_same_gate_not_sinking_still_protects(self):
        _, cmd = self._gate51_recover(self.mod, self.cfg, velocity=1.0)
        self.assertAlmostEqual(cmd.climb, 0.7)


if __name__ == "__main__":
    unittest.main()
