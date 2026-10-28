"""Find the next gate in an Uncrashed FPV frame.

Uncrashed draws the next gate in saturated green and later gates in magenta.
The detector thresholds that green in HSV, picks the largest gate-shaped blob,
merges nearby fragments (the frame is often split by grass or the drone's own
props), and reports where the gate is and how big it looks.

Image convention for outputs:
    x: -1 at the left edge, +1 at the right edge, 0 at the centre.
    y: -1 at the top edge,  +1 at the bottom edge, 0 at the centre.
    size: sqrt(hull area) / frame width. Grows as the drone approaches.
"""
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

DEFAULTS = {
    "work_width": 640,          # frames are downscaled to this width first
    # OpenCV HSV: H 0-179, S/V 0-255. Gate green measured at H 57-66; the
    # green racing-line guide is H 41-52, so the lower bound sits between them.
    "hsv_low": [55, 150, 140],
    "hsv_high": [72, 255, 255],
    "close_px": 5,              # morphological close kernel, at work_width
    "group_px": 15,             # fragments closer than this are judged as one shape
    "min_area_px": 12,          # smallest blob kept, at work_width
    "max_aspect": 6.0,          # a blob longer than this ratio ...
    "thin_px": 3.5,             # ... and thinner than this (px at work_width) is a line, not a gate
    "edge_px": 2,               # a hull this close to the border counts as clipped
    # Far gates are washed out by haze (gate 17 down the canyon: H ~53, S ~65 on
    # 2026-10-25) and fail the strict green. When the strict pass finds nothing usable,
    # a relaxed pass takes the single most gate-like (squarish, hollow) bright blob.
    "far_below_size": 0.02,     # strict result smaller than this (or none): try relaxed
    "far_hsv_low": [50, 40, 185],
    "far_hsv_high": [75, 255, 255],
    "far_max_aspect": 2.5,
    "far_max_fill": 0.7,
    # Later gates (magenta), for looking ahead: measured H 156-166, S >= 94, V >= 128 on
    # raw frames of Roadtrip, 2026-10-26. Kept apart per gate (a row of far gates sits
    # close together), so fragments are grouped over fewer pixels than the green.
    "future_hsv_low": [150, 80, 110],
    "future_hsv_high": [172, 255, 255],
    "future_group_px": 5,
    "future_min_area_px": 10,
}


@dataclass
class Gate:
    visible: bool
    x: float = 0.0
    y: float = 0.0
    size: float = 0.0
    clipped: bool = False
    aspect: float = 0.0
    fill: float = 0.0           # green pixels / hull area: low = hollow frame seen whole
    pixels: int = 0
    corners: list = field(default_factory=list)  # [[x, y], ...] normalised, up to 4 when found
    bbox: list = field(default_factory=list)     # [x0, y0, x1, y1] normalised

    def row(self):
        d = asdict(self)
        d["corners"] = ";".join(f"{x:.4f},{y:.4f}" for x, y in self.corners)
        d["bbox"] = ",".join(f"{v:.4f}" for v in self.bbox)
        return d


FIELDS = list(Gate(False).row().keys())


class GateDetector:
    def __init__(self, cfg=None):
        self.cfg = dict(DEFAULTS, **(cfg or {}))
        k = int(self.cfg["close_px"])
        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)) if k > 1 else None

    def mask(self, bgr, low=None, high=None):
        """Green mask at work resolution, plus the resized frame size."""
        h, w = bgr.shape[:2]
        ww = int(self.cfg["work_width"])
        if ww and w != ww:
            bgr = cv2.resize(bgr, (ww, max(1, round(h * ww / w))), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        m = cv2.inRange(hsv, np.array(low or self.cfg["hsv_low"], np.uint8),
                        np.array(high or self.cfg["hsv_high"], np.uint8))
        if self.kernel is not None:
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, self.kernel)
        return m

    def detect(self, bgr):
        gate = self._detect(self.mask(bgr), merge=True)
        if gate.visible and gate.size >= self.cfg["far_below_size"]:
            return gate
        far = self._detect(self.mask(bgr, self.cfg["far_hsv_low"], self.cfg["far_hsv_high"]), merge=False)
        return far if far.visible and far.size > (gate.size if gate.visible else 0.0) else gate

    def detect_future(self, bgr, limit=6):
        """Later gates (magenta), each one separately, biggest (usually nearest) first."""
        m = self.mask(bgr, self.cfg["future_hsv_low"], self.cfg["future_hsv_high"])
        blobs = [b for b in self._blobs(m, self.cfg["future_group_px"], self.cfg["future_min_area_px"])
                 if self._gate_like(b)]
        gates = [self._gate(b, m.shape) for b in blobs]
        return sorted(gates, key=lambda g: -g.size)[:limit]

    def _blobs(self, m, group_px, min_area):
        """Pixel groups of the mask, without thin line fragments. Nearby fragments are grouped
        before judging shape: a far gate against grass often breaks into separate thin posts
        and bars, which only look like a gate once grouped. Shape is still measured on the
        undilated pixels."""
        g = int(group_px)
        grouped = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (g, g))) if g > 1 else m
        n, labels = cv2.connectedComponents(grouped, connectivity=8)
        labels[m == 0] = 0
        blobs = []
        for i in range(1, n):
            ys, xs = np.nonzero(labels == i)
            area = len(xs)
            if area < min_area:
                continue
            pts = np.column_stack([xs, ys]).astype(np.int32)
            (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
            long_side = max(rw, rh, 1.0)
            aspect = long_side / max(1.0, min(rw, rh))
            thickness = area / long_side
            if aspect > self.cfg["max_aspect"] and thickness < self.cfg["thin_px"]:
                continue  # thin line fragment
            blobs.append(pts)
        return blobs

    def _detect(self, m, merge):
        """merge: every blob is a piece of the next gate (strict green). Otherwise keep only
        the single most gate-like blob (relaxed green also catches pale scenery)."""
        blobs = self._blobs(m, self.cfg["group_px"], self.cfg["min_area_px"])
        if not blobs:
            return Gate(False)
        if not merge:
            blobs = [b for b in blobs if self._gate_like(b)]
            if not blobs:
                return Gate(False)
            blobs = [max(blobs, key=lambda b: cv2.contourArea(cv2.convexHull(b)))]
        # Only the next gate is drawn in this green, so every surviving blob is a
        # piece of it: whole frame far away, or edge strips plus the arrow up close.
        return self._gate(np.vstack(blobs), m.shape)

    def _gate(self, pts, shape):
        H, W = shape
        hull = cv2.convexHull(pts)
        hull_area = max(1.0, cv2.contourArea(hull))
        M = cv2.moments(hull)
        if M["m00"] > 0:
            cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
        else:
            cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
        (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
        aspect = max(rw, rh) / max(1.0, min(rw, rh))
        e = self.cfg["edge_px"]
        hx, hy = hull[:, 0, 0], hull[:, 0, 1]
        clipped = bool(hx.min() <= e or hy.min() <= e or hx.max() >= W - 1 - e or hy.max() >= H - 1 - e)

        quad = cv2.approxPolyDP(hull, 0.04 * cv2.arcLength(hull, True), True)[:, 0, :]
        while len(quad) > 4:  # drop the vertex whose removal loses the least area
            j = max(range(len(quad)), key=lambda k: cv2.contourArea(np.delete(quad, k, 0)))
            quad = np.delete(quad, j, 0)

        nx = lambda v: 2.0 * v / W - 1.0
        ny = lambda v: 2.0 * v / H - 1.0
        return Gate(
            visible=True,
            x=nx(cx), y=ny(cy),
            size=float(np.sqrt(hull_area) / W),
            clipped=clipped,
            aspect=float(aspect),
            fill=float(len(pts) / hull_area),
            pixels=int(len(pts)),
            corners=[[nx(px), ny(py)] for px, py in quad],
            bbox=[nx(hx.min()), ny(hy.min()), nx(hx.max()), ny(hy.max())],
        )


    def _gate_like(self, pts):
        """Squarish and hollow, like a gate frame (not a solid patch of pale grass)."""
        hull = cv2.convexHull(pts)
        area = max(1.0, cv2.contourArea(hull))
        (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
        aspect = max(rw, rh) / max(1.0, min(rw, rh))
        return aspect <= self.cfg["far_max_aspect"] and len(pts) / area <= self.cfg["far_max_fill"] and area >= 16


def draw(bgr, gate, label=""):
    """Overlay for review: hull box, centre, crosshair at screen centre."""
    out = bgr.copy()
    h, w = out.shape[:2]
    px = lambda x, y: (int(round((x + 1) * w / 2)), int(round((y + 1) * h / 2)))
    cv2.drawMarker(out, (w // 2, h // 2), (255, 255, 255), cv2.MARKER_CROSS, 30, 1)
    if gate.visible:
        x0, y0, x1, y1 = gate.bbox
        cv2.rectangle(out, px(x0, y0), px(x1, y1), (0, 255, 255) if gate.clipped else (255, 0, 255), 2)
        if len(gate.corners) >= 3:
            cv2.polylines(out, [np.array([px(*c) for c in gate.corners], np.int32)], True, (255, 255, 0), 2)
        c = px(gate.x, gate.y)
        cv2.circle(out, c, 7, (0, 0, 255), -1)
        cv2.line(out, (w // 2, h // 2), c, (0, 0, 255), 2)
        text = f"x {gate.x:+.2f}  y {gate.y:+.2f}  size {gate.size:.3f}{'  CLIPPED' if gate.clipped else ''}"
    else:
        text = "no gate"
    for col, th in (((0, 0, 0), 4), ((255, 255, 255), 1)):
        cv2.putText(out, f"{label} {text}", (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, th)
    return out
