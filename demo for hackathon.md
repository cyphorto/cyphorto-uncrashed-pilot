# Demo for Hackathon — Autonomous Drone Pilot: Simulator to Real World

> **One-line pitch:** An AI pilot that learned to fly an FPV racing course in a
> simulator — no memorised route, no waypoints, just camera vision — is now
> being transferred to a real custom-built 5-inch drone, as the first step
> toward autonomous delivery of food and medicine to places roads cannot reach.

---

## 1. What already works (the proof, not the promise)

The simulator pilot in this repository flies the Roadtrip course in
Uncrashed (FPV simulator) fully autonomously:

- It watches only the game camera feed and drives a virtual Xbox controller.
- **No gate positions, routes, or waypoints are memorised anywhere in the
  code.** Gates are found live, by colour vision (green = next gate,
  magenta = later gates), and flown through by pursuit of the gate centre.
- It handles crashes, damage, being stuck, and losing sight of the next
  gate with detect-and-recover states, then keeps racing.

### Best run so far

| | |
|---|---|
| Version | `p2_finish_blindcap_v8` (frozen, hash-verified, untouched) |
| Course | Roadtrip, 60 gates |
| Time | 461.8 s (7:42) — almost a minute faster than the builder's own finished human-piloted runs |
| Contact | No gate or obstacle hits; 2 slight ground skids on one sharp descent |
| Evidence | Flight log at `versions/p2_finish_blindcap_v8/logs/20261027_181311_457981_gate_live/log.csv`; record in `eval/roadtrip_candidate/BEST_p2_finish_blindcap_v8.md` |

**Honesty note (say this out loud if asked):** that finish is confirmed by
the pilot watching it live plus the telemetry log. The formal project rule
is that a finish counts only when confirmed in
`training_data/runs/annotations.csv` against the game's Results screen —
that annotation is still pending. Judges respect a team that knows the
difference between "it worked" and "we verified it." Earlier
annotation-confirmed finishes do exist for the parent versions
(`p2_fast_baseline` 8:27.545, 2026-10-27; the x7 run 9:29.874, 2026-10-26).

### Why it got good (the engineering story)

The pilot was improved through ~19 frozen candidate versions, **one change
at a time**, each diagnosed from the previous flight's telemetry log:

- Flew over the last gate → blind-crossing guard: never hold full pitch
  through a gate you can no longer see.
- Hit the bottom rung → proactive camera ground detector that lifts the
  flight line *before* contact, with a separate floor held through gate
  crossings.
- Hit gate sides in sharp turns → "look-ahead" turn brake: detect the next
  gate at a sharp angle, slow down massively, turn, then go straight.
- Bumpy, drifting flight → filtered, symmetric, slew-limited climb so the
  stick commands themselves stay smooth (log analysis proved the drone's
  velocity vector, not stick noise, was the problem).
- Best speed discipline: hold ~24 km/h (6.7 m/s), slow only *after*
  passing a gate, or massively for a sharp turn.

Each candidate is frozen and hash-verified with `flightops/freeze.py` and
covered by regression tests in `tests/`. Nothing was tuned by guessing —
every change traces to a logged failure.

---

## 2. The real drone (target hardware)

Already owned and flying:

| Part | Spec | Role in the autonomous build |
|---|---|---|
| Frame / motors | Custom 5-inch, 2207 motors | Airframe — unchanged |
| ESC | 60 A | Unchanged |
| Flight controller | H743 | Runs Betaflight today; ArduPilot-capable (exact board model to confirm) |
| Video | DJI O4 Air Unit Pro + Goggles N3 | **Pilot/monitoring video only** — safety pilot's eyes, not the AI's |

Key fact: the DJI gear is only a video link. Flight control authority will
come from the open-source flight stack below, so no DJI software limits
what the AI can do.

### Hardware to add

| Item | Why | Notes |
|---|---|---|
| Companion computer (Jetson Orin Nano class, or Raspberry Pi 5) | Runs the vision + guidance brain onboard | Needs a dedicated 5 V / ≥4 A BEC off the flight pack — never power it from the FC |
| Small forward camera the computer owns (USB UVC or Pi Global Shutter) | The AI's eyes | The O4 cannot feed video to a computer onboard (USB is config/storage; the feed goes encrypted to the goggles). The O4 stays as the human safety pilot's feed |
| Downward rangefinder (e.g. TF-Luna, UART) | True height-above-ground | Replaces the simulator's screen-scraped altitude; feeds the same ground-avoidance logic that won in sim |
| GPS + compass (M10 class) | Position hold and any delivery leg beyond one gate | Optional for the first gate demo; required for real delivery |
| Independent RC receiver + physical kill/arm switch (ELRS etc.) | Human override the AI can never block | **Non-negotiable safety requirement** |

### Firmware decision

| | Betaflight | ArduPilot ⭐ recommended |
|---|---|---|
| On the H743 | Stays as-is | Reflash Copter (MATEKH743-class target) |
| Control interface | MSP RC override (`MSP_SET_RAW_RC`, MSP v1 code 200) over UART/USB, ~50 Hz | MAVLink `SET_ATTITUDE_TARGET` over UART 921600, 20–50 Hz |
| Flight mode | ANGLE + MSP override | `GUIDED_NOGPS` (attitude), or `GUIDED` with GPS (position/velocity) |
| Position hold | None — drifts | Yes (GPS outdoors / optical flow indoors) |
| Failsafes | Basic RX failsafe | Full: geofence, battery, link loss, return/land, logging |
| Sim-code reuse | Closest 1:1 (the sim pilot literally outputs sticks) | Guidance brain reused; outputs remapped to attitude targets |

**Recommendation: ArduPilot on the H743**, because it offers MAVLink,
`GUIDED_NOGPS` attitude control (the natural landing spot for a stick-style
guidance pilot), real failsafes and geofencing, dataflash logging, and —
critically — **SITL simulation**: the transferred pilot can fly the whole
mission in ArduPilot's simulator before a propeller ever spins.
Betaflight + MSP remains the fallback if keeping the existing race tune
matters more than autonomy safety features.

**Open question before any promise:** "H743" alone does not prove an
ArduPilot target exists — the exact board model (printed target name, e.g.
Matek H743) must be confirmed first.

### How the sim pilot maps to the real drone

```
SIMULATOR (today)                     REAL DRONE (transfer)
─────────────────                     ──────────────────────
Game window capture        ──►        Onboard camera → companion computer
HSV gate detection         ──►        Same detector, retuned for a real,
                                      high-contrast gate (or ArUco/AprilTag)
Screen-scraped ALT/speed   ──►        MAVLink telemetry + TF-Luna rangefinder
GateGuidance / Flight      ──►        Same Python guidance, unchanged logic
Virtual Xbox sticks        ──►        ArduPilot SET_ATTITUDE_TARGET
                                      (GUIDED_NOGPS)  — or MSP_SET_RAW_RC
                                      if Betaflight is kept
Damage/mode icon checks    ──►        MAVLink failsafes + human kill switch
```

What does **not** transfer for free (be upfront about this):

- Gate-detection colours were tuned on the game's gates; a real gate needs
  re-tuning (a bright/LED gate or fiducial marker makes this far easier).
- The simulator has near-zero latency; the real loop is ~50–150 ms
  end-to-end, so speed and distance thresholds must be re-validated.
- Simulator "metres per second" are game units; every threshold needs
  re-checking at real scale, starting slow and low.

---

## 3. The demo plan (what judges actually see)

**Demo goal: the real drone flies itself through one gate, on camera,
with a human safety pilot standing by — then the same brain is shown
finishing the full 60-gate simulator course.**

1. **Hook (30 s):** simulator video — the AI finishing Roadtrip faster
   than its builder can. "No route was programmed. It sees gates and
   flies to them."
2. **Live (2–3 min):** the real 5-inch, props guarded or in a netted
   area, takes off under ArduPilot, the companion computer finds the
   gate, flies through it, and the safety pilot demonstrates the kill
   switch working mid-flight.
3. **Vision (1 min):** from one gate to a delivery: marked drop point,
   servo release, dummy payload (a foam "vaccine vial" — clearly a
   mock-up). Food and medicine delivery to remote communities (the
   long-term goal: regions where roads fail in rainy season, clinics
   hours away) is the mission this autonomy is the first brick of.
4. **Fallbacks running the whole time:** a recorded run on screen in case
   the live flight is grounded, and the simulator live on a laptop —
   the sim pilot *always* demos, even if the real drone cannot fly
   that day.

**Never demo:** actual medicine, flights over people, or anything beyond
visual line of sight. Judges reward a team whose safety story is tighter
than their ambition story.

---

## 4. Safety and honesty rules (part of the pitch, not fine print)

- Props-off bench tests first; ArduPilot SITL before that.
- Netted/tethered first flights, low altitude cap, geofence set.
- Independent RC kill switch, tested, held by a human who is *not* the
  person talking to judges.
- Link loss = ArduPilot failsafe (land/return), never "keep flying."
- No payload until the empty drone passes the gate repeatedly.
- Local drone regulations and the event's own flight rules come first;
  if the venue forbids live flight, the video + simulator demo is the
  demo (plan for this from day one).
- Real medical delivery is regulated beyond-visual-line-of-sight work.
  The hackathon proves the autonomy link; it does not deliver medicine.

---

## 5. Roadmap to the hackathon (in order — do not skip ahead)

### Phase 0 — Confirm the platform (days, no flying)
- [ ] Record the exact FC board model/target name, receiver type, and
      battery (4S/6S); confirm an ArduPilot target exists for that board.
- [ ] Weigh the drone; confirm payload/weight margin for companion
      computer + camera + rangefinder + BEC.
- [ ] Check the official hackathon theme, tracks, and judging criteria,
      and the venue's drone/flight rules. Write the pitch to *their*
      words, not ours.

### Phase 1 — Interface in simulation (the big de-risk)
- [ ] Stand up ArduPilot SITL for the confirmed board parameters.
- [ ] Port the guidance output layer: sim stick values →
      `SET_ATTITUDE_TARGET` in `GUIDED_NOGPS` (keep the Betaflight
      `MSP_SET_RAW_RC` path documented as the fallback).
- [ ] Feed SITL "camera" gates (or synthetic gate detections) and prove
      the guidance brain flies to and through a gate end-to-end.
- [ ] Write the bench test: companion ↔ FC over UART, motors disarmed,
      verify command rates, telemetry, and that the RC kill path wins.

### Phase 2 — Bench and first real flights
- [ ] Wire companion + camera + rangefinder; props-off command checks.
- [ ] Retune gate detection on the real gate (bright gate / ArUco tag),
      on recorded real camera footage, offline.
- [ ] Netted flights: hover in `GUIDED_NOGPS`, then one slow gate pass,
      safety pilot on the kill switch, altitude cap low.
- [ ] Repeat the gate pass until it is boring. Boring is the goal.

### Phase 3 — Demo hardening
- [ ] Servo payload drop with a dummy payload at a marked point.
- [ ] Record the full demo run on video (several takes) as the fallback.
- [ ] Rehearse the 5-minute pitch; rehearse the failure answer
      ("what happens if it loses the gate / the link / GPS?") — the
      failsafe story *is* the answer.
- [ ] Prepare the one-page leave-behind: problem, proof (sim finish),
      transfer plan, safety, long-term delivery vision.

### Phase 4 — After the hackathon (the real mission)
- GPS waypoint delivery legs in `GUIDED`, then supervised outdoor tests
  at a legal flying site; cold-chain dummy payloads with temperature
  logging; only much later, and only with the relevant aviation
  authority's approvals, any real medical payload. This phase is a
  company/NGO partnership conversation, not a weekend project.

---

## 6. How to win (strategy, honestly)

Judges at a Meta hackathon typically reward: a real problem, a working
demo, technical depth they can verify, and a team that knows its limits.
This project is unusually strong on all four — if it is presented that way.

1. **Lead with the working system, not the idea.** Most teams pitch a
   drone-delivery concept. You can *show* an autonomous pilot that
   already finishes a 60-gate course faster than its builder. Open with
   20 seconds of that footage before explaining anything.
2. **Make the transfer the story.** "Simulator-trained, hardware-real" is
   the narrative arc: sim → SITL → bench → netted flight → one real gate.
   Each step is a slide with evidence, not a promise.
3. **Sell the safety system as a feature.** Failsafes, kill switch,
   geofence, one-change-at-a-time versioning with hash-verified frozen
   builds and 136 regression tests — this reads as engineering maturity,
   which delivery-drone pitches usually lack.
4. **Name the impact precisely.** Not "help Africa" in the abstract: pick
   one concrete scenario (e.g. vaccine/medicine resupply to clinics cut
   off by seasonal roads), one payload (~1–2 kg), one range, and state
   plainly which parts are proven (autonomous gate flight), which are
   next (GPS delivery leg), and which are regulated future work (BVLOS
   medical delivery).
5. **Demo reliability beats demo ambition.** One gate, flown cleanly
   three times in rehearsal, beats a delivery attempt that fails on
   stage. Always have the video + live simulator fallback running.
6. **Answer the hard questions before they're asked.** Latency, wind,
   GPS denial, link loss, "why not just use DJI's SDK?", "what does the
   O4 actually do here?" — each has a one-sentence answer in Sections 2
   and 4 above. Rehearse them.
7. **Use what Meta rewards:** build openly where possible (this repo's
   frozen versions, logs, and tests are already an audit trail), and if
   the event has an AI/open-source track, frame the detector upgrade
   path (learned gate detection, e.g. a small fine-tuned model) as the
   research direction — while demoing the colour detector that works
   *today*.
8. **Leave judges a next step.** A specific ask ("introductions to
   drone-delivery NGOs / a test site / ArduPilot maintainers") makes the
   project feel continuable, which is what prizes and follow-on support
   actually fund.

---

## 7. Quick reference

| | |
|---|---|
| Sim run command (Roadtrip) | `powershell -ExecutionPolicy Bypass -File .\start_roadtrip.ps1 -Version p2_finish_blindcap_v8 -SkipTiltCheck -Label "my flight"` |
| Verify best version intact | `.\.venv\Scripts\python.exe flightops\freeze.py --verify p2_finish_blindcap_v8` |
| Run all regression tests | `.\.venv\Scripts\python.exe -m unittest discover -s tests` |
| Best-run record | `eval/roadtrip_candidate/BEST_p2_finish_blindcap_v8.md` |
| Project status | `PROJECT_STATUS.md` |

*Do not edit the frozen `p2_finish_blindcap_v8` version. Any new change is
one change, on top of it, frozen as a new version — that discipline is
part of the story above.*
