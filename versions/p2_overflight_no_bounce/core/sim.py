"""A small vertical-only drone simulator so every script can be tried with --sim, no game needed.

Models: input delay, motor lag, linear drag, ground, a 30 fps OSD that shows
height rounded to 0.1 m with render latency, OCR processing time, misreads and dropped reads.
It is deliberately imperfect. The real game WILL differ, so treat sim gains as a starting point.
"""
import bisect
import random

G = 9.81


class SimIO:
    is_sim = True

    def __init__(self, sim_cfg, seed=None):
        c = sim_cfg
        self.hover = float(c["true_hover"])
        self.delay = float(c["input_delay_s"])
        self.tau = float(c["motor_tau_s"])
        self.drag = float(c["drag"])
        self.osd_dt = 1.0 / float(c["osd_fps"])
        self.disp_lat = float(c["display_latency_s"])
        self.ocr_delay = float(c["ocr_delay_s"])
        self.p_mis = float(c["misread_prob"])
        self.p_drop = float(c["drop_prob"])
        self.rng = random.Random(c.get("seed", 1) if seed is None else seed)
        self.t = 0.0
        self.h = 0.0
        self.v = 0.0
        self.thrust = 0.0
        self.cmd_t = [-1.0]
        self.cmd_u = [0.0]
        self.hist_t = [0.0]
        self.hist_h = [0.0]
        self.phys_dt = 0.001
        self.misreads = 0

    # --- clock ---
    def now(self):
        return self.t

    def wait_until(self, t_target):
        while self.t < t_target - 1e-12:
            self._step(min(self.phys_dt, t_target - self.t))

    def _cmd_at(self, t):
        i = bisect.bisect_right(self.cmd_t, t) - 1
        return self.cmd_u[max(i, 0)]

    def _step(self, dt):
        u = self._cmd_at(self.t - self.delay)
        self.thrust += (u - self.thrust) * min(1.0, dt / self.tau)
        a = G * (self.thrust / self.hover - 1.0) - self.drag * self.v
        self.v += a * dt
        self.h += self.v * dt
        if self.h <= 0.0:
            self.h = 0.0
            if self.v < 0:
                self.v = 0.0
        self.t += dt
        self.hist_t.append(self.t)
        self.hist_h.append(self.h)

    def _h_at(self, t):
        i = bisect.bisect_right(self.hist_t, t) - 1
        return self.hist_h[max(i, 0)]

    # --- sensing ---
    def read(self):
        """Returns (t_grab, height reading or None, extra info)."""
        t_grab = self.t
        frame_t = (int(t_grab / self.osd_dt)) * self.osd_dt
        shown = round(self._h_at(frame_t - self.disp_lat), 1)
        z = shown
        r = self.rng.random()
        if r < self.p_drop:
            z = None
        elif r < self.p_drop + self.p_mis:
            self.misreads += 1
            kind = self.rng.choice(("dropped_decimal", "digit"))
            z = round(shown * 10, 1) if kind == "dropped_decimal" else round(shown + self.rng.choice((-1, 1)) * self.rng.choice((1.0, 10.0)), 1)
        self.wait_until(self.t + self.ocr_delay)
        return t_grab, z, {"true_h": self.h, "true_v": self.v}

    # --- actuation ---
    def send(self, throttle, yaw=0.0, pitch=0.0, roll=0.0):
        self.cmd_t.append(self.t)
        self.cmd_u.append(max(0.0, min(1.0, throttle)))

    def min_throttle(self):
        self.send(0.0)

    def arm(self):
        pass

    def kill_pressed(self):
        return False

    def close(self):
        pass
