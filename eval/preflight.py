"""V2 preflight check for Roadtrip validation.

Offline except for game-window and runner-heartbeat presence checks. Exit 0
means ready to fly, 1 means a blocker is printed below. Changes nothing.
"""
import json
import sys
import time
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT))

from droneai import control, maps, meta, perception, recovery, sim, training

failures = []


def check(name, ok, detail=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        failures.append(name)


check("control.GateGuidance", control.GateGuidance.__name__ == "GateGuidance",
      control.GateGuidance.__module__)
check("control.GateFlight", control.GateFlight.__name__ == "GateFlight",
      control.GateFlight.__module__)
check("perception.GateDetector", perception.GateDetector.__name__ == "GateDetector",
      perception.GateDetector.__module__)
check("recovery.Safety", recovery.Safety.__name__ == "Safety",
      recovery.Safety.__module__)
check("sim.Gamepad", sim.Gamepad.__name__ == "Gamepad", sim.Gamepad.__module__)

st = training.resume_state()
check("training.resume_state", True,
      f"{st['version']} baseline {st['baseline_collected']}/{st['baseline_required']} "
      f"ridge={st['ridge_status']} train={st['attempts']['train']}")

ov = maps.to_overrides("roadtrip", "roadtrip_full")
check("roadtrip overrides", ov == ["gate_pilot.camera_tilt_deg=30", "gate_pilot.max_gates=99"],
      ",".join(ov))

p2cfg = json.loads((V2_ROOT / "versions/p2_fast_baseline/config.json")
                   .read_text(encoding="utf-8"))
gp = p2cfg["gate_pilot"]
check("p2 frozen config matches V2 map",
      gp["camera_tilt_deg"] == 30 and gp["max_gates"] == 99,
      f"tilt={gp['camera_tilt_deg']} max_gates={gp['max_gates']}")

t = meta.ledger_totals()
check("meta ledger offline", t["within_budget"],
      f"{t['calls']} calls ${t['spent_usd']}/${t['budget_usd']}")
try:
    meta.request_live()
    check("meta live refused", False)
except RuntimeError:
    check("meta live refused", True)

hwnd = sim.find_game_window()
check("game window", bool(hwnd), "Uncrashed not running" if not hwnd else "found")

vroot = V2_ROOT / "versions/p2_fast_baseline"
beat_p = vroot / "results/_runner.json"
alive, age = False, None
if beat_p.exists():
    try:
        beat = json.loads(beat_p.read_text(encoding="utf-8"))
        age = time.time() - beat.get("time", 0)
        alive = age < 5
    except (OSError, ValueError):
        pass
jobs = [p.name for p in (vroot / "jobs").iterdir()] if (vroot / "jobs").exists() else []
check("p2 runner alive and idle", alive and not jobs,
      f"alive={alive} age={age} queued_jobs={jobs}")

sys.exit(1 if failures else 0)
