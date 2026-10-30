# Real-Gate Detector — Mavic Air 2 footage

New program that takes the gate detector proven in Uncrashed and points it
at **real gates in DJI Mavic Air 2 footage**, with detection overlays.

## How it reuses the Uncrashed software

- Base detector: [core/gate_detector.py](/C:/Users/VYRAL/Desktop/drone-ai-v2/core/gate_detector.py)
  (`GateDetector`, exposed as `droneai.perception.GateDetector`). HSV
  threshold → fragment grouping → hollow/squarish shape check →
  normalised gate geometry (`x, y` in -1..1, `size`, `bbox`, `corners`).
- This package does **not** copy or edit that code, and no frozen version
  is touched. [detector.py](/C:/Users/VYRAL/Desktop/drone-ai-v2/real_gate_detector/detector.py)
  subclasses/reuses its blob + shape machinery and only changes the HSV
  ranges, because real gates are not simulator green (H 55-72, S≥150).
- New for real footage: colour presets (`orange`, `red`, `blue`,
  `real_green`, `yellow`, `magenta`, `sim_green`), `auto` mode that tries
  them all, and a heuristic `confidence` (squarish + hollow scores high).

## Run it

From the `drone-ai-v2` root, on any Mavic Air 2 MP4/MOV:

```powershell
.\.venv\Scripts\python.exe -m real_gate_detector.detect --input path\to\flight.mp4
.\.venv\Scripts\python.exe -m real_gate_detector.detect --input path\to\flight.mp4 --preset orange
.\.venv\Scripts\python.exe -m real_gate_detector.detect --input path\to\flight.mp4 --detections out.csv --every 2
```

Outputs next to the input by default: `<name>_overlay.mp4` (annotated
video) and `<name>_detections.json` (or `.csv`). Each detection row has
`frame_index, timestamp_s, visible, color, x, y, size, confidence,
clipped, aspect, fill, pixels, corners, bbox`.

Overlay draws: bounding box, corner polygon, gate centre dot, line from
screen centre to gate centre, and a label with colour/confidence/geometry.

No footage handy? Generate the synthetic demo clip and detect on it:

```powershell
.\.venv\Scripts\python.exe -m real_gate_detector.make_sample
.\.venv\Scripts\python.exe -m real_gate_detector.detect --input real_gate_detector\sample\sample_gate.mp4 --preset orange
```

## Mavic Air 2 notes & honest limits

- Works on exported MP4/MOV files (incl. 4K; frames are downscaled to
  `work_width` 640 internally, same as the sim detector). No live DJI
  feed — the Air 2 has no open real-time video API for this.
- Colour vision needs a **bright, saturated gate** and decent light.
  White/grey gates, backlight, and motion blur will miss; the fix is a
  brighter gate or a fiducial (ArUco/AprilTag), not more tuning.
- `confidence` is a shape heuristic, not a learned probability.
