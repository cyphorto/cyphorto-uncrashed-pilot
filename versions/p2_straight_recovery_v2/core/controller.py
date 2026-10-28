"""Height controller: hover feed-forward + P on height + D on vertical-speed error
+ optional acceleration feed-forward + a bounded integral that only learns within i_zone_m
and once no planned move (MoveProfile) has been under way for i_settle_s; tracking the
guidance's climb (reference.Track) counts as not moving. Every term is returned separately so it can be logged."""

import math

G = 9.81


class AltitudeController:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.i_term = 0.0
        self.still_for = 0.0

    def update(self, dt, h, v, h_ref, v_ref, a_ref, ref_moving):
        c = self.cfg
        hover = float(c["hover"])
        e = h_ref - h
        ev = v_ref - v
        u_ff = hover
        u_aff = (a_ref * hover / G) if c.get("accel_ff", True) else 0.0
        u_p = float(c["kp"]) * e
        u_d = float(c["kd"]) * ev
        ki = float(c.get("ki", 0.0))
        self.still_for = 0.0 if ref_moving else self.still_for + dt
        learning = self.still_for >= float(c.get("i_settle_s", 1.0))
        if ki > 0 and learning and abs(e) < float(c.get("i_zone_m", 1.5)):
            self.i_term += ki * e * dt
            lim = float(c.get("i_max", 0.05))
            self.i_term = max(-lim, min(lim, self.i_term))
        u_i = self.i_term
        u_raw = u_ff + u_aff + u_p + u_d + u_i
        u = max(float(c["u_min"]), min(float(c["u_max"]), u_raw))
        sat = u != u_raw
        return u, {"e": e, "ev": ev, "u_ff": u_ff, "u_aff": u_aff, "u_p": u_p,
                   "u_d": u_d, "u_i": u_i, "u_raw": u_raw, "sat": int(sat)}


def tilt_feedforward(base, pitch_att, roll_stick, deg_per_unit, max_deg=60.0):
    """Extra throttle to hold height while tilted: thrust ~ throttle, and only its vertical
    part (cos of the tilt) holds the drone up, so hovering at tilt t needs base / cos(t).
    pitch_att, roll_stick: attitude in stick units (ANGLE mode: deg_per_unit degrees each).
    At pitch 0.7 (~35 deg) that is +22% of hover; without it the height loop chased the
    shortfall and the drone bobbed ~1 m into gate 9 (x2 logs 20261026_193927, 2026-10-26)."""
    tp = math.radians(min(max_deg, deg_per_unit * abs(pitch_att)))
    tr = math.radians(min(max_deg, deg_per_unit * abs(roll_stick)))
    return base * (1.0 / (math.cos(tp) * math.cos(tr)) - 1.0)


def bounced(v, u_prev, u_low_prev, status, v_min=0.8, slack=0.02):
    """The drone moved up faster than v_min (m/s) on a trusted ALT reading while the last
    throttle was at the bottom of its band: nothing but the ground pushes it up like that.
    In the valley at gate 17 (x5 logs 20261026_200413, 129-167 s) the target sat ~0.5 m
    above the road; every cut to the band's floor ended on the road and the drone bounced
    for 40 s. The 1 s "ALT doesn't move" ground check never fired: a bounce never holds still."""
    return (status in ("ok", "skip") and v > v_min and u_prev is not None and u_low_prev is not None
            and u_prev <= u_low_prev + slack)
