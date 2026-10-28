"""Run the gate detector over a recording and write files to review it by eye.

    python tools/eval_gate_detector.py data/recordings/<run>
    python tools/eval_gate_detector.py data/recordings/<run> --video --every 6

Writes into the run folder:
    gates.csv           one row per frame: frame, capture time, detector output
    gates_sheet.jpg     contact sheet with the overlay on every Nth frame
    gates_overlay.avi   (--video) every frame with the overlay, for the viewer or VLC
Prints a summary: how often a gate was seen, suspected gate passes, and frames
where the detection jumped across the screen (the ones worth checking first).
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.gate_detector import FIELDS, GateDetector, draw


def capture_times(run):
    path = run / "frames.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {int(r["frame"]): float(r["capture_start_s"]) for r in csv.DictReader(f)}


def find_passes(rows, near=0.18, drop=0.5, within=10):
    """Gate events from the detector alone.

    pass: the gate was near (size >= near), then within `within` frames a much
          smaller, unclipped gate appears (the next gate has turned green).
    lost: the gate was near, then nothing unclipped shows up within `within`
          frames. Usually a missed gate or a crash, sometimes a pass where the
          next gate is out of view.
    """
    passes, lost = [], []
    k = 0
    while k < len(rows):
        r = rows[k]
        if r["visible"] and r["size"] >= near:
            nxt = None
            for j in range(k + 1, min(len(rows), k + 1 + within)):
                q = rows[j]
                if q["visible"] and not q["clipped"] and q["size"] < r["size"] * drop:
                    nxt = q
                    break
                if q["visible"] and q["size"] >= near:
                    break  # still near the same gate; keep scanning from there
            else:
                lost.append(r["frame"])
                k += within
                continue
            if nxt is not None:
                passes.append(nxt["frame"])
                k = nxt["frame"]
                continue
        k += 1
    return passes, lost


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run", type=Path)
    p.add_argument("--video", action="store_true", help="also write gates_overlay.avi")
    p.add_argument("--every", type=int, default=8, help="contact sheet: one tile every N frames")
    p.add_argument("--jump", type=float, default=0.6, help="flag x/y jumps larger than this between frames")
    args = p.parse_args()

    det = GateDetector()
    times = capture_times(args.run)
    cap = cv2.VideoCapture(str(args.run / "video.avi"))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.run / 'video.avi'}")
    writer, tiles, rows = None, [], []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        g = det.detect(frame)
        row = {"frame": i, "t": times.get(i, ""), **g.row()}
        rows.append({**row, "clipped": g.clipped})
        over = None
        if args.video or i % args.every == 0:
            over = draw(frame, g, f"#{i}")
        if args.video:
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(args.run / "gates_overlay.avi"), cv2.VideoWriter_fourcc(*"MJPG"), 20, (w, h))
            writer.write(over)
        if i % args.every == 0:
            tiles.append(cv2.resize(over, (480, 270), interpolation=cv2.INTER_AREA))
        i += 1
    if writer is not None:
        writer.release()
    if not rows:
        raise SystemExit("no frames decoded")

    with (args.run / "gates.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["frame", "t"] + FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in ["frame", "t"] + FIELDS})

    cols = 5
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[k:k + cols]) for k in range(0, len(tiles), cols)])
    cv2.imwrite(str(args.run / "gates_sheet.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])

    seen = [r for r in rows if r["visible"]]
    jumps = []
    for a, b in zip(rows, rows[1:]):
        if a["visible"] and b["visible"] and max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"])) > args.jump:
            jumps.append(b["frame"])
    passes, lost = find_passes(rows)
    print(f"{args.run.name}: {len(rows)} frames, gate visible in {len(seen)} ({100 * len(seen) / len(rows):.0f}%), "
          f"clipped in {sum(r['clipped'] for r in seen)}")
    print(f"gate passes (next gate appeared) at frames: {passes or 'none'}")
    print(f"near gate then lost (miss, crash or next gate out of view) at frames: {lost or 'none'}")
    print(f"large jumps (> {args.jump}) at frames: {jumps or 'none'}")
    print(f"wrote {args.run / 'gates.csv'}, {args.run / 'gates_sheet.jpg'}" + (", gates_overlay.avi" if args.video else ""))


if __name__ == "__main__":
    main()
