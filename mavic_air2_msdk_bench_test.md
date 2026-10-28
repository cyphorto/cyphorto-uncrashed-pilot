# Mavic Air 2 — DJI SDK camera-and-telemetry bench test

Props removed. No flight command. This test proves only that DJI's
official SDK can deliver live camera frames and telemetry to our own
code on the OnePlus Open. It does not prove autonomous control.

## Hardware and software on hand

- Aircraft: DJI Mavic Air 2 (confirm the label on the aircraft — not
  Mavic Air 1), controller, props removed and stored separately.
- Phone: OnePlus Open, Android 16, OxygenOS 16.0.5.
- Connection: phone USB-C to the controller; controller link to the
  aircraft. The phone never talks to the aircraft directly.
- PC: needs Android Studio installed before anything can be built.
  As of 2026-10-28 this PC has no Android Studio, Java, or ADB.

## SDK choice — the version matters

- Use DJI Mobile SDK **V4 (v4.18)**, official Android sample:
  https://github.com/dji-sdk/Mobile-SDK-Android
- Do **not** use Mobile SDK V5. V5 does not support the Mavic Air 2.
- A DJI developer account and an **App Key** are required. Register the
  app with the sample's exact package name, or registration fails.
- Never put the App Key in this repository or any committed file.

## Known Android 16 risk (read before investing hours)

A public report (dji-sdk/Mobile-SDK-Android issue #1347) documents the
official v4.18 sample on a Pixel 7 Pro running Android 16 showing a
black or 1–2 minute delayed video feed on a Mavic Air 2. DJI's reply
was to try a different phone and that the model/OS would be reported
for adaptation. The OnePlus Open may behave the same. That is why the
test below is split into independent gates: telemetry can pass even
if the video gate fails, and a video failure is a stop point, not a
debugging marathon before the event.

## Safety setup

1. Remove all four propellers. Mark motor positions. Keep props in a
   separate box, not on the bench beside the aircraft.
2. Aircraft unfolded on a flat, stable surface. Battery charged.
3. Force-stop DJI Fly on the phone. Only one app can own the USB
   connection to the controller at a time.
4. In the sample app, do not open or press: takeoff/landing, virtual
   stick, waypoint, ActiveTrack, or any motor-start control.
5. Abort at once if any motor turns, the SDK reports motors on, or
   the aircraft reports a temperature or compass fault.

## Test gates (record pass/fail for each, with a screenshot or log)

### Gate A — SDK registration and connection

- App launches on the OnePlus Open without crashing.
- SDK registration reports success.
- Product connects and identifies as Mavic Air 2, firmware shown.

### Gate B — Telemetry (no camera needed)

- Battery percentage and voltage update live.
- GPS satellite count and position update live.
- Altitude reads near ground level and stays stable.
- Pitch, roll, and yaw respond when the aircraft is tilted by hand.
- Flight mode, RC link, and aircraft link status are shown.
- Motor status remains stopped for the whole test.

### Gate C — Camera

- Live preview is present and fresh: a hand waved at the lens appears
  with under ~1 second of delay.
- Gimbal pitch follows the controller wheel.
- Moving the aircraft by hand moves the image in real time.
- If the image is black or delayed by seconds after one retry with a
  different cable and USB port order, mark Gate C **failed —
  Android 16 known issue** and stop. Do not spend event days on it.

## Evidence to keep for the hackathon

- One screenshot or screen recording showing the sample app, live
  telemetry values changing, and (if Gate C passes) the live image.
- The gate results above, filled in. A documented telemetry-only
  pass is still honest transfer evidence: DJI telemetry reached our
  own code. A failed Gate C is presented as a named platform limit,
  with DJI Fly footage plus offline gate detection as the fallback.

## Out of scope for this test

- Any motor start, takeoff, virtual-stick, waypoint, or tracking
  command.
- Any claim that the Mavic Air 2 can be flown by a companion
  computer. It cannot: no onboard SDK, no flight-controller UART.
  SDK control, if ever used, would run through the phone and
  controller link only.
- Gate detection on the phone. That is a later step, and only if
  Gate C passes: consume the sample's YUV frames and run the existing
  colour detector on them, with no control output connected.
