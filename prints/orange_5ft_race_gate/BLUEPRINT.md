# Orange 5 ft race gate — printed joints + PVC pipe (Bambu Lab A1 / A1 mini)

One full-size FPV race gate for the real 5-inch drone, designed in Blender
(`build_gate_joints.py`, 1 unit = 1 mm). The printer only makes the
**joints** — the gate itself is cheap PVC pipe that you cut and push-fit.
No glue, no screws in the frame (optional M4 pins, below).

Clear opening is 1533 × 1533 mm (5 ft = 1524 mm), pipe centrelines
1560 × 1560 mm, overall height about 1628 mm. Bottom bar sits 50 mm off
the ground, feet stick out 300 mm front and back so it stands on its own.

## Files

| File | What it is |
|---|---|
| `gate_corner_elbow.3mf` / `.stl` | Top corner — **print 2×** |
| `gate_foot_corner_left.3mf` / `.stl` | Bottom-left foot corner — **print 1×** |
| `gate_foot_corner_right.3mf` / `.stl` | Bottom-right foot corner — **print 1×** |
| `orange_5ft_race_gate_assembly.blend` | Assembled gate scene (setup reference) |
| `orange_5ft_race_gate_preview.png` | Render of the assembled gate |
| `build_gate_joints.py` | Rebuildable Blender script (dimensions at the top) |
| `verify_and_make_3mf.py` | Re-checks the STLs and re-packs the 3MFs |

## Print settings (Bambu Studio)

1. Open each `.3mf`, pick your **bright orange PETG** profile. PETG, not
   PLA — PLA is brittle outdoors and in a crash. Orange matters: the
   real-gate detector's `orange` preset looks for exactly this colour.
2. Layer height 0.20 mm, **4 wall loops**, 30–40% gyroid infill (the
   sockets need the wall strength more than infill).
3. **No supports.** Horizontal sockets have a pointed roof inside, so
   they print clean as exported. Print every part flat as it opens —
   do not rotate.
4. All parts fit an A1 mini plate (largest is the foot at 93 × 130 mm).
5. Rough filament use: elbow ~35–50 g, each foot ~55–80 g at the settings
   above (Bambu Studio shows the exact number per part).

## Buy / cut the pipe

Pipe: **3/4″ PVC, outside diameter 26.7 mm** (standard 3/4″ Schedule 40).
Check yours with calipers before printing if you can — the sockets are
27.6 mm. If your pipe measures different, tell me the OD and the joints
get regenerated; do not force an oversize pipe in.

Cut list (7.33 m total — buy 3× 3 m lengths, or 2× 10 ft):

| Piece | Qty | Cut length |
|---|---|---|
| Vertical posts | 2 | 1555 mm |
| Top + bottom bars | 2 | 1510 mm |
| Foot pipes | 2 | 600 mm |

Deburr the cut ends. If your PVC is white, make it orange before
assembly — wrap each pipe in bright orange tape (spiral wrap is fine)
or spray it with orange paint made for plastic. White pipe + orange
joints will **not** read as a gate to the detector; the whole square
frame has to be orange.

## Set it up (your part — about 10 minutes)

1. Slide a 600 mm foot pipe through the round hole in each foot corner
   and centre it (300 mm each side).
2. Push a 1555 mm post into the top of each foot corner. Left foot on
   the left: its side socket must point inwards, towards the other foot.
3. Push the 1510 mm bottom bar between the two foot corners.
4. Put a corner elbow on top of each post, flipped so its upright
   socket faces **down** onto the post and its side socket points
   inwards.
5. Push the second 1510 mm bar between the two elbows.
6. Stand it on flat ground, feet flat, and check it's square (the two
   diagonals post-to-post should match). Outdoors in wind, drop a
   sandbag or tent peg over each foot pipe.

Optional but recommended — pin the posts so nothing works loose:
each elbow (both sockets) and each foot (post socket) has a 4.2 mm
hole across it. With the pipe pushed fully home (45 mm in), drill
4.2 mm through the pipe using the hole as a guide, then drop in an
M4×40 bolt or a fat screw. 6 pins total. The bottom bar needs no pin —
it's trapped between the two feet once the posts are pinned.

## First use

- Bench-check the detector against the finished gate before flying:
  `python -m real_gate_detector.detect --preset orange` on phone/Mavic
  footage of it, or just hold the gate in front of the camera.
- First autonomous passes stay netted/tethered with the RC kill switch
  in hand, per `hardware for next stage.txt`. PVC flexes and the joints
  are PETG — a 5-inch at speed will knock it over or crack a joint
  before it hurts the drone much, but props vs. pipe is still props vs.
  pipe: keep people behind the flight line.
- Cracked a joint? Reprint just that one part; the pipe survives.

## Rebuilding / resizing

```
blender -b --factory-startup --python-exit-code 1 -P build_gate_joints.py
python verify_and_make_3mf.py
```

Edit the tunables at the top of `build_gate_joints.py` (`PIPE_OD`,
`SOCKET_R`, `GATE_CL`, …), re-run both, and the STLs, 3MFs, `.blend`
and preview are regenerated. Current verification: all three parts
watertight, flat at Z=0, and inside a 180 × 180 mm plate.
