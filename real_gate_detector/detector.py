"""Real-gate detector for Mavic Air 2 footage.

Reuses the Uncrashed detector in core/gate_detector.py (HSV threshold,
fragment grouping, hollow/squarish shape check, normalised gate geometry)
and retunes it for real-world gates, which are not simulator green.

Geometry convention is identical to the sim detector:
    x: -1 left edge, +1 right edge, 0 centre
    y: -1 top edge,  +1 bottom edge, 0 centre
    size: sqrt(hull area) / frame width
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

# HSV ranges (OpenCV H 0-179). sim_green is the original Uncrashed tuning,
# kept verbatim so sim footage still works. Real presets are broader to
# survive daylight, auto-exposure and H.264 compression on Mavic Air 2 video.
PRESETS: dict[str, list[tuple[list[int], list[int]]]] = {
    "sim_green": [([55, 150, 140], [72, 255, 255])],
    "real_green": [([40, 60, 60], [85, 255, 255])],
    "orange": [([5, 90, 90], [25, 255, 255])],
    "red": [([0, 90, 90], [10, 255, 255]), ([170, 90, 90], [179, 255, 255])],
    "blue": [([90, 70, 70], [130, 255, 255])],
    "magenta": [([150, 80, 110], [172, 255, 255])],
    "yellow": [([22, 90, 90], [38, 255, 255])],
}

# Order tried in "auto" mode: most distinctive real-gate colours first.
AUTO_ORDER = ["orange", "red", "real_green", "blue", "yellow", "magenta", "sim_green"]


@dataclass
class Detection:
    frame_index: int = 0
    timestamp_s: float = 0.0
    visible: bool = False
    color: str = ""
    x: float = 0.0
    y: float = 0.0
    size: float = 0.0
    confidence: float = 0.0
    clipped: bool = False
    aspect: float = 0.0
    fill: float = 0.0
    pixels: int = 0
    corners: list = field(default_factory=list)
    bbox: list = field(default_factory=list)

    def row(self) -> dict:
        return asdict(self)


def _confidence(aspect: float, fill: float, size: float) -> float:
    """Heuristic 0-1 score. The sim Gate has no confidence, so derive one:
    squarish (aspect near 1) + hollow (fill well below solid) scores high."""
    if size <= 0:
        return 0.0
    aspect_score = max(0.0, 1.0 - (aspect - 1.0) / 3.0)
    fill_score = max(0.0, 1.0 - abs(fill - 0.30) / 0.70)
    return round(float(min(1.0, 0.6 * aspect_score + 0.4 * fill_score)), 3)


class RealGateDetector:
    """Multi-colour gate detector built on the sim GateDetector machinery."""

    def __init__(self, preset: str = "auto", cfg: dict | None = None):
        # Import here so the sim stack stays the single source of truth.
        from core.gate_detector import GateDetector

        self.preset = preset
        self._base = GateDetector(cfg)
        self.cfg = self._base.cfg

    def _mask_for(self, bgr: np.ndarray, ranges) -> np.ndarray:
        h, w = bgr.shape[:2]
        ww = int(self.cfg["work_width"])
        small = bgr
        if ww and w != ww:
            small = cv2.resize(bgr, (ww, max(1, round(h * ww / w))),
                               interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mask = np.zeros(hsv.shape[:2], np.uint8)
        for low, high in ranges:
            mask = cv2.bitwise_or(mask, cv2.inRange(
                hsv, np.array(low, np.uint8), np.array(high, np.uint8)))
        if self._base.kernel is not None:
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._base.kernel)
        return mask

    def detect(self, bgr: np.ndarray, frame_index: int = 0,
               timestamp_s: float = 0.0) -> Detection:
        names = AUTO_ORDER if self.preset == "auto" else [self.preset]
        best: Detection | None = None
        for name in names:
            if name not in PRESETS:
                raise ValueError(f"unknown preset {name!r}; choose from "
                                 f"{sorted(PRESETS) + ['auto']}")
            gate = self._base._detect(
                self._mask_for(bgr, PRESETS[name]), merge=(name == "sim_green"))
            if not gate.visible:
                continue
            det = Detection(
                frame_index=frame_index, timestamp_s=round(float(timestamp_s), 3),
                visible=True, color=name, x=float(gate.x), y=float(gate.y),
                size=float(gate.size),
                confidence=_confidence(gate.aspect, gate.fill, gate.size),
                clipped=bool(gate.clipped), aspect=float(gate.aspect),
                fill=float(gate.fill), pixels=int(gate.pixels),
                corners=[[float(a), float(b)] for a, b in gate.corners],
                bbox=[float(v) for v in gate.bbox])
            if best is None or det.confidence * max(det.size, 1e-6) > \
                    best.confidence * max(best.size, 1e-6):
                best = det
            if self.preset != "auto":
                break
        return best or Detection(frame_index=frame_index,
                                 timestamp_s=round(float(timestamp_s), 3))


def draw_overlay(bgr: np.ndarray, det: Detection) -> np.ndarray:
    """Annotated frame: bbox, corner polygon, centre, centre-line, label."""
    out = bgr.copy()
    h, w = out.shape[:2]

    def px(x, y):
        return (int(round((x + 1) * w / 2)), int(round((y + 1) * h / 2)))

    cv2.drawMarker(out, (w // 2, h // 2), (255, 255, 255),
                   cv2.MARKER_CROSS, 30, 1)
    if det.visible and len(det.bbox) == 4:
        x0, y0, x1, y1 = det.bbox
        cv2.rectangle(out, px(x0, y0), px(x1, y1),
                      (0, 165, 255) if det.clipped else (0, 255, 0), 3)
        if len(det.corners) >= 3:
            cv2.polylines(out, [np.array([px(*c) for c in det.corners], np.int32)],
                          True, (255, 255, 0), 2)
        centre = px(det.x, det.y)
        cv2.circle(out, centre, 8, (0, 0, 255), -1)
        cv2.line(out, (w // 2, h // 2), centre, (0, 0, 255), 2)
        text = (f"GATE {det.color} conf {det.confidence:.2f} "
                f"x {det.x:+.2f} y {det.y:+.2f} size {det.size:.3f}"
                f"{' CLIPPED' if det.clipped else ''}")
    else:
        text = "no gate"
    label = f"f{det.frame_index} t={det.timestamp_s:.2f}s  {text}"
    for colour, thick in (((0, 0, 0), 4), ((255, 255, 255), 1)):
        cv2.putText(out, label, (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX,
                    0.65, colour, thick)
    return out


def load_config(path: str | Path | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))
