"""CLI: run the real-gate detector over Mavic Air 2 video footage.

Examples (from the drone-ai-v2 root):
    .\\.venv\\Scripts\\python.exe -m real_gate_detector.detect --input footage.mp4
    .\\.venv\\Scripts\\python.exe -m real_gate_detector.detect --input footage.mp4 --preset orange --output runs\\out.mp4
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from real_gate_detector.detector import PRESETS, RealGateDetector, draw_overlay, load_config

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def process(input_path: Path, output: Path, detections_path: Path,
            preset: str, cfg: dict, every: int, max_frames: int) -> dict:
    detector = RealGateDetector(preset=preset, cfg=cfg or None)
    rows: list[dict] = []

    if input_path.suffix.lower() in IMAGE_EXTS:
        frame = cv2.imread(str(input_path))
        if frame is None:
            raise SystemExit(f"cannot read image: {input_path}")
        det = detector.detect(frame, 0, 0.0)
        rows.append(det.row())
        cv2.imwrite(str(output), draw_overlay(frame, det))
        return _summary(rows, 1)

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {input_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise SystemExit(f"cannot write output video: {output}")

    idx = 0
    last = None
    while True:
        ok, frame = cap.read()
        if not ok or (max_frames and idx >= max_frames):
            break
        if idx % max(1, every) == 0:
            last = detector.detect(frame, idx, idx / fps)
        assert last is not None
        rows.append(last.row() | {"written_frame": idx} if every > 1 else last.row())
        writer.write(draw_overlay(frame, last))
        idx += 1
    cap.release()
    writer.release()
    if idx == 0:
        raise SystemExit(f"no frames decoded from: {input_path}")

    detections_path.parent.mkdir(parents=True, exist_ok=True)
    if detections_path.suffix.lower() == ".csv":
        with detections_path.open("w", newline="", encoding="utf-8") as fh:
            wtr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wtr.writeheader()
            wtr.writerows(rows)
    else:
        detections_path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return _summary(rows, idx)


def _summary(rows: list[dict], total: int) -> dict:
    hits = sum(1 for r in rows if r["visible"])
    return {"frames": total, "detections": hits,
            "detection_rate": round(hits / max(1, total), 3)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Detect real gates in drone footage.")
    p.add_argument("--input", required=True, help="Mavic Air 2 video (MP4/MOV) or image")
    p.add_argument("--output", default=None, help="annotated output video/image")
    p.add_argument("--detections", default=None, help="detections .json or .csv path")
    p.add_argument("--preset", default="auto",
                   choices=sorted(PRESETS) + ["auto"],
                   help="gate colour preset (default: auto = try all)")
    p.add_argument("--config", default=None, help="JSON overrides for GateDetector cfg")
    p.add_argument("--every", type=int, default=1, help="detect every Nth frame")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = all)")
    a = p.parse_args(argv)

    inp = Path(a.input)
    if not inp.exists():
        raise SystemExit(f"input not found: {inp}")
    out = Path(a.output) if a.output else inp.with_name(inp.stem + "_overlay.mp4")
    det_path = Path(a.detections) if a.detections else inp.with_name(inp.stem + "_detections.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config(a.config)
    # preset may also come from the config file
    preset = cfg.pop("preset", a.preset)
    summary = process(inp, out, det_path, preset, cfg, a.every, a.max_frames)
    print(json.dumps({**summary, "output": str(out), "detections_file": str(det_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
