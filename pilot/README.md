# Gate approach pilot

This is an experimental Uncrashed ANGLE-mode pilot. It takes off, settles at 2 m,
turns toward the green gate, and adds a small forward pitch when aligned. Roll
stays neutral. The existing altitude controller follows a slowly adjusted height
target. It has not yet demonstrated a gate pass in the game.

## Run in the game

1. Open `gate_pilot.bat` in the project root.
2. In Uncrashed select the virtual **XboxController**, keep the ALT readout visible,
   and verify **ANGLE** mode. The program holds button A, which must be bound to Angle.
3. Load the course with green gates, press **T** to reset, and leave the sticks neutral.
4. Hold **F8** for half a second. Takeoff begins after a three-second countdown.
5. Hold **F12** to cut throttle immediately. Ctrl+C in the console also stops it.

Only one controller-writing program should run at a time. The pilot captures the
monitor selected by `capture.monitor`; the game must remain visible there.

The default approach lasts at most 30 seconds. After one candidate gate passage it
levels and descends. A candidate is a persistent large-to-small gate transition,
not a confirmed race-score increment. Losing the gate or altitude reading aborts
and cuts throttle. Neutral pitch does not cancel existing forward momentum.

Every attempt saves `logs/<time>_gate_live/`: commands and detections in `log.csv`,
ALT crops, annotated images, and configuration/result in `meta.json`.

## Offline check

```powershell
.\.venv\Scripts\python.exe pilot/gate_run.py --replay data/recordings/20261023_105033_519877_flight
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Replay creates hypothetical commands without connecting a controller. It assumes
settled altitude; recorded images cannot respond to those commands. The existing
manual Acro recording triggers a clipped-gate abort during takeoff, so it does not
establish that this ANGLE pilot can fly the course.

## Tuning

Settings are under `gate_pilot` in `config.json`. Per-attempt overrides work:

```powershell
.\gate_pilot.bat --set gate_pilot.forward_pitch=0.04
```

`yaw_sign` and `forward_sign` describe the pilot's commanded directions. Your
existing input/output mappings are preserved. Confirm these directions in a short
attempt before increasing pitch. `aim_y=0.35` is an initial camera-offset guess
(positive is below image centre), and needs calibration for the current camera.
Pitch is an attitude command, not a speed limit. Vertical guidance does not yet
compensate for camera motion caused by pitching, and there is no horizontal-speed
estimator or active braking controller.

The previous hover's unreadable **1.6 m** crop was manually checked and added to
the ALT templates, retaining the original confidence thresholds. That sample now
reads correctly; this does not establish reliability on new backgrounds.
