"""Offline evaluation over fixture records plus human labels."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from droneai import evaluate

FIX = Path(__file__).resolve().parent / "fixtures"


class TestEval(unittest.TestCase):
    def test_fixture_summary(self):
        out = evaluate.summarize_attempts(FIX / "mini_attempts.jsonl",
                                          FIX / "mini_annotations.csv")
        self.assertEqual(out["attempts"], 3)
        self.assertEqual(out["median_gates"], 60)
        self.assertEqual(out["best_gates"], 63)
        self.assertEqual(out["crash_ended"], 1)
        self.assertEqual(out["categories"], {"gate_lost": 1, "error": 2})
        self.assertEqual(out["by_version"]["p2_fast_baseline"]["attempts"], 2)
        self.assertEqual(out["annotations"]["rows"], 3)
        self.assertEqual(out["annotations"]["finished_confirmed"], 2)
        self.assertEqual(out["annotations"]["hits_observed"], 2)

    def test_empty_file(self):
        out = evaluate.summarize_attempts(FIX / "empty.jsonl")
        self.assertEqual(out["attempts"], 0)
        self.assertEqual(out["median_gates"], 0)


if __name__ == "__main__":
    unittest.main()
