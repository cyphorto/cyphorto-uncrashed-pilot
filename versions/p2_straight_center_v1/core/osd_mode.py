"""Read which flight mode Uncrashed shows top right: ANGLE, or something shorter after a crash.

When the drone hits something hard the OSD mode changes from "ANGLE" to "3D" and a
damaged-drone icon appears bottom right (2026-10-24). In 3D mode the throttle centre is
zero thrust, so the pilot's normal 0.2-0.3 throttle pushes the drone into the ground and
anything over 0.5 launches it. The flight has to end and the race restart.

The mode text is right-aligned, so its width tells the modes apart without templates:
in MODE_BOX "ANGLE" spans ~0.60 of the box width, "ACRO" ~0.49 and "3D" ~0.22.
"""
import numpy as np

from .alt_reader import binarize

MODE_BOX = (0.86, 0.055, 0.985, 0.115)  # fractions of the frame, measured at 960x540 and 1920x1080
RIGHT_EDGE = 0.91                        # text's right end, as a fraction of the box width


def mode_width(frame):
    """Width of the mode text as a fraction of MODE_BOX, or None if it doesn't look like
    right-aligned text (nothing there, or a gate frame or cloud edge in the box)."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = MODE_BOX
    c = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    b = binarize(c)
    cols = np.where(b.any(axis=0))[0]
    if len(cols) == 0:
        return None
    left, right = cols.min() / b.shape[1], (cols.max() + 1) / b.shape[1]
    if abs(right - RIGHT_EDGE) > 0.04:
        return None
    return round(right - left, 3)


DAMAGE_BOX = (0.895, 0.86, 0.99, 0.99)  # the white drone icon shown after a hit


def damage_icon(frame):
    """Share of near-white pixels where the damaged-drone icon appears (bottom right):
    ~0.07 while it shows, ~0 otherwise in 5,185 saved flight frames. It means "took a hit";
    the drone sometimes flies on (2026-10-24), so it only shortens the stuck check."""
    import cv2
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = DAMAGE_BOX
    c = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
    return float((cv2.inRange(hsv, (0, 0, 225), (179, 40, 255)) > 0).mean())


def is_angle(width):
    """True for ANGLE (0.60), False for another mode (ACRO 0.49, 3D 0.22), None when unreadable."""
    if width is None or width > 0.75:
        return None
    if 0.68 < width <= 0.75:
        return None
    return width >= 0.55
