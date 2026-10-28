# V2 Roadtrip flight validation — 2026-10-27

Three live flights on the user's open Uncrashed session. No Meta calls. No
flight-code changes. No training reset.

## Verdict: partial

- Control the drone: PASS. Takeover and liftoff in all 3 flights.
- Navigate Roadtrip autonomously: PASS. Up to 32 self-counted gates.
- Complete the race: FAIL. No Results screen in 3 attempts. Best run ended
  "no next gate after crossing" at gate 32.
- Preserve recovery and training state: PASS. Flew on after hits, no crash
  ends, frozen tree hash-verified per attempt, history append-only.

## Launch commands

```powershell
.\.venv\Scripts\python.exe drone-ai-v2/eval/preflight.py
.\.venv\Scripts\python.exe tools/game.py status
.\.venv\Scripts\python.exe tools/game.py shot --scale 0.5
.\.venv\Scripts\python.exe tools/game.py key DOWN   # tilt probe, then UP to restore
.\.venv\Scripts\python.exe -u hackathon/versions/p2_fast_baseline/pilot/runner.py
.\.venv\Scripts\python.exe hackathon/attempts.py run --version p2_fast_baseline --course roadtrip_full --split train --n 1 --set gate_pilot.camera_tilt_deg=30 --set gate_pilot.max_gates=99 --label "V2 roadtrip validation attempt N"
```

Game-touching commands ran with user-approved sandbox escalation: the managed
sandbox cannot see desktop windows (diagnosed: zero MainWindowHandles), so
capture, keys and the virtual pad need unsandboxed runs. No code fix involved.

## Configuration and checkpoint

- Version p2_fast_baseline, tree 02da8965de99 (hash re-verified by attempts.py
  before every flight).
- V2 map roadtrip/roadtrip_full issued tilt 30 + max_gates 99, identical to the
  frozen config values, so V2 and the original flew the same settings.
- Game verified before flight: Roadtrip at start pad, Time 0:00, ALT 0.0 m,
  sticks centered, client 1920x1080, tilt probe reads 30 (shot
  logs/shots/20261027_111150.png). Runner forced ACRO to ANGLE per job.

## Per-attempt results

| # | attempt_id | gates | time | end | crash | hit at | flew on after hit |
|---|------------|-------|------|-----|-------|--------|-------------------|
| 1 | 20261027_111255_4dab_01 | 25 | 225.6 s | no_next_gate | no | 218.0 s | 8 s |
| 2 | 20261027_112005_ec38_01 | 2 | 44.5 s | no_next_gate | no | 28.0 s | 16 s |
| 3 | 20261027_112447_6320_01 | 32 | 299.5 s | no_next_gate | no | 83.0 s | 216 s, ~24 more gates |

Mean speed 5.1-5.3 m/s. Gate visibility 79-96%. No stuck events, no
crash-ended flights. All three ended by losing the next gate after a
crossing, the known p2 failure mode, not by a V2 integration fault.

## Logs and records

- Attempt records: hackathon/runs/train/attempts.jsonl (train 80 -> 83).
- Flight logs: hackathon/versions/p2_fast_baseline/logs/20261027_111300_224962_gate_live,
  .../20261027_112009_256646_gate_live, .../20261027_112450_910559_gate_live
  (log.csv per tick, view/ frames at 15 Hz).
- Game shots: logs/shots/20261027_111125.png (start pad), 20261027_111150.png (Tilt : 30).

## Recovery behavior

Attempt 3 is the evidence: damage icon at 83 s, then 216 s and roughly 24
more gates before the run ended by gate loss. The hit did not end the flight
and no stuck or crash logic triggered falsely. No recovery-code differences
between V2 and the original exist: V2 re-exports the same classes.

## Training-state effect

The three flights are legitimate phase-2 baseline material (same frozen
version/hash, full course, 30-degree tilt, labeled). The next
`learning.py report` will ingest them toward the 6-baseline requirement.
Feedback and coordinator state were read, never written, during validation.

## Fixes made

None to flight code, config or data. Environment only: sandbox escalation
for desktop access (above).

## What remains

- A V2-configured finish still needs demonstrating. Attempt more baseline
  flights, or judge candidates once human labels land in annotations.csv.
- Human labels needed for these 3 flights: finish no/no/no, hits observed
  (damage icon proves at least 1 each; exact counts need frame review).
