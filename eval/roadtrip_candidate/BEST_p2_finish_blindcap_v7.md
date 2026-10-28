# BEST: p2_finish_blindcap_v7 (saved 2026-10-27, user's call)

Best attempt so far — better than the original confirmed finishes
(p2_fast_baseline 8:27, p2_overflight_no_bounce 9:13) per the user who
watched it: it hit nothing at all.

## The run

- Attempt: label "no ground v7", started 2026-10-27 (see
  training_data/runs/train/attempts.jsonl, latest p2_finish_blindcap_v7 row)
- Log: versions/p2_finish_blindcap_v7/logs/20261027_180059_637801_gate_live/log.csv
- 46 gates self-reported, 362.0 s flight, mean 5.48 m/s
- first_damage_s: none; crash_ended: false — no gate, ground, or obstacle contact
- Ended "next gate lost" after flying over the last gate it reached
  (gate 47 by pilot count). Finish NOT confirmed: gate counts alone are
  not finishes (annotations.csv + game Results screen are the truth),
  and no annotation row exists for this attempt yet.

## What is in it

Proven finisher (p2_overflight_no_bounce) lineage plus, in order:
blind-crossing reacquire guard, cross_hold centre pursuit, crossing
climb centre-target capped +1 with 4.5 sink authority, look_ahead
next-gate detection with turn brake, and the proactive camera ground
detector (ground_warn=1, floor at ground+1.5 m, gate wins near a low
gate, no pitch cap from detector readings, floor held through
crossings). Verified intact with flightops/freeze.py --verify.

## Remaining known issue

Flew over the last gate reached. If this is ever patched, it is one
change on top of THIS version, judged from that flight's log — the
series history (v1-v6 of both lineages) shows stacked changes regress.
