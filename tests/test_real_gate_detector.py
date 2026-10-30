import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from real_gate_detector.detector import RealGateDetector, draw_overlay


def _frame_with_gate(colour_bgr=(0, 140, 255)):
    frame = np.zeros((480, 640, 3), np.uint8)
    frame[:] = (90, 90, 90)
    cv2.rectangle(frame, (220, 140), (420, 340), colour_bgr, 14)
    return frame


class TestRealGateDetector(unittest.TestCase):
    def test_detects_orange_gate(self):
        det = RealGateDetector(preset="orange").detect(_frame_with_gate(), 0, 0.0)
        self.assertTrue(det.visible)
        self.assertGreater(det.confidence, 0.3)
        self.assertEqual(len(det.bbox), 4)

    def test_blank_frame_no_gate(self):
        blank = np.full((480, 640, 3), 90, np.uint8)
        det = RealGateDetector(preset="orange").detect(blank, 3, 0.1)
        self.assertFalse(det.visible)

    def test_overlay_changes_frame(self):
        frame = _frame_with_gate()
        det = RealGateDetector(preset="auto").detect(frame, 0, 0.0)
        self.assertFalse(np.array_equal(frame, draw_overlay(frame, det)))


if __name__ == "__main__":
    unittest.main()
