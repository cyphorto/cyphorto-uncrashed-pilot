"""Map configs: roadtrip active, canyon locked, overrides pure."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from droneai import maps


class TestMaps(unittest.TestCase):
    def test_available(self):
        names = maps.available()
        self.assertIn("roadtrip", names)
        self.assertIn("canyon_heldout", names)

    def test_roadtrip_full_overrides(self):
        self.assertEqual(maps.to_overrides("roadtrip", "roadtrip_full"),
                         ["gate_pilot.camera_tilt_deg=30", "gate_pilot.max_gates=99"])

    def test_roadtrip_g10_overrides(self):
        self.assertEqual(maps.to_overrides("roadtrip", "roadtrip_g10"),
                         ["gate_pilot.camera_tilt_deg=30", "gate_pilot.max_gates=10"])

    def test_canyon_locked(self):
        with self.assertRaises(ValueError):
            maps.assert_unlocked("canyon_heldout")
        with self.assertRaises(ValueError):
            maps.to_overrides("canyon_heldout", "canyon_g10")

    def test_unknown_map_and_course(self):
        with self.assertRaises(ValueError):
            maps.load_map("nope")
        with self.assertRaises(ValueError):
            maps.course("roadtrip", "nope")


if __name__ == "__main__":
    unittest.main()
