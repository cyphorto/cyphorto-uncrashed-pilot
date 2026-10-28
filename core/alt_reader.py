"""Read Uncrashed's "ALT 12.3 m" readout from a full screen frame.

The readout is semi-transparent white text, so its brightness follows the
background (about 200 over dark ground, 245 over sky). A fixed threshold fails;
a white top-hat (text brighter than its surroundings) followed by Otsu works on
both. The number is right-aligned against the "m", so its left edge and the
"ALT" label move as digits are added: the reader keeps only full-height
characters (digits) plus the decimal point, and drops "ALT" and "m" by size.

Everything is scaled to a 1280-wide frame first, so the same templates work on
live 1920x1080 captures and on the 1280x720 recordings.

Returns None whenever it is unsure. A wrong number is worse than no number.
"""
import re
from pathlib import Path

import cv2
import numpy as np

REF_W = 1280
# Readout box as fractions of the frame (measured at 1280x720: x 1150-1250, y 165-200)
DEFAULT_BOX = (0.8984, 0.2292, 0.9766, 0.2778)
GLYPH_W, GLYPH_H = 16, 24
_FORMAT = re.compile(r"^-?\d{1,3}\.\d$")


def crop(frame, box=DEFAULT_BOX):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    c = frame[int(y0 * h):int(round(y1 * h)), int(x0 * w):int(round(x1 * w))]
    s = REF_W / w
    if abs(s - 1) > 1e-3:
        c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return c


def binarize(c):
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY) if c.ndim == 3 else c
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    t, b = cv2.threshold(th, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if t < 15:  # nothing stands out: no text, only noise
        return np.zeros_like(b)
    return b


def segment(c):
    """Characters left to right: list of ('d', glyph) or ('.', None)."""
    b = binarize(c)
    n, _, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    # The readout never touches the crop border. A gate frame behind it does, and being
    # taller than the digits it used to set H and get every real digit thrown away.
    ih, iw = b.shape
    comps = [tuple(int(v) for v in st[i, :5]) for i in range(1, n) if st[i, 4] >= 3
             and st[i, 0] > 0 and st[i, 1] > 0 and st[i, 0] + st[i, 2] < iw and st[i, 1] + st[i, 3] < ih]
    if not comps:
        return []
    H = max(cc[3] for cc in comps)
    if H < 8:
        return []
    tall = [cc for cc in comps if cc[3] >= 0.8 * H]
    top = int(np.median([cc[1] for cc in tall]))
    bot = int(np.median([cc[1] + cc[3] for cc in tall]))
    digits = [cc for cc in tall if abs(cc[1] - top) <= 2 and abs(cc[1] + cc[3] - bot) <= 2]
    if not digits:
        return []
    x_lo, x_hi = min(cc[0] for cc in digits), max(cc[0] + cc[2] for cc in digits)
    items = [("d", cc) for cc in digits]
    mid = (top + bot) / 2
    for cc in comps:
        x, y, w, h, a = cc
        if (h <= 0.3 * H and w <= 0.3 * H and abs((y + h) - bot) <= 2
                and x_lo < x + w / 2 < x_hi):
            items.append((".", cc))
        elif (h <= 0.25 * H and 0.25 * H <= w <= 0.7 * H and abs(y + h / 2 - mid) <= 0.2 * H
              and 0 <= x_lo - (x + w) <= 0.3 * H):
            # Minus sign just left of the first digit: a real one sits 2-3 px (0.13-0.2 H)
            # away. Above 10 m the "T" of ALT ends 9 px away, and its crossbar alone read
            # as a minus at 0.6 H ("-17.0" for 17.0, 2026-10-24).
            items.append(("-", cc))
    items.sort(key=lambda it: it[1][0])
    # A digit hidden by the background leaves a wide hole ("16.2" read as "1.2").
    # Normal spacing in 1,497 recorded frames was at most 0.46 digit heights.
    for (_, a), (_, b2) in zip(items, items[1:]):
        if b2[0] - (a[0] + a[2]) > 0.7 * H:
            return []
    out = []
    for kind, (x, y, w, h, a) in items:
        if kind in ".-":
            out.append((kind, None))
            continue
        g = b[top:bot, x:x + w]
        cw = max(w, int(round(0.62 * (bot - top))))  # pad narrow "1" to a normal cell
        canvas = np.zeros((bot - top, cw), np.uint8)
        canvas[:, (cw - w) // 2:(cw - w) // 2 + w] = g
        out.append(("d", cv2.resize(canvas, (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255))
    return out


def _ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 1e-9 else 0.0


class AltReader:
    # Live frames match the recording-made templates at only ~0.75-0.82, but the right
    # digit still leads the runner-up by 0.2+. Judge by the lead, with a low floor.
    # On 1,497 recorded frames this gave 0 wrong readings on the labelled set.
    # Live templates now exist for most digits and match at 0.96+, but live 3 and 8 are
    # only ~0.14 apart, so a near-perfect match needs a smaller lead (strong_*).
    def __init__(self, templates_dir, box=DEFAULT_BOX, min_score=0.55, min_margin=0.15,
                 strong_score=0.9, strong_margin=0.08, fmt=_FORMAT):
        self.box = box
        self.min_score = min_score
        self.min_margin = min_margin
        self.strong_score = strong_score
        self.strong_margin = strong_margin
        self.fmt = fmt  # what a complete reading looks like (core.speed_reader reuses this class)
        self.templates = {}
        d = Path(templates_dir)
        for p in sorted(d.glob("*.png")) if d.exists() else []:
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                self.templates.setdefault(p.stem.split("_")[0], []).append(
                    cv2.resize(img, (GLYPH_W, GLYPH_H)).astype(np.float32) / 255)

    @property
    def ready(self):
        return all(str(k) in self.templates for k in range(10))

    def missing(self):
        return [str(k) for k in range(10) if str(k) not in self.templates]

    def classify(self, g):
        scores = sorted(((max(_ncc(g, t) for t in ts), lab) for lab, ts in self.templates.items()), reverse=True)
        best, lab = scores[0]
        second = scores[1][0] if len(scores) > 1 else -1.0
        return lab, best, best - second

    def read(self, frame):
        """(metres or None, text, worst score)."""
        return self.read_crop(crop(frame, self.box))

    def read_crop(self, image):
        """Read a saved, reference-size ALT crop (no second crop or resize)."""
        if not self.ready:
            return None, "", 0.0
        chars, worst = [], 1.0
        for kind, g in segment(image):
            if kind in ".-":
                chars.append(kind)
                continue
            lab, s, margin = self.classify(g)
            worst = min(worst, s)
            strong = s >= self.strong_score and margin >= self.strong_margin
            if not strong and (s < self.min_score or margin < self.min_margin):
                return None, "".join(chars) + "?", s
            chars.append(lab)
        text = "".join(chars)
        if not self.fmt.match(text):
            return None, text, worst
        return float(text), text, worst


def save_glyphs(frame, label, templates_dir, box=DEFAULT_BOX, max_per_digit=6):
    """Learn from one frame whose readout shows `label` (e.g. "21.4"). Returns glyphs saved."""
    return save_crop_glyphs(crop(frame, box), label, templates_dir, max_per_digit)


def save_crop_glyphs(image, label, templates_dir, max_per_digit=32):
    """Add templates from a manually verified saved ALT crop."""
    if not _FORMAT.fullmatch(label):
        raise ValueError("Expected an altitude label such as 1.6")
    segs = segment(image)
    if len(segs) != len(label) or any((k == "d") != ch.isdigit() for (k, _), ch in zip(segs, label)):
        return -1
    d = Path(templates_dir)
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for (k, g), ch in zip(segs, label):
        if k != "d":
            continue
        existing = list(d.glob(f"{ch}_*.png"))
        if len(existing) >= max_per_digit:
            continue
        i = 0
        while (d / f"{ch}_{i}.png").exists():
            i += 1
        cv2.imwrite(str(d / f"{ch}_{i}.png"), (g * 255).astype(np.uint8))
        n += 1
    return n
