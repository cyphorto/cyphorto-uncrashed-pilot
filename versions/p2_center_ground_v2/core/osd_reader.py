"""Read the altitude number off the OSD with template matching.

No Tesseract needed. The game's OSD font never changes, so the reader learns it from a few
labelled screenshots (tools/calibrate_osd.py). It then matches each character against those
templates. If any character is doubtful, the reading is rejected (returns None). A wrong
number is worse than no number.
"""
import re
from pathlib import Path

import cv2
import numpy as np

GLYPH_W, GLYPH_H = 20, 28
SAFE_NAMES = {".": "dot", "-": "minus", "/": "slash", ":": "colon"}
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def label_to_name(label):
    return SAFE_NAMES.get(label, label)


def name_to_label(name):
    for k, v in SAFE_NAMES.items():
        if v == name:
            return k
    return name


def binarize(img_bgr, cfg):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    if cfg.get("text_is_dark"):
        gray = 255 - gray
    thr = int(cfg.get("threshold", 0))
    if thr > 0:
        _, b = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)
    else:
        _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b


def segment(img_bgr, cfg):
    """Split the OSD crop into characters, left to right.

    Returns a list of (kind, glyph) where kind is 'glyph', 'dot' or 'minus' and glyph is a
    normalized GLYPH_H x GLYPH_W float image (None for dot/minus).
    """
    b = binarize(img_bgr, cfg)
    n, _, stats, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    comps = [tuple(int(v) for v in stats[i, :4]) for i in range(1, n) if stats[i, 4] >= 2]
    if not comps:
        return []
    min_h = int(cfg.get("min_glyph_height_px", 6))
    tall = [c for c in comps if c[3] >= min_h]
    if not tall:
        return []
    H = max(c[3] for c in tall)
    glyphs = [list(c) for c in tall if c[3] >= 0.5 * H]
    line_top = min(c[1] for c in glyphs)
    line_bot = max(c[1] + c[3] for c in glyphs)

    # merge pieces of one character that overlap horizontally (broken strokes)
    glyphs.sort(key=lambda c: c[0])
    merged = []
    for c in glyphs:
        if merged:
            m = merged[-1]
            overlap = min(m[0] + m[2], c[0] + c[2]) - max(m[0], c[0])
            if overlap > 0.5 * min(m[2], c[2]):
                x0, y0 = min(m[0], c[0]), min(m[1], c[1])
                x1, y1 = max(m[0] + m[2], c[0] + c[2]), max(m[1] + m[3], c[1] + c[3])
                merged[-1] = [x0, y0, x1 - x0, y1 - y0]
                continue
        merged.append(c)

    items = [("glyph", c) for c in merged]
    for c in comps:
        x, y, w, h = c
        if h >= 0.5 * H:
            continue
        cy = y + h / 2
        if h <= 0.35 * H and w <= 0.6 * H and y + h >= line_bot - 0.3 * H and cy > line_top + 0.5 * H:
            items.append(("dot", list(c)))
        elif h <= 0.3 * H and w >= 0.35 * H and line_top + 0.25 * H < cy < line_bot - 0.25 * H:
            items.append(("minus", list(c)))
    items.sort(key=lambda it: it[1][0])

    out = []
    canvas_w = int(np.ceil(0.9 * H))
    for kind, (x, y, w, h) in items:
        if kind != "glyph":
            out.append((kind, None))
            continue
        crop = b[y:y + h, x:x + w]
        cw = max(canvas_w, w)
        canvas = np.zeros((line_bot - line_top, cw), np.uint8)
        ox = (cw - w) // 2
        oy = y - line_top
        canvas[oy:oy + h, ox:ox + w] = crop
        g = cv2.resize(canvas, (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        out.append(("glyph", g))
    return out


def _ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 1e-9 else 0.0


class OSDReader:
    def __init__(self, osd_cfg, templates_dir):
        self.cfg = osd_cfg
        self.dir = Path(templates_dir)
        self.templates = self._load()
        lo, hi = osd_cfg.get("valid_range_m", [-1e9, 1e9])
        self.lo, self.hi = float(lo), float(hi)

    def _load(self):
        t = {}
        if self.dir.exists():
            for p in sorted(self.dir.glob("*.png")):
                label = name_to_label(p.stem.split("_")[0])
                img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                img = cv2.resize(img, (GLYPH_W, GLYPH_H)).astype(np.float32) / 255.0
                t.setdefault(label, []).append(img)
        return t

    @property
    def ready(self):
        return all(str(d) in self.templates for d in range(10))

    def missing(self):
        return [str(d) for d in range(10) if str(d) not in self.templates]

    def classify(self, g):
        best, best_s = "?", -1.0
        for label, imgs in self.templates.items():
            for t in imgs:
                s = _ncc(g, t)
                if s > best_s:
                    best, best_s = label, s
        return best, best_s

    def read_text(self, img_bgr):
        """Returns (text, min_score)."""
        chars, scores = [], []
        for kind, g in segment(img_bgr, self.cfg):
            if kind == "dot":
                chars.append(".")
            elif kind == "minus":
                chars.append("-")
            else:
                label, s = self.classify(g)
                chars.append(label)
                if label.isdigit() or label in ".-":
                    scores.append(s)
        return "".join(chars), (min(scores) if scores else 0.0)

    def read_height(self, img_bgr):
        """Height in metres, or None when unsure."""
        text, score = self.read_text(img_bgr)
        if score < float(self.cfg.get("min_score", 0.6)):
            return None
        m = _NUMBER.search(text.replace(" ", ""))
        if not m:
            return None
        try:
            v = float(m.group(0))
        except ValueError:
            return None
        if not (self.lo <= v <= self.hi):
            return None
        return v


def save_template(templates_dir, label, glyph, max_per_label=8):
    d = Path(templates_dir)
    d.mkdir(parents=True, exist_ok=True)
    name = label_to_name(label)
    existing = sorted(d.glob(f"{name}_*.png"))
    if len(existing) >= max_per_label:
        return False
    idx = 0
    while (d / f"{name}_{idx}.png").exists():
        idx += 1
    cv2.imwrite(str(d / f"{name}_{idx}.png"), (glyph * 255).astype(np.uint8))
    return True
