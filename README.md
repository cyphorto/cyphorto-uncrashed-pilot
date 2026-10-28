# drone-ai-v2

The main, self-contained autonomous drone pilot for Uncrashed (FPV sim).
It watches the game window and drives a virtual Xbox controller through
the Roadtrip race.

Migrated 2026-10-27 from the original `flying drone` project. All flight
code was copied verbatim and hash-verified; no algorithms were rewritten,
no training was reset, and the original project is untouched (V2 no longer
reads it — `tests/test_independence.py` proves this offline).

- [AGENTS.md](AGENTS.md): architecture, commands, modules, rules.
- [PROJECT_STATUS.md](PROJECT_STATUS.md): working pilot, training progress.
- droneai/: sim, control, perception, recovery, training, evaluate, meta, maps.
- versions/: frozen pilots (p2_fast_baseline, p2_overflight_recovery,
  p2_overflight_no_bounce), each complete and hash-verified.
- flightops/: attempt runner + version freezing for V2.
- training_data/: attempt history, human labels, tuning/learning state.
- checkpoints/manifest.json: where learned progress lives.

## Run the tests (no game needed)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s drone-ai-v2/tests
```

## Fly Roadtrip (game must already be open, Roadtrip loaded, tilt 30)

```powershell
powershell -ExecutionPolicy Bypass -File .\drone-ai-v2\start_roadtrip.ps1 -Version p2_overflight_no_bounce -SkipTiltCheck -Label "my flight"
```

## Training / evaluation (offline)

```powershell
cd drone-ai-v2
..\.venv\Scripts\python.exe -m droneai.evaluate train
..\.venv\Scripts\python.exe eval\preflight.py
```

Run from drone-ai-v2/ with `..\.venv\Scripts\python.exe`, or from the
original root as shown. A V2-local `.venv` is used automatically if one
is created in drone-ai-v2/.
