"""Smooth height targets. The reference supplies target height, velocity and acceleration,
so damping acts on velocity ERROR and doesn't fight the planned climb."""
import math


class MoveProfile:
    """Trapezoidal (or triangular) velocity profile from h0 to h1 starting at t0."""

    def __init__(self, h0, h1, t0, v_max, a_max):
        self.h0, self.h1, self.t0 = h0, h1, t0
        d = abs(h1 - h0)
        self.s = 1.0 if h1 >= h0 else -1.0
        self.a = a_max
        if d < 1e-9:
            self.ta, self.tc, self.vp = 0.0, 0.0, 0.0
        elif d >= v_max * v_max / a_max:
            self.vp = v_max
            self.ta = v_max / a_max
            self.tc = (d - v_max * self.ta) / v_max
        else:
            self.vp = math.sqrt(d * a_max)
            self.ta = self.vp / a_max
            self.tc = 0.0
        self.T = 2 * self.ta + self.tc

    def done(self, t):
        return t - self.t0 >= self.T

    def __call__(self, t):
        """Returns (h, v, a, moving)."""
        tau = t - self.t0
        s, a, ta, tc, vp = self.s, self.a, self.ta, self.tc, self.vp
        if tau <= 0:
            return self.h0, 0.0, 0.0, False
        if tau >= self.T:
            return self.h1, 0.0, 0.0, False
        if tau < ta:
            return self.h0 + s * 0.5 * a * tau * tau, s * a * tau, s * a, True
        d1 = 0.5 * a * ta * ta
        if tau < ta + tc:
            return self.h0 + s * (d1 + vp * (tau - ta)), s * vp, 0.0, True
        td = tau - ta - tc
        return (self.h0 + s * (d1 + vp * tc + vp * td - 0.5 * a * td * td),
                s * (vp - a * td), -s * a, True)


class Track:
    """Height target that is moving at vertical speed v (the gate guidance's climb or sink),
    so the controller gets the speed as feed-forward instead of chasing a moving step.

    It reports moving=False: "moving" stops the integral learning during a planned move
    (MoveProfile), whose error is transient. A Track's error is steady state, which is what
    the integral is for. Reporting the climb as moving froze the integral for whole flights:
    at gate 27 the drone hung 1 m under its target for 30 s (2026-10-25, hackathon fix)."""

    def __init__(self, h, v):
        self.h, self.v = h, v

    def done(self, t):
        return True

    def __call__(self, t):
        return self.h, self.v, 0.0, False


class Hold:
    def __init__(self, h):
        self.h = h

    def done(self, t):
        return True

    def __call__(self, t):
        return self.h, 0.0, 0.0, False
