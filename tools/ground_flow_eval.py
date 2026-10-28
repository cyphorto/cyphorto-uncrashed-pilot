r"""Check the camera ground estimate (core/ground_flow.py) on a recorded flight.

    .\.venv\Scripts\python.exe tools\ground_flow_eval.py <log dir> [--every 3] [--tilt 30]

Needs a log folder flown with gate_pilot.record_hz > 0 (frames in flow/, named by the log's
t). For each pair of consecutive frames it takes speed, sink and pitch from the nearest
log.csv row, skips banked moments (the flat-ground model ignores roll), and writes
ground_flow.csv next to log.csv: t, phase, state, ALT height, the camera height and its
match quality. ALT is height above the ground only near the start (the start pad is on the
road), so that stretch is the check; later, ground contacts should read near 0.
"""
import argparse
import bisect
import csv
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.ground_flow import estimate  # noqa: E402


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def run(folder, every=3, tilt=30.0, deg_per_pitch=50.0, max_roll=0.1, max_dt=0.15):
    folder = Path(folder)
    rows = list(csv.DictReader(open(folder / "log.csv", newline="", encoding="utf-8")))
    ts = [_f(r["t"]) for r in rows]
    frames = sorted(folder.glob("flow/*.jpg"), key=lambda p: float(p.stem))
    out = []
    for k in range(1, len(frames), every):
        p0, p1 = frames[k - 1], frames[k]
        t0, t1 = float(p0.stem), float(p1.stem)
        if not 0 < t1 - t0 <= max_dt:
            continue
        r = rows[max(0, min(len(rows) - 1, bisect.bisect_left(ts, (t0 + t1) / 2)))]
        roll, pitch = _f(r["roll"]) or 0.0, _f(r["pitch"]) or 0.0
        speed = _f(r["speed_ms"])
        rec = {"t": round(t1 - ts[0], 2), "phase": r["phase"], "state": r["guidance_state"],
               "alt": _f(r["h_filt"]), "speed": speed, "pitch": pitch, "roll": roll, "est": None, "contrast": None}
        if abs(roll) <= max_roll and speed is not None:
            a, b = cv2.imread(str(p0), cv2.IMREAD_GRAYSCALE), cv2.imread(str(p1), cv2.IMREAD_GRAYSCALE)
            est, info = estimate(a, b, t1 - t0, speed, -(_f(r["v_filt"]) or 0.0), tilt - deg_per_pitch * pitch)
            rec["est"] = None if est is None else round(est, 2)
            rec["contrast"] = None if est is None else round(info["contrast"], 3)
        out.append(rec)
    with open(folder / "ground_flow.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["t"])
        w.writeheader()
        w.writerows(out)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--every", type=int, default=3)
    p.add_argument("--tilt", type=float, default=30.0)
    a = p.parse_args()
    out = run(a.folder, a.every, a.tilt)
    print(f"{len(out)} pairs, {sum(r['est'] is not None for r in out)} estimates -> {Path(a.folder) / 'ground_flow.csv'}")


if __name__ == "__main__":
    main()
