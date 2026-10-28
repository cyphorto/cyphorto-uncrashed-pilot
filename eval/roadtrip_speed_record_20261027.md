# Roadtrip speed-record audit — 2026-10-27

Status: blocked before flight. No new finish, promotion, or algorithm change.
Simulator attempts in this task: 0 of the initial maximum of 10.

## Record and baseline

The fastest historical human-confirmed finish in `training_data/runs/annotations.csv`
is **8:27.545 (507.545 seconds)**, attempt `20261027_095806_8743_01`,
version `p2_fast_baseline`. The earlier x7 finish was 9:29.874.
The annotations describe Results-screen confirmation; the screenshots at the
recorded `logs/shots/batch-error.png` and `logs/shots/20261026_203322.png`
paths are absent in V2. This audit did not independently inspect those screens.
The raw `error` category is retained: capture stopped on the Results screen.

Champion metrics: 60 self-reported gates; actual gate total, crashes, successful
recoveries, average speed and peak speed are unverified. These values must not
be substituted with zero. No new baseline flight was possible.

Champion code and configuration: `versions/p2_fast_baseline/`, particularly
`pilot/guidance.py`, `pilot/gate_run.py`, and `config.json`.
Tree SHA-256: `02da8965de99b21d3d44e3a62167b97ccbcc7150b1b693275e1b667d219e1583`.
Key settings: ANGLE mode, camera tilt 30 degrees, forward/near pitch 0.7,
pursuit_up 1.3, pursuit_down 0.85, bounce_ground 0, max_gates 99.
The V2 Roadtrip overrides match the frozen tilt and max_gates settings.
Game FOV, graphics, build and drone preset remain unrecorded.

## System and preservation

- `droneai/sim.py` exposes local capture/controller interfaces and runner paths.
  `core/window.py` captures the existing game window; `core/gamepad.py` drives
  a virtual Xbox controller. `pilot/runner.py` owns that controller.
- Gate guidance, HSV gate detection, altitude estimation and recovery are
  implemented in the local `pilot/` and `core/` trees and exposed by `droneai/`.
- `start_roadtrip.ps1` starts monitoring first, checks controller ownership,
  runs one logged attempt, and shuts down. It was not modified.
- `droneai.training.resume_state()` reads V2-local records and JSON training
  state. There are 90 train, 20 valid, 11 baseline and 1 smoke attempts.
  Phase-2 baseline collection is 4/6. Ridge state has 3 samples and 1 distinct
  setting, still collecting; no fitted model weights exist to preserve.
- `checkpoints/manifest.json` identifies the local checkpoint and feedback files.
  No training progress, annotation, frozen controller or original project was changed.
- All three frozen versions pass `flightops.freeze.verify`: p2_fast_baseline,
  p2_overflight_recovery, p2_overflight_no_bounce.

## Blockers and validation

One process check found no running Uncrashed process. Flight work stopped;
the game was not launched and its presence was not polled again.

Neither `.venv/Scripts/python.exe` nor `../.venv/Scripts/python.exe` exists
at this moved workspace. Those are the launcher's interpreter paths. The
`python` command is an inactive Microsoft Store alias. The old project was
not used as a fallback.

Using Codex's bundled Python for offline evaluation only:
`python -m unittest discover -s tests` ran 36 tests: 32 passed, 3 errored and
1 failed. All four unsuccessful cases encounter missing `cv2` (OpenCV),
including the independence subprocess. Thus full runtime independence is
not established by this audit, although frozen hashes and local state pass.
`python -m droneai.evaluate train` and `resume_state()` both succeeded.
The source/data are local; the runnable simulator environment is incomplete.

## Evidence-based next experiment

Existing reports identify missed low gates followed by blind forward flight as
the dominant loss mechanism. The already-frozen `p2_overflight_no_bounce`
candidate adds vertical braking, bounded gate reacquisition and post-contact
pitch limiting while disabling the false-positive bounce trigger. It has no
verified finish and is not promoted.

The older overflight report's claim of zero candidate flights is stale:
current evaluation contains two p2_overflight_recovery attempts (median 1.5
self-reported gates). Their monitor reports show 1/2 gates, 26.6/38.0 seconds,
and a gate still visible at termination. This is not evidence of improvement.
Monitor recovery episodes and damage-icon onsets are proxies, not verified
successful recoveries or crash counts.

First restore a V2-local Python environment with the project's capture, vision
and controller dependencies and pass the full tests. Then, with the user-opened
Roadtrip session and camera tilt 30 confirmed, reproduce the baseline before
testing the existing candidate. From this workspace the launcher command is:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_roadtrip.ps1 -Version p2_fast_baseline -SkipTiltCheck -Label "speed-record baseline"
```

Use `-SkipTiltCheck` only after tilt is confirmed. Each launcher invocation is
one attempt; inspect its monitor report and preserve the Results screen before
another attempt. Append each attempt to `eval/roadtrip_speed_leaderboard.csv`;
blank metrics mean unknown. A higher gate count cannot establish a finish.

Best new verified time and percentage improvement: not available. Overflight
and ground-bounce improvement: unmeasured. The champion remains unchanged.
