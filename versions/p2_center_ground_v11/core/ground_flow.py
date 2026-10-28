"""Height above the ground from how the ground moves between two camera frames.

ALT counts from the start point, not the ground, so it can't say how close the road is
(the drone bounced off the valley road at gate 17 with ALT reading fine, 2026-10-26).
The camera can: between two frames, flat ground moves by one exact projective warp (a
homography) that depends on the camera's motion and its height above the plane:

    p2 ~ K R (I + t n^T / H) K^-1 p1

t is the camera's own displacement (forward from the OSD km/h, down from the ALT filter),
n the ground's normal seen from the camera (from the camera tilt and the drone's pitch),
R the pitch change between the frames, H the height above the ground. With t and n known,
the only unknowns are 1/H and the pitch change: try a grid of both, warp the first frame,
keep the pair that matches the second frame best over the ground below the horizon.

Dense optical flow was tried first and failed: low and fast, the near rows move 20-60 px
between frames 1/15 s apart and Farneback returned ~0 for them (tests/test_ground_flow.py).
The warp search has no such limit: nothing is linearised.
"""
import math

import cv2
import numpy as np

WORK = (160, 90)  # search resolution
# The game's on-screen display doesn't move with the scene, and the stick boxes sit right in
# the ground area: matched as part of it, they pull the search toward "no motion" (the 40 m
# limit, 2026-10-26). Boxes (x0, y0, x1, y1) in frame fractions, measured on 960x540 frames.
OSD = ((0.38, 0.82, 0.62, 1.0),   # stick display, bottom centre
       (0.0, 0.0, 0.15, 0.22),    # Time / Laps
       (0.86, 0.0, 1.0, 0.40),    # mode, km/h, ALT, battery
       (0.88, 0.80, 1.0, 1.0),    # damaged-drone icon
       (0.46, 0.44, 0.54, 0.56))  # centre crosshair


from core.attitude import attitude_deg  # shared with the optional flight calibration


def _intrinsics(w, h, vfov_deg):
    f = (h / 2) / math.tan(math.radians(vfov_deg) / 2)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
    return K, np.linalg.inv(K), f


def homography(inv_h, d_fwd, d_down, elev_rad, d_pitch_rad, K, Kinv):
    """Pixel map frame 1 -> frame 2 for flat ground at 1/inv_h below a camera whose axis is
    elev_rad above the horizon, moving d_fwd forward and d_down down (world), then pitching
    its axis down by d_pitch_rad. Camera axes: x right, y down, z forward."""
    ce, se = math.cos(elev_rad), math.sin(elev_rad)
    n = np.array([0.0, -ce, se])                       # world up, seen from the camera
    # camera displacement in camera-1 coordinates (world forward F, up U; down = -U)
    t = np.array([0.0, d_fwd * se + d_down * ce, d_fwd * ce - d_down * se])
    c, s = math.cos(d_pitch_rad), math.sin(d_pitch_rad)
    R = np.array([[1, 0, 0], [0, c, s], [0, -s, c]])  # axis nods down: scene moves up
    return K @ R @ (np.eye(3) + inv_h * np.outer(t, n)) @ Kinv


def estimate(prev, cur, dt, speed_ms, sink_ms, cam_elev_deg, vfov_deg=86.2, min_depression_deg=3.0,
             heights=(0.25, 40.0), n_h=48, pitch_step_deg=0.5, max_pitch_deg=6.0, osd=OSD):
    """Height above the ground (m) from two grayscale frames dt apart, or (None, why).

    speed_ms: horizontal speed; sink_ms: descent rate (+ = down); cam_elev_deg: camera axis
    above the horizon (camera tilt - deg_per_pitch x pitch). Returns (height, info); info has
    the match quality (how much better the best height fits than the worst) for gating."""
    if prev is None or cur is None or dt <= 0 or speed_ms is None:
        return None, {"why": "no input"}
    if speed_ms < 0.5 and abs(sink_ms or 0.0) < 0.3:
        return None, {"why": "too little motion"}
    a = cv2.resize(prev, WORK, interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(cur, WORK, interpolation=cv2.INTER_AREA).astype(np.float32)
    w, h = WORK
    K, Kinv, f = _intrinsics(w, h, vfov_deg)
    e = math.radians(cam_elev_deg)
    rows = np.arange(h) + 0.5 - h / 2
    depression = np.arctan(rows / f) - e
    mask = np.zeros((h, w), np.float32)
    mask[depression >= math.radians(min_depression_deg)] = 1.0
    for x0, y0, x1, y1 in osd:
        mask[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = 0.0
    if mask.sum() < 0.1 * w * h:
        return None, {"why": "little ground in view"}
    d_fwd, d_down = speed_ms * dt, (sink_ms or 0.0) * dt
    inv_hs = 1.0 / np.geomspace(heights[1], heights[0], n_h)
    pitches = np.radians(np.arange(-max_pitch_deg, max_pitch_deg + 1e-9, pitch_step_deg))
    ones = np.ones_like(a)
    best = (np.inf, None, None)
    scores = np.full((n_h, len(pitches)), np.inf)
    for i, ih in enumerate(inv_hs):
        for j, dp in enumerate(pitches):
            M = homography(ih, d_fwd, d_down, e, dp, K, Kinv)
            warped = cv2.warpPerspective(a, M, (w, h), flags=cv2.INTER_LINEAR)
            valid = cv2.warpPerspective(ones, M, (w, h), flags=cv2.INTER_NEAREST) * mask
            n = valid.sum()
            if n < 0.05 * w * h:
                continue
            diff = (warped - b) * valid
            score = float((diff * diff).sum() / n)
            scores[i, j] = score
            if score < best[0]:
                best = (score, i, j)
    if best[1] is None:
        return None, {"why": "no overlap"}
    i, j = best[1], best[2]
    col = scores[:, j][np.isfinite(scores[:, j])]
    contrast = float((col.max() - best[0]) / max(col.max(), 1e-6)) if len(col) else 0.0
    return float(1.0 / inv_hs[i]), {"pitch_change_deg": float(np.degrees(pitches[j])), "contrast": contrast,
                                    "score": best[0], "edge": i in (0, n_h - 1)}


def estimate_fast(prev, cur, dt, speed_ms, sink_ms, cam_elev_deg, vfov_deg=86.2, size=(160, 90),
                  min_depression_deg=3.0, heights=(0.25, 40.0), osd=OSD):
    """The same search coarse-to-fine, for the flight loop: 16 heights x 9 pitch changes, then
    9 x 7 around the best: ~200 warps instead of 1,200, ~17 ms. At 80x45 it read 3.2x ALT on
    real frames where the full search read 1.8x (too little ground texture left); at 160x90
    it matches (1.79x). Returns (height, info) like estimate(); info["edge"] marks a best
    height at the ends of the range (the "no motion" or "no fit" answers, not a measurement)."""
    if prev is None or cur is None or dt <= 0 or speed_ms is None:
        return None, {"why": "no input"}
    if speed_ms < 0.5 and abs(sink_ms or 0.0) < 0.3:
        return None, {"why": "too little motion"}
    a = cv2.resize(prev, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(cur, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    w, h = size
    K, Kinv, f = _intrinsics(w, h, vfov_deg)
    e = math.radians(cam_elev_deg)
    depression = np.arctan((np.arange(h) + 0.5 - h / 2) / f) - e
    mask = np.zeros((h, w), np.float32)
    mask[depression >= math.radians(min_depression_deg)] = 1.0
    for x0, y0, x1, y1 in osd:
        mask[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = 0.0
    if mask.sum() < 0.1 * w * h:
        return None, {"why": "little ground in view"}
    d_fwd, d_down = speed_ms * dt, (sink_ms or 0.0) * dt
    ones = np.ones_like(a)

    def score(inv_h, dp):
        M = homography(inv_h, d_fwd, d_down, e, dp, K, Kinv)
        valid = cv2.warpPerspective(ones, M, (w, h), flags=cv2.INTER_NEAREST) * mask
        n = valid.sum()
        if n < 0.05 * w * h:
            return np.inf
        diff = (cv2.warpPerspective(a, M, (w, h), flags=cv2.INTER_LINEAR) - b) * valid
        return float((diff * diff).sum() / n)

    hs = np.geomspace(heights[1], heights[0], 16)
    ps = np.radians(np.arange(-6.0, 6.0 + 1e-9, 1.5))
    coarse = np.array([[score(1.0 / H, p) for p in ps] for H in hs])
    if not np.isfinite(coarse).any():
        return None, {"why": "no overlap"}
    i, j = np.unravel_index(np.argmin(coarse), coarse.shape)
    col = coarse[:, j][np.isfinite(coarse[:, j])]
    contrast = float((col.max() - coarse[i, j]) / max(col.max(), 1e-6))
    fh = np.geomspace(hs[max(i - 1, 0)], hs[min(i + 1, len(hs) - 1)], 9)
    fp = ps[j] + np.radians(np.arange(-1.5, 1.5 + 1e-9, 0.5))
    fine = np.array([[score(1.0 / H, p) for p in fp] for H in fh])
    k, m = np.unravel_index(np.argmin(fine), fine.shape)
    height = float(fh[k])
    edge = height <= heights[0] * 1.15 or height >= heights[1] * 0.85
    return height, {"pitch_change_deg": float(np.degrees(fp[m])), "contrast": contrast, "edge": edge}


class GroundWarn:
    """Filtered height above the ground, and a too-low warning, from estimate_fast() results.

    A reading counts only at speed >= min_speed (below ~15 km/h most real readings were junk,
    2026-10-26) and when it isn't an edge answer. Readings are multiplied by `scale`: at
    racing pitch the estimate ran a steady ~1.8x ALT on two flights (1.77, 1.85), cause not
    found, so 0.55 is an empirical calibration, not physics. The height is the median of the
    readings of the last window_s; it warns when that is under warn_m on at least min_n."""

    def __init__(self, scale=0.55, min_speed=15 / 3.6, window_s=0.6, warn_m=0.8, min_n=2):
        self.scale, self.min_speed, self.window_s = scale, min_speed, window_s
        self.warn_m, self.min_n = warn_m, min_n
        self.readings = []  # (t, corrected height)

    def add(self, t, est, info, speed_ms):
        if est is None or speed_ms is None or speed_ms < self.min_speed or (info or {}).get("edge"):
            return
        self.readings.append((t, est * self.scale))

    def recent(self, t):
        self.readings = [(tr, h) for tr, h in self.readings if t - tr <= self.window_s]
        return [h for _, h in self.readings]

    def height(self, t):
        hs = self.recent(t)
        return float(np.median(hs)) if len(hs) >= self.min_n else None

    def warning(self, t):
        h = self.height(t)
        return h is not None and h < self.warn_m


class GroundWorker:
    """Runs estimate_fast in a background thread so the 30 Hz flight loop never waits on it
    (~17 ms each; OpenCV releases the GIL while warping). One job at a time: submit() drops a
    job while the last one is still running; take() returns finished results, oldest first."""

    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self._busy = False
        self._done = []
        self._threading = threading

    def submit(self, t, prev, cur, dt, speed_ms, sink_ms, cam_elev_deg):
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def run():
            try:
                est, info = estimate_fast(prev, cur, dt, speed_ms, sink_ms, cam_elev_deg)
            except Exception as e:  # never let the estimate stop a flight
                est, info = None, {"why": f"error: {e}"}
            with self._lock:
                self._done.append((t, est, info, speed_ms))
                self._busy = False
        self._threading.Thread(target=run, daemon=True).start()
        return True

    def take(self):
        with self._lock:
            out, self._done = self._done, []
        return out
