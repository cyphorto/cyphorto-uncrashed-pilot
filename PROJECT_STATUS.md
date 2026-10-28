# PROJECT_STATUS.md — drone-ai-v2

## Working pilot (verified 2026-10-27)

- Frozen baseline p2_fast_baseline (parent x7), ANGLE mode, camera tilt 30.
- Flies Roadtrip start to Results screen. Two human-confirmed finishes:
  x7 9:29.874 on 2026-10-26, p2 8:27.545 on 2026-10-27.
- Detection is color HSV (green next gate, magenta later gates). No memorized
  gate positions, routes or waypoints exist in the code.
- Crash handling: OSD mode width + damage icon detection, stuck and ground
  checks, recover/search guidance states, race restart on failure.
- Records: 83 train, 20 valid, 11 baseline, 1 smoke attempt. 12 annotation rows.
  Three train flights added by V2 validation on 2026-10-27 (25/2/32 gates, no finish).

## Training progress (verified 2026-10-27)

- Phase-2 baseline: 4 of 6 required flights collected. No candidate flown yet.
- Local ridge predictor: collecting (3 samples, 1 setting; needs 12 and 6).
- Meta: 9 calls, $0.356 of $5. One phase-1 candidate kept (~8 s faster to
  gate 10). Phase-2 and expert calls produced no flown change. Optional.
- State: hackathon/runs/tune/full_course_learning.json plus feedback.json.
  V2 reads both in place through droneai.training.resume_state().

## Next objectives

1. Fly baseline attempts 5-6 of p2_fast_baseline (needs game + watcher).
2. Annotate finishes and hits in annotations.csv. Judge candidates only on
   confirmed labels.
3. Unlock Canyon per droneai/maps/canyon_heldout.json: stills first, confirm
   10+ gates, verify HSV, then fly canyon_g10.
4. Record game build, FOV, graphics and drone presets (all UNRECORDED).

## V2 relation to the original

- V2 re-exports original classes (identity-tested). Behavior is identical.
- New in V2: map configs, training-state schema checks, offline evaluation,
  Meta live-call refusal, checkpoint manifest, 20 regression tests.
- Live-tested 2026-10-27: three watched flights with V2 map overrides landed
  in attempts.jsonl (25/2/32 gates, no crash ends, no finish). A V2-configured
  finish is still undemonstrated. See eval/roadtrip_20261027_validation.md.
- Monitor live-tested 2026-10-27: one flight (19 gates, operator_kill), manual
  T detected from telemetry and split within seconds, reports in
  eval/roadtrip/. 35 V2 regression tests pass.
- Launcher fixed 2026-10-27 (debug.txt): a PowerShell parser bug made every
  heartbeat age read as raw epoch, so all launcher runs aborted healthy
  runners. Fixed, then flew 23 gates / 195 s end-to-end via start_roadtrip.ps1.
