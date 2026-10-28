"""Height / vertical-speed estimate from OSD readings.

- Each reading is placed at the time it was ON SCREEN (grab time minus the game's render latency),
  then predicted forward to 'now', so observation age is compensated rather than only logged.
- Implausible jumps (e.g. 3.0 misread as 30) are rejected. If several rejected readings in a row
  agree with each other, the filter accepts that the height really changed and resets to them.
"""
import math


class HeightKF:
    def __init__(self, cfg, extra_latency_s=0.0):
        self.q = float(cfg.get("accel_noise", 4.0)) ** 2
        self.r = float(cfg.get("meas_noise_m", 0.05)) ** 2
        self.gate_sigma = float(cfg.get("gate_sigma", 4.0))
        self.gate_floor = float(cfg.get("gate_floor_m", 0.3))
        self.reaccept_after = int(cfg.get("reaccept_after", 3))
        # ...and for this long. At the 50 Hz window-capture rate, 3 readings is 60 ms: a
        # flickering misread (17.0 / -17.0) was accepted that way and the controller chased it.
        self.reaccept_s = float(cfg.get("reaccept_s", 0.3))
        self.max_rate = float(cfg.get("max_rate_mps", 6.0))  # fastest believable climb or fall
        self.min_dt = float(cfg.get("min_update_dt_s", 0.03))
        self.latency = float(extra_latency_s)
        # How far now() may project past the last accepted reading. Unlimited projection
        # turned a 2.7 m/s climb estimate into a phantom 4.2 m when ALT went unreadable,
        # and the controller cut throttle to chase it.
        self.max_predict = float(cfg.get("max_predict_s", 0.15))
        self.reset()

    def reset(self):
        self.h = None
        self.v = 0.0
        self.P = [[1.0, 0.0], [0.0, 1.0]]
        self.t = None  # time of the state (measurement time)
        self.rejects = []
        self.n_rejected = 0
        self.last_good_t = None

    @property
    def initialized(self):
        return self.h is not None

    def _predict(self, dt):
        if dt <= 0:
            return
        self.h += self.v * dt
        P, q = self.P, self.q
        p00 = P[0][0] + dt * (P[1][0] + P[0][1]) + dt * dt * P[1][1] + q * dt ** 4 / 4
        p01 = P[0][1] + dt * P[1][1] + q * dt ** 3 / 2
        p11 = P[1][1] + q * dt * dt
        self.P = [[p00, p01], [p01, p11]]

    def update(self, t_grab, z):
        """Feed one reading (z may be None). Returns 'ok', 'skip', 'reject', 'reset' or 'none'."""
        if z is None:
            return "none"
        t = t_grab - self.latency
        if self.h is None:
            self.h, self.v, self.t = z, 0.0, t
            self.P = [[self.r, 0.0], [0.0, 1.0]]
            self.last_good_t = t_grab
            return "reset"
        h_save, v_save, P_save = self.h, self.v, [row[:] for row in self.P]
        self._predict(t - self.t)
        y = z - self.h
        S = self.P[0][0] + self.r
        implausible = abs(y) > self.gate_sigma * math.sqrt(S) + self.gate_floor
        # After a long gap the covariance grows until almost anything fits: 1.5 s into a
        # dropout a "-9.6" misread of 9.6 was accepted as "ok" and the pilot dove into the
        # road (2026-10-24). So also cap the jump by what the drone can physically do.
        since = t_grab - self.last_good_t if self.last_good_t is not None else 0.0
        implausible = implausible or abs(z - h_save) > 1.0 + self.max_rate * since
        # Height can't change sign without passing readable values near zero, so a sign
        # flip away from zero is a misread minus sign: never accept it, not even by re-accept.
        if abs(z) > 1.5 and abs(h_save) > 1.5 and (z > 0) != (h_save > 0):
            self.h, self.v, self.P = h_save, v_save, P_save
            self.n_rejected += 1
            return "reject"
        if t - self.t < self.min_dt and not implausible:
            # same OSD frame (or nearly): don't double-count it, but it's still a fresh, sane reading
            self.h, self.v, self.P = h_save, v_save, P_save
            self.last_good_t = t_grab
            return "skip"
        if implausible:
            self.h, self.v, self.P = h_save, v_save, P_save
            self.n_rejected += 1
            self.rejects.append((t_grab, z))
            # the run of rejected readings that agree with this one
            run = []
            # (a real fast climb spreads its readings out: allow 8 m/s between them, or a
            # genuine 10 m/s climb stays "implausible" forever, as on 2026-10-24)
            for tr, zr in reversed(self.rejects):
                if abs(zr - z) >= 0.5 + 8.0 * (t_grab - tr):
                    break
                run.append(tr)
            if len(run) >= self.reaccept_after and run[0] - run[-1] >= self.reaccept_s:
                self.h, self.v, self.t = z, 0.0, t
                self.P = [[self.r, 0.0], [0.0, 1.0]]
                self.rejects = []
                self.last_good_t = t_grab
                return "reset"
            return "reject"
        self.rejects = []
        K0, K1 = self.P[0][0] / S, self.P[1][0] / S
        self.h += K0 * y
        self.v = max(-self.max_rate, min(self.max_rate, self.v + K1 * y))
        p00, p01, p11 = self.P[0][0], self.P[0][1], self.P[1][1]
        self.P = [[(1 - K0) * p00, (1 - K0) * p01], [p01 - K1 * p00, p11 - K1 * p01]]
        self.t = t
        self.last_good_t = t_grab
        return "ok"

    def now(self, t_now):
        """(height, vertical speed) predicted to t_now, at most max_predict_s past the last reading."""
        if self.h is None:
            return None, 0.0
        return self.h + self.v * min(max(0.0, t_now - self.t), self.max_predict), self.v


class AlphaBeta:
    """Simpler fixed-gain filter, kept for comparison in replay_estimators.py."""

    def __init__(self, alpha=0.4, beta=0.08, extra_latency_s=0.0, gate_m=1.0):
        self.a, self.b, self.latency, self.gate = alpha, beta, extra_latency_s, gate_m
        self.reset()

    def reset(self):
        self.h, self.v, self.t = None, 0.0, None

    def update(self, t_grab, z):
        if z is None:
            return "none"
        t = t_grab - self.latency
        if self.h is None:
            self.h, self.v, self.t = z, 0.0, t
            return "reset"
        dt = t - self.t
        if dt <= 1e-4:
            return "skip"
        hp = self.h + self.v * dt
        r = z - hp
        if abs(r) > self.gate:
            return "reject"
        self.h = hp + self.a * r
        self.v += self.b * r / dt
        self.t = t
        return "ok"

    def now(self, t_now):
        if self.h is None:
            return None, 0.0
        return self.h + self.v * max(0.0, t_now - self.t), self.v
