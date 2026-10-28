# p2_overflight_recovery evaluation — 2026-10-27 (flightfix.txt)

Candidate ready and unit-verified. Simulator flights NOT run: at flight time
`tools/game.py status` reported `{"running": false}` (single check, no
relaunch attempted per standing rules). No before/after flight comparison is
claimed. Do not promote.

## Root causes (evidence)

### A. Overflight — confirmed
Across 7 full-course flights (4 baseline + 3 `p2_side_glimpse`, same code
paths), the dominant killer is the crossed gate exiting the frame with no
next gate found:

- Monitor reports (`eval/roadtrip*/*.md`): last-seen gate y 0.886–0.967
  (bottom of frame) in the 11- and 30-gate flights; end speeds 8.8–9.9 m/s;
  class `no_next_gate_after_crossing` / `gate_lost_moving`.
- `p2_fast_baseline/pilot/guidance.py` `_cross`: after the gate vanishes it
  flies straight at full cruise pitch for `cross_timeout_s` (blind), then
  aborts `no next gate after crossing`. No reacquisition is attempted.
- Near gates low in the frame: pursuit sink is capped, so at cruise pitch
  the drone reaches the gate before sinking to it and passes over it.

Hypothesis (not separately proven): some counted passes are overflights
that happened to find the next gate; the fix does not count a reacquired
gate as passed, so this stays visible in telemetry if it occurs.

### B. Ground bouncing — confirmed mechanism, frequency unquantified
- Baseline `config.json`: `bounce_ground=0`. The bounce detector in
  `pilot/hover_test.py:254` (upward jolt with throttle cut) therefore never
  calls `ground_contact`; only a full stop (`_on_ground`) sets the floor.
- Baseline `ground_contact` set a fixed +1.5 m floor for 4 s with no pitch
  limit: the pilot could pitch straight back into the ground at cruise
  pitch, and repeated contacts had no escalation or bound.
- Damage onsets 0–4 per flight and 2–21 recovery episodes (monitor
  `summary.csv`) show contact/recovery cycles are common, but no log
  isolates a pure bounce loop; frequency is NOT quantified.

## Changes (only `hackathon/versions/p2_overflight_recovery/`)

Parent `p2_fast_baseline`, baseline untouched. Only `pilot/guidance.py`
differs, plus `config.json`: `gate_pilot.bounce_ground` 0 → 1.

1. Crossing reacquire (`reacquire_s=5.0`, `reacquire_brake_s=0.7`):
   on crossing timeout — or immediately when the crossed gate exits the
   bottom past peak size (y > 0.85, size < 0.6 × peak) — brake (pitch 0),
   then search toward the last sighting (`_reacquire`) for up to 5 s.
   A gate back in view is approached normally. The missed gate is NOT
   counted as a pass. Still blind after 5 s: abort
   `no next gate after crossing (reacquire failed)`.
2. Vertical brake (`vert_brake=1`): a near gate well below the level line
   scales pitch down in proportion to the vertical error, so the pursuit
   sink can catch up instead of the gate exiting the bottom.
3. Ground stabilization: while the post-contact floor is active, forward
   pitch is capped at `ground_pitch=0.12`; each repeat contact inside
   `ground_window_s=30` raises clearance ×1.5 steps; the 4th contact
   (`ground_max_contacts=4`) aborts with
   `repeated ground contact: unable to stay airborne` (bounded, diagnosable).

No Roadtrip-specific coordinates, gate numbers, or routes. All triggers
use image position/size, speed-independent state, and ALT-relative floors.

## Regression tests

[hackathon/tests/test_overflight_recovery.py](../../hackathon/tests/test_overflight_recovery.py)
(9 tests, kept with the project):

- both frozen versions hash-intact;
- candidate byte-identical commands to baseline with no triggers;
- crossing timeout: baseline aborts, candidate brakes → `reacquire_search`
  → bounded abort, pass uncounted;
- bottom-exit (y 0.9, past peak) starts reacquire immediately;
- a reacquired gate is approached again, not aborted;
- `reacquire_s=0` restores the exact baseline abort;
- vertical brake lowers pitch for a near low gate, unchanged when centred;
- ground contact caps pitch, repeat contact escalates the floor;
- 4 contacts in 30 s abort bounded; spaced contacts do not accumulate.

Suites (2026-10-27, this session): hackathon 94/94, root 86/86, V2 35/35.

## Flights

None. Game window not detected (see header). Baseline reference range
remains 25/2/32/23 gates plus the x7 63-gate finish; candidate range: none.

## Verdict

- Roadtrip completed by candidate: no flight attempted.
- Promote candidate: NO. No flight evidence; a gate count alone would not
  prove improvement anyway (baseline variance 2–63 on identical code).
- Next step: with Uncrashed open on Roadtrip, run up to 3 attempts via
  `start_roadtrip.ps1 -Version p2_overflight_recovery` (adapts only the
  version selection), review each log before the next, and record
  overflight/reacquire/ground-contact counts from the monitor. Then
  compare against the baseline range above. Canyon stays locked; no
  Canyon work in this task.
