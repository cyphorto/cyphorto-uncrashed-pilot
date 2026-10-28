# AGENTS.md — drone-ai-v2

## What this is

The main, self-contained drone project. It flies Uncrashed (FPV sim) through
the Roadtrip race by watching the game and driving a virtual Xbox controller.

Migrated 2026-10-27 from the original `flying drone` folder. Flight code was
copied verbatim (hash-verified against each frozen version's `version.json`);
the original project is untouched and is no longer read by anything here.
No flight algorithms were rewritten.

## Layout

- droneai/sim.py: capture, pad, runner entry. Start here for flights.
- droneai/control.py: GateGuidance, Flight, GateFlight, apply_map().
- droneai/perception.py: GateDetector, AltReader, HeightKF. No obstacle
  detector exists; see NO_OBSTACLE_DETECTOR.
- droneai/recovery.py: mode width, damage icon, Safety, RECOVERY_CHAIN.
- droneai/training.py: read-only resume_state(), attempt counts (local data).
- droneai/evaluate.py: offline attempts.jsonl + annotations summary.
- droneai/meta.py: offline ledger readers. Live calls refused by design.
- droneai/monitor.py: live log tail, T-reset splits, per-attempt diagnosis
  to eval/roadtrip/ plus summary.csv. Start it before the runner.
- droneai/maps/*.json: map configs. roadtrip active, canyon_heldout locked.
- core/, pilot/, tools/: the working flight stack (workspace copy).
- versions/: frozen pilots, each self-contained and hash-verified:
  p2_fast_baseline, p2_overflight_recovery, p2_overflight_no_bounce
  (the last is p2_overflight_recovery with the false-positive bounce
  detector off; see eval/overflight_recovery_20261027.md).
- flightops/: attempts.py, freeze.py, common.py, outcome.py (V2 paths).
- training_data/: protocol.json, runs/<split>/attempts.jsonl,
  runs/annotations.csv, runs/tune/*.json, meta/ ledger + feedback.
- checkpoints/manifest.json: where learned progress lives (local paths).
- start_roadtrip.ps1: one-command Roadtrip launcher (runs from here).
- tests/: regression tests, including test_independence.py.

## Commands

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s drone-ai-v2/tests
cd drone-ai-v2
..\.venv\Scripts\python.exe -m droneai.evaluate train
..\.venv\Scripts\python.exe eval\preflight.py
..\.venv\Scripts\python.exe -m droneai.monitor --version p2_fast_baseline
```

All commands below run from the original project root unless noted. The
interpreter is the original root `.venv` until a V2-local `.venv` exists;
`droneai.sim.runner_argv` and `start_roadtrip.ps1` prefer `drone-ai-v2/.venv`
when present. That venv is an external dependency, not project code.

Fly a frozen version (needs the game open + user watching):

```powershell
powershell -ExecutionPolicy Bypass -File .\drone-ai-v2\start_roadtrip.ps1 -Version p2_overflight_no_bounce -SkipTiltCheck -Label "my flight"
```

Or manually, from drone-ai-v2/:

```powershell
..\.venv\Scripts\python.exe -u versions\p2_fast_baseline\pilot\runner.py
..\.venv\Scripts\python.exe flightops\attempts.py run --version p2_fast_baseline --course roadtrip_full --split train --n 1
```

Freeze a new version (never overwrite an existing one):

```powershell
.\.venv\Scripts\python.exe drone-ai-v2\flightops\freeze.py <name> --parent <version> --set gate_pilot.<key>=<value> --desc "..."
.\.venv\Scripts\python.exe drone-ai-v2\flightops\freeze.py --verify <name>
```

## Rules

- NEVER launch Uncrashed through Steam during a task. NEVER create another
  game instance. The user opens Uncrashed with Roadtrip loaded; reuse that
  existing window only.
- Use the V2 `start_roadtrip.ps1` launcher for simulator tests. Do not modify
  it unless a specific defect has been demonstrated.
- If the game window cannot be detected, report that once and stop flight
  work. Do not retry, relaunch, or repeatedly poll for it.
- Do offline analysis and code changes first. Only run simulator tests when
  the candidate is ready and its automated tests pass.
- Never edit a frozen version in place. Freeze a new one with flightops.
- Finish truth is annotations.csv plus the game Results screen. Gate counts
  alone are never finishes.
- One controller owner at a time. Never start a second runner or pad writer.
- No Meta calls from V2. No keys in files. Dry-run estimates only.
- Canyon is locked until its checklist in canyon_heldout.json is done.
- The original `flying drone` tree is read-only reference now. Do not make
  V2 depend on it again; test_independence.py guards this.

## Do not ingest (heavy paths)

- versions/*/logs/, versions/*/results/, versions/*/jobs/
- training_data/runs/*/attempts.jsonl (summarize with droneai.evaluate)
- data/recordings/, data/alt_templates/, data/speed_templates/
- .venv/, __pycache__/, *.pyc
