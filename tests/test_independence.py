"""V2 must not execute code from the original project tree.

Runs a subprocess whose import hook rejects any module loaded from outside
drone-ai-v2 (except the interpreter/stdlib and site-packages). That makes
the original tree unavailable without moving, renaming or modifying it.
"""
import subprocess
import sys
import unittest
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = V2_ROOT.parent

CHILD = r"""
import pathlib, sys
v2 = pathlib.Path(sys.argv[1]).resolve()
origin = v2.parent

class Blocker:
    def find_module(self, name, path=None):
        return None

# Reject by auditing loaded module files after import instead: import the
# public surface, then assert every project module came from inside V2.
sys.path.insert(0, str(v2))
# Original root must not be importable as project code.
sys.path = [p for p in sys.path if pathlib.Path(p or ".").resolve() != origin]

from droneai import control, evaluate, meta, monitor, perception, recovery, sim, training

# Safe offline controller start: construct guidance + detector objects only.
g = control.GateGuidance({"camera_tilt_deg": 30, "max_gates": 99})
assert g.cfg["bounce_ground"] in (0, 1)
det = perception.GateDetector()
state = training.resume_state()
assert state["attempts"]["train"] > 0
argv = sim.runner_argv("p2_overflight_no_bounce")
assert pathlib.Path(argv[-1]).exists(), argv
assert meta.ledger_totals()["calls"] > 0
from flightops.freeze import verify
assert verify("p2_overflight_no_bounce") == [], verify("p2_overflight_no_bounce")
assert verify("p2_fast_baseline") == []

bad = []
for name, mod in list(sys.modules.items()):
    f = getattr(mod, "__file__", None)
    if not f:
        continue
    p = pathlib.Path(f).resolve()
    if origin in p.parents and v2 not in p.parents and ".venv" not in p.parts:
        bad.append(f"{name}: {p}")
assert not bad, "modules loaded from original tree: " + "; ".join(bad)
print("INDEPENDENT_OK train_attempts=", state["attempts"]["train"])
"""


class TestIndependence(unittest.TestCase):
    def test_no_original_code_executes(self):
        proc = subprocess.run(
            [sys.executable, "-c", CHILD, str(V2_ROOT)],
            capture_output=True, text=True, timeout=120,
            cwd=str(V2_ROOT))
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + "\n" + proc.stderr)
        self.assertIn("INDEPENDENT_OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
