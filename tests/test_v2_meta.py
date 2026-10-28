"""Meta stays optional: V2 refuses live calls, the ledger balances, and the
flight path imports no Meta code."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from droneai import _roots, meta

MARKERS = ("meta_client", "MODEL_API_KEY", "learning.py", "propose.py")


class TestMetaOptional(unittest.TestCase):
    def test_live_refused_by_default(self):
        os.environ.pop(meta.ALLOW_ENV, None)
        with self.assertRaises(RuntimeError):
            meta.request_live()

    def test_live_never_from_v2(self):
        os.environ[meta.ALLOW_ENV] = "1"
        try:
            with self.assertRaises(RuntimeError):
                meta.request_live()
        finally:
            del os.environ[meta.ALLOW_ENV]

    def test_ledger_balances(self):
        totals = meta.ledger_totals()
        lines = [l for l in meta.LEDGER.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        self.assertEqual(totals["calls"], len(lines))
        self.assertGreater(totals["calls"], 0)
        self.assertGreater(totals["spent_usd"], 0)
        self.assertTrue(totals["within_budget"])

    def test_flight_path_has_no_meta_imports(self):
        roots = [_roots.V2_ROOT / "pilot", _roots.V2_ROOT / "core",
                _roots.V2_ROOT / "flightops/attempts.py"]
        hits = []
        for root in roots:
            files = [root] if root.is_file() else sorted(root.glob("*.py"))
            for f in files:
                text = f.read_text(encoding="utf-8")
                for m in MARKERS:
                    if m in text:
                        hits.append(f"{f.name}: {m}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
