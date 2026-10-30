# Green 5-inch propeller guard — blueprint for Bambu Lab A1 / A1 mini

One propeller guard for a standard 5-inch FPV drone, modelled in Blender
(`build_prop_guard.py`, 1 unit = 1 mm) and ready to slice in Bambu Studio.

> Assumption made for you: a 5-inch drone. If your props are a different
> size, change `PROP_DIA` / `INNER_R` at the top of `build_prop_guard.py`
> and re-run it — everything else follows from those numbers.

## Files

| File | What it is |
|---|---|
| `green_5in_prop_guard.3mf` | **Open this in Bambu Studio** (preferred) |
| `green_5in_prop_guard.stl` | Same part, plain STL (also opens in Bambu Studio) |
| `green_5in_prop_guard.blend` | Blender scene — ring, tabs, ribs, render setup |
| `build_prop_guard.py` | Rebuildable Blender script (all dimensions at the top) |
| `green_5in_prop_guard_preview.png` | Render of the part |
| `verify_and_make_3mf.py` | Re-checks the STL (size, watertight) and re-packs the 3MF |

## Dimensions (mm)

```
            <- 141.2 outer ->
        . - - - - - - - - - - .
      /   <- 134.0 inner ->    \      Height:        18.0
     |    (prop: 127.0 = 5")    |     Wall:          3.6 thick
     |      3.5 tip clearance   |     Tabs:          4x, bottom face,
     |        per side          |                    18 long x 14 wide x 3 thick
      \                         /     Tab slot:      8.0 long x 3.4 wide (M3)
        ' - - - - - - - - - - '      Ribs:          8x on the outer wall
                                    Weight:        ~38 g at 100% infill (less at print settings below)
                                    Verified:      141.2 x 141.2 x 18.0 mm, watertight, base flat at Z=0
```

Fits A1 mini (180 x 180) and A1/P1/X1 (256 x 256) build plates, printed
flat as exported — do not rotate it.

## Bambu Studio settings

1. Open `green_5in_prop_guard.3mf`, pick your green filament profile.
2. Layer height 0.20 mm, 3 wall loops, 15-20% gyroid infill.
3. No supports. No brim needed (flat 141 mm ring); use a brim only if
   your plate adhesion is poor.
4. Seam: aligned. Print one guard per prop you want to protect.

## Fitting it

- The 4 bottom tabs reach inwards at 0/90/180/270 degrees. Fix each tab
  to a drone arm with an M3 screw through the slot (the slot lets you
  slide it to line up), or with a zip-tie through the slot.
- Spin the prop **by hand first**: you need clear daylight between the
  prop tips (127 mm) and the guard (134 mm) all the way round, and the
  prop disc must sit inside the 18 mm guard height.
- Print a second guard mirrored the same way — the part is symmetrical,
  so the same file works for every corner.

## Safety / material notes

- **Green PLA is for a fit-check print.** PLA is stiff and brittle; a
  guard that shatters can throw pieces into the prop. For a guard you
  actually fly, reprint the same file in PETG (tougher) or TPU 95A
  (flexible, best for guards).
- A guard adds ~25-38 g per corner and changes handling. Test hover at
  low throttle in an open space first.
- If a tab slot does not line up with your arm screws, tell me your
  motor mount pattern (e.g. 16x16 mm or 19x19 mm M3) and prop size,
  and the tabs can be made to match exactly.

## Rebuilding / resizing

```
blender -b --factory-startup --python-exit-code 1 -P build_prop_guard.py
python verify_and_make_3mf.py
```

Edit the tunables at the top of `build_prop_guard.py` (`INNER_R`, `WALL`,
`HEIGHT`, `TAB_*`, `RIB_COUNT`), re-run both commands, and the STL, 3MF,
`.blend` and preview are regenerated.
