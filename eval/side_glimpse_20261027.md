# p2_side_glimpse evaluation — 2026-10-27 (gate.txt)

One targeted navigation change, tested against the frozen p2_fast_baseline
under equivalent conditions (roadtrip_full, train, tilt 30, max_gates 99).

## The change

`p2_side_glimpse` (parent `p2_fast_baseline`, tree `4f21e0550240`) differs by
one block in `pilot/guidance.py` (`_cross`): every qualifying side blob is
now recorded in `side_seen`, even before the crossed gate has left a blank
frame (`cross_gone`). The 0.2 s side-confirm path is unchanged. Effect: at a
crossing timeout the pilot turns back toward a glimpsed side gate
(`_side_pass` fallback) instead of aborting.

Motivation: baseline flight `20261027_112450` died at gate 32 after the
missed gate left one frame at the right edge (x 0.97) inside an unbroken
visibility run. `cross_gone` never armed, no `side_seen`, 4 s of straight
blind flight at magenta gates that never turned green, abort. Frames prove
the miss (nearest gate still magenta, close, 3.5 s later).

## Regression tests

`hackathon/tests/test_side_glimpse.py` (5 tests, new):

- base and candidate byte-identical commands over a normal
  approach/cross/pass/recover/lost script (no side blobs);
- side-confirm after a blank frame unchanged (5 x `side_candidate`, then pass);
- 32-gate replay: base aborts `no next gate after crossing`, candidate
  side-passes and turns right (`search`, yaw > 0, pitch 0);
- a glimpse in one crossing does not leak into the next (both abort, 1 pass);
- both versions hash-intact.

Suites: hackathon 85/85, root 107/107, V2 35/35.

## Flights (3/3 allowed, same Uncrashed session, no Meta calls)

| flight | gates | time | end | damage | fix engaged? |
|---|---|---|---|---|---|
| candidate 1 | 11 | 104 s | `next gate lost` (search) | 1 @ 25.6 s | no (0 side episodes) |
| candidate 2 | 30 | 279 s | `no next gate after crossing` | 0 | no (no side glimpse) |
| candidate 3 | 57 | 500 s | `no next gate after crossing` | 4 (all survived) | no (no side glimpse) |
| baseline range (4) | 2-32 | 44-299 s | 3 x crossing, 1 x search | 0-3 | n/a |
| x7 finish (same code) | 63 | 579 s | Results screen | 2 | n/a |

Candidate 1: likely overflight + false pass at 11, lost the low gate at the
frame bottom, dive-search into magenta, abort. Candidate 2: overflight at
gate 30 (gate whipsawed, exited bottom, peak 0.56, no hit), 4 s blind past a
magenta post, abort. Candidate 3: 57 clean gates with 4 survived hits, then a
below-center vanish at gate 57 (peak 0.39), 4 s blind over a gully, abort.
Monitor auto-diagnosed all three (`eval/roadtrip_candidate/`); attempt
records train 86-88, history append-only.

## Verdict

- No regression: proven. The change only executes at crossing timeouts with a
  recorded glimpse; all three flights behaved exactly like the baseline
  (identical code paths), and unit tests pin the identity.
- Improvement: NOT confirmed. The trigger (a qualifying side glimpse) never
  occurred in 3 flights / 98 gates. The better totals (median 30 vs 24, best
  57 vs 32) are variance, not a treatment effect: n is tiny and the baseline
  spread is 2-32 with the identical code finishing once (x7, 63 gates).
- Milestone (one verified Roadtrip finish): NOT MET. No Results screen.
- Preservation: the frozen version and its tests stay (harmless, may help
  future flights). V2 keeps `p2_fast_baseline` as its baseline; the candidate
  is NOT promoted to the active V2 configuration without improvement evidence.

## What the data now says

Across 7 full-course flights (4 baseline + 3 candidate), the dominant killer
is the overflight: the drone passes over (or under) a gate, the gate exits
through the bottom (or top) with no side glimpse, and the pilot flies 4 s
straight blind and aborts (23-gate baseline, candidates 1-3 either proven or
likely). Lateral misses with an edge glimpse (the fixed case) are a minority
(1-2 of 7). Hits/spins that turn into blind flight are the rest.

Recommended next targeted improvement (needs its own task + flights):
on crossing timeout, enter search toward the last-seen direction (cut pitch,
yaw) instead of aborting. That covers ALL blind-timeout deaths regardless of
exit direction, where the side-glimpse fix covers only lateral misses. Needs
care: the drone is at ~9 m/s, so the timeout must first slow it before
turning. Alternative: validate passes against overflights (require the
crossed gate to exit through the top edge at high peak before counting).
