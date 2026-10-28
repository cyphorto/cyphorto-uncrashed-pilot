# BEST: p2_finish_blindcap_v8 (saved 2026-10-27, user's call)

Supersedes p2_finish_blindcap_v7 as best. User watched the run and
reported: perfect run, only 2 slight ground skids on a sharp descent,
no gate/obstacle hits, beating their original finished runs by almost
a minute.

## The run

- Attempt: label "low gate standdown v8" (training_data/runs/train/attempts.jsonl)
- Log: versions/p2_finish_blindcap_v8/logs/20261027_181311_457981_gate_live/log.csv
- 60 gates self-reported, 461.8 s flight, mean 5.67 m/s
- first_damage_s: none; crash_ended: false
- Status field is "error" only because capture timed out after the run
  (TimeoutError: no frame from the game window) — the same capture
  timeout retained on both original confirmed finishes.
- Finish NOT annotation-confirmed in annotations.csv: user report in
  chat is the evidence so far; annotations.csv + Results screen remain
  the formal finish truth.

## What is in it

Everything in p2_finish_blindcap_v7 (the previous best: finisher +
blind guard + cross_hold + sink authority + look_ahead turn brake +
proactive ground detector) plus one change: detector lifts stand down
for a visible gate below the flight line at any size while the drone
is sinking toward it (the gate-47 overflight fix). Config identical
to v7; verified intact with flightops/freeze.py --verify.
