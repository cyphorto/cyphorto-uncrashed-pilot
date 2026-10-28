"""Training state loads and every checkpoint manifest path exists, so V2 can
resume learning in place. Asserts schema, not exact counts, because flights
keep appending."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from droneai import _roots, training


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)


class TestTrainingState(unittest.TestCase):
    def test_resume_state_schema(self):
        st = training.resume_state()
        self.assertTrue(st["version"])
        self.assertGreaterEqual(st["baseline_required"], 1)
        self.assertGreaterEqual(st["baseline_collected"], 0)
        self.assertIn(st["ridge_status"], ("collecting", "fitted"))
        self.assertEqual(set(st["attempts"]), set(training.SPLITS))
        for n in st["attempts"].values():
            self.assertIsInstance(n, int)
            self.assertGreaterEqual(n, 0)

    def test_unknown_split(self):
        with self.assertRaises(ValueError):
            training.attempts_path("nope")

    def test_manifest_paths_exist(self):
        manifest = json.loads((_roots.V2_ROOT / "checkpoints/manifest.json")
                              .read_text(encoding="utf-8"))
        checked = 0
        for value in _walk_strings(manifest):
            if "/" in value and not value.startswith(("collecting",)):
                self.assertTrue((_roots.V2_ROOT / value).exists(), value)
                self.assertFalse(value.startswith("hackathon/"), value)
                checked += 1
        self.assertGreater(checked, 5)


if __name__ == "__main__":
    unittest.main()
