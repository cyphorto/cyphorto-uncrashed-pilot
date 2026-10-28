r"""Replay the in-flight ground warning (core/ground_flow.py GroundWarn) over a recorded flight.

    .\.venv\Scripts\python.exe tools\ground_warn_replay.py <log dir> [--tilt 30] [--hz 5]

Needs frames in flow/ (gate_pilot.record_hz). Every 1/hz s of log time it takes the newest
recorded frame and the one before it, runs estimate_fast with that moment's speed, sink and
pitch, feeds GroundWarn, and prints each warning episode (start, end, ALT, filtered height,
guidance state). Writes ground_warn.csv next to log.csv.
"""
import argparse
import bisect
import csv
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.ground_flow import GroundWarn, attitude_deg, estimate_fast  # noqa: E402


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def replay(folder, tilt=30.0, hz=5.0, max_roll=0.15):
    folder = Path(folder)
    rows = list(csv.DictReader(open(folder / "log.csv", newline="", encoding="utf-8")))
    ts = [_f(r["t"]) for r in rows]
    frames = sorted(folder.glob("flow/*.jpg"), key=lambda p: float(p.stem))
    ft = [float(p.stem) for p in frames]
    warn, out, next_t = GroundWarn(), [], ft[1] if len(ft) > 1 else None
    for k in range(1, len(frames)):
        t1 = ft[k]
        if t1 < next_t:
            continue
        next_t = t1 + 1.0 / hz
        t0 = ft[k - 1]
        r = rows[max(0, min(len(rows) - 1, bisect.bisect_left(ts, t1)))]
        speed, roll, pitch = _f(r["speed_ms"]), _f(r["roll"]) or 0.0, _f(r["pitch"]) or 0.0
        est, info = None, {}
        if speed is not None and abs(roll) <= max_roll and 0 < t1 - t0 <= 0.15:
            est, info = estimate_fast(cv2.imread(str(frames[k - 1]), 0), cv2.imread(str(frames[k]), 0), t1 - t0,
                                      speed, -(_f(r["v_filt"]) or 0.0), tilt - attitude_deg(pitch))
        warn.add(t1, est, info, speed)
        out.append({"t": round(t1 - ts[0], 2), "phase": r["phase"], "state": r["guidance_state"], "alt": _f(r["h_filt"]),
                    "speed": speed, "est": None if est is None else round(est, 2), "edge": info.get("edge"),
                    "height": warn.height(t1), "warn": int(warn.warning(t1)), "damage": r.get("damage")})
    with open(folder / "ground_warn.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    return out


def episodes(out):
    eps, cur = [], None
    for o in out:
        if o["warn"] and cur is None:
            cur = {"start": o["t"], "end": o["t"], "alt": o["alt"], "min_h": o["height"], "state": o["state"]}
        elif o["warn"]:
            cur["end"], cur["min_h"] = o["t"], min(cur["min_h"], o["height"])
        elif cur is not None:
            eps.append(cur)
            cur = None
    if cur is not None:
        eps.append(cur)
    return eps


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--tilt", type=float, default=30.0)
    p.add_argument("--hz", type=float, default=5.0)
    a = p.parse_args()
    out = replay(a.folder, a.tilt, a.hz)
    eps = episodes(out)
    valid = sum(o["height"] is not None for o in out)
    print(f"{len(out)} estimates, {valid} with a filtered height, {len(eps)} warning episodes")
    for e in eps:
        print(f"  {e['start']:7.2f}-{e['end']:7.2f} s  ALT {e['alt']}  lowest filtered height {e['min_h']:.2f} m  ({e['state']})")


if __name__ == "__main__":
    main()
