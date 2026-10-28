"""droneai re-exports V2's own copied flight classes (identity within V2,
not a second fork) and layers map settings without mutating caller data."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from droneai import control, perception, recovery, sim


class TestIdentity(unittest.TestCase):
    def test_sim_classes_are_original(self):
        import core.gamepad
        import core.window
        self.assertIs(sim.Gamepad, core.gamepad.Gamepad)
        self.assertIs(sim.WindowCapture, core.window.WindowCapture)

    def test_control_classes_are_original(self):
        import pilot.gate_run
        import pilot.guidance
        self.assertIs(control.GateGuidance, pilot.guidance.GateGuidance)
        self.assertIs(control.GateFlight, pilot.gate_run.GateFlight)

    def test_perception_classes_are_original(self):
        import core.estimator
        import core.gate_detector
        self.assertIs(perception.GateDetector, core.gate_detector.GateDetector)
        self.assertIs(perception.HeightKF, core.estimator.HeightKF)

    def test_recovery_members_are_original(self):
        import core.osd_mode
        import core.safety
        self.assertIs(recovery.Safety, core.safety.Safety)
        self.assertIs(recovery.is_angle, core.osd_mode.is_angle)

    def test_apply_map(self):
        src = {"camera_tilt_deg": 10, "max_gates": 1, "forward_pitch": 0.3}
        out = control.apply_map(src, "roadtrip", "roadtrip_full")
        self.assertEqual(out["camera_tilt_deg"], 30)
        self.assertEqual(out["max_gates"], 99)
        self.assertEqual(out["forward_pitch"], 0.3)
        self.assertEqual(src, {"camera_tilt_deg": 10, "max_gates": 1,
                               "forward_pitch": 0.3})

    def test_runner_argv_points_at_real_runner(self):
        argv = sim.runner_argv("p2_fast_baseline")
        self.assertTrue(Path(argv[-1]).exists())


if __name__ == "__main__":
    unittest.main()
