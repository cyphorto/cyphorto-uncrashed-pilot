"""Abort rules shared by every mode. Any abort -> minimum throttle, run fails."""


class Safety:
    def __init__(self, cfg):
        self.stale_s = float(cfg["stale_s"])
        self.ceiling = float(cfg["ceiling_m"])
        self.sat_abort_s = float(cfg["sat_abort_s"])
        self.ground_m = float(cfg["ground_m"])
        self.reset(0.0)

    def reset(self, t_now):
        self.sat_since = None
        self.reason = None
        self.ground_contact = False
        self.start_t = t_now

    def check(self, t_now, last_good_t, h_filt, sat, closed_loop):
        """Returns an abort reason string, or None."""
        if self.reason:
            return self.reason
        ref_t = last_good_t if last_good_t is not None else self.start_t
        if t_now - ref_t > self.stale_s:
            self.reason = f"no fresh OSD reading for {t_now - ref_t:.2f}s"
        elif h_filt is not None and h_filt > self.ceiling:
            self.reason = f"filtered height {h_filt:.2f}m above ceiling {self.ceiling}m"
        elif closed_loop and sat:
            if self.sat_since is None:
                self.sat_since = t_now
            elif t_now - self.sat_since >= self.sat_abort_s:
                self.reason = f"throttle saturated for {self.sat_abort_s}s"
        else:
            self.sat_since = None
        return self.reason

    def note_reading(self, raw, airborne):
        if airborne and raw is not None and raw <= self.ground_m:
            self.ground_contact = True
