"""Edge-margin + lighting candidate: branched from the best pilot (v8).

Two changes, both asked for together, nothing else:

1. Turn-entry edge clipping: v8 commits to a crossing when the flight
   path sits inside the gate shrunk by frame_margin=0.20, and inside a
   crossing steers only cross_margin=0.30 (image x) clear of a visible
   side bar. A path near a bar therefore still crosses at full pitch
   and can clip the post on turn entry. This candidate raises both
   margins (0.20 -> 0.30, 0.30 -> 0.40): near a bar it recovers to
   centre first, and in a crossing it steers further from the bar.

2. Gates in different lightings: v8's strict green needs S >= 150 and
   V >= 140, so a gate in shadow/dim light (measured probe: HSV
   60/110/100) is invisible even though its hue is exactly gate green.
   This candidate lowers only the strict S/V floors (150/140 -> 90/80).
   The hue window 55-72 is unchanged, so the green racing line
   (H 41-52) and pale scenery are still excluded, and the relaxed far
   pass is untouched.

Parent is v8 (the proven best), NOT v11: the unflown v9-v11 changes
(faster pitch, gate-51 fix, blind hold) are not in this candidate.
v8 remains best until this one is flown and confirmed.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "versions" / "p2_finish_blindcap_v12"
PARENT = ROOT / "versions" / "p2_finish_blindcap_v8"


def _load(name, path, stubs=None):
    saved = {k: sys.modules.get(k) for k in (stubs or {})}
    sys.modules.update(stubs or {})
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
        def __init__(self, x=0.0, y=0.4, size=0.25, clipped=True, bbox=None):
            self.visible = True
            self.x, self.y, self.size = x, y, size
            self.aspect, self.fill, self.pixels = 2.0, 0.5, 100
            self.corners = [(0, 0)] * 4
            self.bbox = bbox if bbox is not None else [-0.5, -0.2, 0.2, 1.0]
            self.clipped = clipped

    stub.Gate = Gate
    core_pkg = types.ModuleType("core")
    core_pkg.__path__ = []
    mod = _load(f"edge_light_{tag}_guidance", version / "pilot" / "guidance.py",
                {"core": core_pkg, "core.gate_detector": stub})
    return mod, Gate


def cfg_of(path):
    return json.loads((path / "config.json").read_text(encoding="utf-8"))


def frame(hsv, w=640, h=360):
    img = np.zeros((h, w, 3), np.uint8)
    bgr = cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2BGR)[0, 0]
    cv2.rectangle(img, (220, 80), (420, 280), tuple(int(c) for c in bgr), 10)
    return img


class TestEdgeMarginLighting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod, cls.Gate = load_guidance("v12", VERSION)
        cls.parent_mod, _ = load_guidance("v8", PARENT)
        cls.det_mod = _load("edge_light_v12_detector", VERSION / "core" / "gate_detector.py")
        cls.parent_det_mod = _load("edge_light_v8_detector", PARENT / "core" / "gate_detector.py")
        cls.full = cfg_of(VERSION)
        cls.parent_full = cfg_of(PARENT)
        cls.cfg = cls.full["gate_pilot"]
        cls.parent_cfg = cls.parent_full["gate_pilot"]

    # -- config scope -------------------------------------------------
    def test_only_edge_margins_changed_in_config(self):
        changed = {k for k in set(self.cfg) | set(self.parent_cfg)
                   if self.cfg.get(k) != self.parent_cfg.get(k)}
        self.assertEqual(changed, {"frame_margin", "cross_margin"})
        self.assertAlmostEqual(self.cfg["frame_margin"], 0.30)
        self.assertAlmostEqual(self.cfg["cross_margin"], 0.40)
        self.assertAlmostEqual(self.parent_mod.DEFAULTS["frame_margin"], 0.20)
        self.assertAlmostEqual(self.parent_cfg["cross_margin"], 0.30)
        for section, values in self.parent_full.items():
            if section != "gate_pilot":
                self.assertEqual(self.full.get(section), values, section)
        # The unflown v9-v11 changes must not leak in.
        self.assertAlmostEqual(self.cfg["forward_pitch"], 0.70)
        self.assertAlmostEqual(self.cfg["near_pitch"], 0.70)

    # -- turn-entry clipping ------------------------------------------
    def test_near_edge_gate_recovers_instead_of_crossing(self):
        # Path inside the gate at a 20% margin but not at 30%: v8
        # commits to a full-pitch crossing here, v12 centres first.
        for mod, cfg, want in ((self.mod, self.cfg, "recover"),
                               (self.parent_mod, self.parent_cfg, "crossing")):
            g = mod.GateGuidance(cfg)
            cmd = g.update(self.Gate(), 10.0, 0.0, 0.0, 0.0, speed=5.0)
            self.assertEqual(cmd.state, want)
            self.assertFalse(cmd.abort)

    def test_crossing_steers_further_from_visible_bar(self):
        gate = self.Gate(bbox=[-0.1, -0.2, 1.0, 1.0])
        new = self.mod.GateGuidance(self.cfg)._opening_x(gate)
        old = self.parent_mod.GateGuidance(self.parent_cfg)._opening_x(gate)
        self.assertAlmostEqual(old, 0.20)
        self.assertAlmostEqual(new, 0.30)
        self.assertGreater(new, old)

    # -- lighting -------------------------------------------------------
    def test_only_strict_sv_floors_changed(self):
        new, old = self.det_mod.DEFAULTS, self.parent_det_mod.DEFAULTS
        self.assertEqual(new["hsv_low"], [55, 90, 80])
        self.assertEqual(new["hsv_high"], old["hsv_high"])
        for key in old:
            if key != "hsv_low":
                self.assertEqual(new[key], old[key], key)

    def test_dim_gate_now_detected(self):
        det = self.det_mod.GateDetector()
        gate = det.detect(frame((60, 110, 100)))
        self.assertTrue(gate.visible)
        self.assertGreater(gate.size, 0.1)
        parent_gate = self.parent_det_mod.GateDetector().detect(frame((60, 110, 100)))
        self.assertFalse(parent_gate.visible)

    def test_bright_gate_still_detected(self):
        gate = self.det_mod.GateDetector().detect(frame((60, 220, 240)))
        self.assertTrue(gate.visible)

    def test_racing_line_hue_still_rejected(self):
        gate = self.det_mod.GateDetector().detect(frame((47, 220, 240)))
        self.assertFalse(gate.visible)

    def test_very_dim_gate_still_rejected(self):
        gate = self.det_mod.GateDetector().detect(frame((60, 70, 60)))
        self.assertFalse(gate.visible)


if __name__ == "__main__":
    unittest.main()
