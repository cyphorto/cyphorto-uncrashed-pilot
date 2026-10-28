"""Image-based gate approach for Uncrashed ANGLE mode, not a real drone pilot."""
from dataclasses import dataclass
import math

from core.gate_detector import Gate


DEFAULTS = {
    # Where a gate level with the drone appears depends on attitude: the camera is tilted
    # 25 deg up, and ANGLE mode tilts the drone forward with the pitch stick. 50 deg per
    # unit stick fits 2026-10-24 (stick 0.14 -> level gate at y 0.35; level hover -> 0.50).
    # A fixed aim (0.35) read every pause in pitch as "gate too low" and sank the drone.
    "camera_tilt_deg": 25.0,
    "vfov_deg": 86.2,          # FOV 118 is horizontal; 16:9 gives this vertical FOV
    "deg_per_pitch": 50.0,
    "attitude_tau_s": 0.3,     # attitude lag behind the pitch stick
    "aim_trim": 0.0,           # added to the computed level line (image y, + is down)
    "aim_above_frac": 0.15,    # fly at this fraction of the gate's height above its centre
    "pursuit_up": 1.3,         # climb this much faster than the straight line to the gate
    "pursuit_down": 0.85,      # and sink this much slower (both: more ground clearance)
    "yaw_kp": 0.35,
    "yaw_kd": 0.025,
    "max_yaw": 0.18,
    "roll_kp": 0.3,            # sideways stick per unit of gate x, near the gate and while crossing
    "max_roll": 0.12,
    "bank_per_yaw": 0.0,       # roll stick per unit of yaw stick while approaching: bank into the turn (0: off)
    "max_bank": 0.3,
    "roll_sign": 1,            # +1: positive roll stick moves the drone right (check in the logs)
    "yaw_sign": 1,
    "forward_sign": 1,
    "forward_pitch": 0.07,     # attitude input, NOT a speed in m/s
    "near_pitch": 0.025,
    "alignment_x": 0.28,
    "alignment_y": 0.35,
    "vertical_gain": 0.5,      # metres/sec per normalised image error
    "max_climb_rate": 0.25,
    "min_height": 0.7,
    "max_height": 5.0,
    "near_size": 0.22,
    "near_brake": 1,           # 1: slow down close to a gate (near_pitch, line up first); 0: don't
    "commit_check": 0,         # 1: start a crossing only if the gate frames the flight path, even if lined up before
    "look_ahead": 0,           # 1: with no green gate in view, turn toward the nearest later (magenta) gate
    "tilt_ff": 0,              # 1: add the throttle forward pitch and roll cost (pilot/hover_test.py)
    "cross_steer": 0,          # 1: banked yaw+roll inside a crossing, by the gate's visible side bars
    "cross_margin": 0.3,       # ... keep the flight path this far (image x) from a visible side bar
    "dive": 0,                 # 1: gate low in the frame (or lost low): nose down to keep it in view
    "dive_y": 0.4,             # ... image y (+ is down) from which the dive starts
    "bounce_ground": 0,        # 1: a jolt upward with the throttle cut counts as touching the ground
    "reacquire_s": 5.0,        # after a crossing timeout, slow and search toward the last gate sighting this long before aborting (0: abort at once, the old behaviour)
    "reacquire_brake_s": 0.7,  # first part of a reacquire: no forward pitch, shed speed before turning or sinking
    "vert_brake": 1,           # 1: a near gate well below the level line slows the approach so the sink can catch up
    "ground_pitch": 0.12,      # forward-pitch cap while the post-ground-contact floor is active
    "ground_max_contacts": 4,  # this many ground contacts within ground_window_s: bounded abort instead of endless bouncing
    "ground_window_s": 30.0,
    "record_hz": 0,            # >0: save small grayscale frames this often (pilot/hover_test.py)
    "pass_drop_ratio": 0.45,
    "pass_confirm_s": 0.2,
    "pass_window_s": 1.0,
    "ground_clearance_m": 1.5, # after touching the ground, stay this far above it ...
    "ground_floor_s": 4.0,     # ... for this long (the terrain ahead changes)
    "recover_s": 8.0,          # how long a clipped gate may take to come back into full view
    "recover_rate": 0.7,       # climb/sink speed while recovering (m/s)
    "frame_margin": 0.2,      # share of a gate's width/height kept clear of its bars
    "cross_max_s": 20.0,       # longest any one crossing may take
    "progress_s": 120.0,       # give up if no gate is passed for this long
    "cross_timeout_s": 4.0,    # straight ahead after the crossed gate was last seen, waiting for the next
    "acquire_s": 0.25,
    "lost_s": 0.6,             # neutral sticks first ...
    "search_s": 6.0,           # ... then head where the gate was last seen, until this
    "search_pitch": 0.12,
    "blind_cross_s": 0.6,
    "cross_hold": 1,           # 1: keep pursuing the gate centre vertically inside a crossing      # in a crossing, gate invisible this long: stop flying blind at full pitch
    "blind_cross_pitch": 0.12, # pitch cap for a blind crossing when no reacquire is available      # forward pitch while searching for a gate last seen ahead and low
    "search_rate": 0.4,        # climb/sink speed while searching (m/s)
    "max_frame_age_s": 0.2,
    "filter_s": 0.12,
    "max_gates": 1,
}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


@dataclass
class Command:
    state: str
    height: float
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    passes: int = 0
    abort: str = ""
    done: bool = False
    climb: float = 0.0  # vertical speed the height reference is moving at (m/s)


class GateGuidance:
    def __init__(self, cfg=None):
        self.cfg = dict(DEFAULTS, **(cfg or {}))
        c = self.cfg
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in c.values()):
            raise ValueError("Gate pilot settings must be finite numbers")
        if c["yaw_sign"] not in (-1, 1) or c["forward_sign"] not in (-1, 1) or c["roll_sign"] not in (-1, 1):
            raise ValueError("Control signs must be -1 or 1")
        # min_height may be negative: ALT counts from the start point and the course drops
        # below it (gate 10 is in a gully under the start height).
        if not c["min_height"] < c["max_height"] or not -1 <= c["aim_trim"] <= 1:
            raise ValueError("Invalid height limits or image aim")
        if not 0 < c["vfov_deg"] < 170 or not 0 <= c["deg_per_pitch"] <= 90 or c["attitude_tau_s"] <= 0:
            raise ValueError("Invalid camera or attitude model")
        # Pitch up to 1.0 (full stick, ~50 deg nose down) for the speed experiment of
        # 2026-10-26; the frozen v0-v3 keep their 0.5 limit.
        if not 0 <= c["near_pitch"] <= c["forward_pitch"] <= 1.0 or not 0 < c["max_yaw"] <= 0.5:
            raise ValueError("Invalid steering limits")
        if c["near_brake"] not in (0, 1):
            raise ValueError("near_brake must be 0 or 1")
        if c["bank_per_yaw"] < 0 or not 0 < c["max_bank"] <= 0.5 or c["commit_check"] not in (0, 1):
            raise ValueError("Invalid turn settings")
        if c["look_ahead"] not in (0, 1):
            raise ValueError("look_ahead must be 0 or 1")
        if c["tilt_ff"] not in (0, 1) or c["cross_steer"] not in (0, 1) or not 0 < c["cross_margin"] < 1:
            raise ValueError("Invalid tilt or crossing settings")
        if c["dive"] not in (0, 1) or not 0 <= c["dive_y"] < 0.85:
            raise ValueError("Invalid dive settings")
        if c["bounce_ground"] not in (0, 1):
            raise ValueError("bounce_ground must be 0 or 1")
        if c["vert_brake"] not in (0, 1) or not 0 <= c["reacquire_s"] <= 30 or not 0 <= c["reacquire_brake_s"] <= 5:
            raise ValueError("Invalid reacquire or vertical-brake settings")
        if not 0 <= c["ground_pitch"] <= 1 or c["ground_max_contacts"] < 1 or int(c["ground_max_contacts"]) != c["ground_max_contacts"]:
            raise ValueError("Invalid ground-stabilization settings")
        self.future = []
        positive = ("alignment_x", "alignment_y", "max_climb_rate", "near_size", "pass_confirm_s",
                    "pass_window_s", "pursuit_up", "pursuit_down", "cross_timeout_s", "recover_s", "recover_rate", "frame_margin", "cross_max_s", "progress_s", "ground_clearance_m", "ground_floor_s", "acquire_s", "lost_s", "search_s", "search_rate", "search_pitch", "max_frame_age_s", "filter_s", "ground_window_s")
        if any(c[k] <= 0 for k in positive) or not 0 < c["pass_drop_ratio"] < 1:
            raise ValueError("Invalid guidance timing or thresholds")
        if c["max_gates"] < 1 or int(c["max_gates"]) != c["max_gates"]:
            raise ValueError("max_gates must be a positive integer")
        self.started = self.last_t = self.last_seen = self.acquire_since = None
        self.last_frame = None
        self.x = self.y = None
        self.height = None
        self.near_t = self.near_size = self.candidate_since = None
        self.crossing_since = self.recover_since = self.crossing_start = None
        self.cross_peak, self.cross_gone = 0.0, False  # this crossing: biggest gate size, gate vanished yet
        self.cross_last = None                         # last (x, y) of the gate being crossed, for reacquire
        self.reacquire_t0 = None                       # when a post-crossing reacquire started, else None
        self.ground_contacts = []                      # recent ground-contact times (bounce escalation)
        self.side_since = self.side_seen = None        # next gate seen off to the side while crossing
        self.climb = 0.0
        self.last_pass_t = None
        self.last_pitch = 0.0  # pitch of the last command, kept through a one-frame flicker
        self.blind = False
        self.seen = None  # (x, y) of the last valid gate
        if not -0.5 <= c["aim_above_frac"] <= 0.5:
            raise ValueError("aim_above_frac must be within the gate (-0.5..0.5)")
        self.floor = self.floor_until = None
        self.pitch_att = 0.0  # pitch stick filtered to the drone's likely attitude (+ = nose down)
        self.att_t = None
        self.passes = 0
        self.done = False
        self.failure = ""

    def ground_contact(self, height, now):
        """The flight saw the drone stop on the ground at `height` (relative to the start):
        keep the height reference above it for a while so the drone lifts off and carries on.
        Repeated contacts inside ground_window_s raise the clearance, and reaching
        ground_max_contacts aborts in a bounded, diagnosable state instead of bouncing on."""
        c = self.cfg
        self.ground_contacts = [t for t in self.ground_contacts if now-t <= c["ground_window_s"]] + [now]
        if len(self.ground_contacts) >= int(c["ground_max_contacts"]):
            self.failure = "repeated ground contact: unable to stay airborne"
        lift = c["ground_clearance_m"]*(1.0+0.5*(len(self.ground_contacts)-1))
        self.floor = height+lift
        self.floor_until = now+c["ground_floor_s"]
        self.height = max(self.height if self.height is not None else 0.0, self.floor)

    def min_height(self, now):
        if self.floor is not None and now < self.floor_until:
            return max(self.cfg["min_height"], min(self.floor, self.cfg["max_height"]))
        return self.cfg["min_height"]

    def aim(self):
        """Image y of a gate level with the drone, for the current (estimated) attitude."""
        c = self.cfg
        a = math.radians(c["camera_tilt_deg"] - c["deg_per_pitch"]*self.pitch_att)
        return math.tan(a)/math.tan(math.radians(c["vfov_deg"]/2)) + c["aim_trim"]

    def update(self, gate, height, velocity, now, frame_time, speed=None, blind=False, future=None):
        """blind: ALT has been unreadable for a while, so height and velocity are stale.
        future: later (magenta) gates in view, used with look_ahead on."""
        self.blind = blind
        self.future = list(future or [])
        cmd = self._update(gate, height, velocity, now, frame_time, speed)
        if self.att_t is not None and math.isfinite(now) and now > self.att_t:
            k = 1-math.exp(-(now-self.att_t)/self.cfg["attitude_tau_s"])
            self.pitch_att += k*(cmd.pitch*self.cfg["forward_sign"]-self.pitch_att)
        self.att_t = now
        return cmd

    def valid_gate(self, g):
        return bool(g and g.visible and all(math.isfinite(v) for v in (g.x, g.y, g.size, g.aspect, g.fill))
                    and abs(g.x) <= 1 and abs(g.y) <= 1 and 0.01 <= g.size <= 2
                    and g.pixels >= 12 and 1 <= g.aspect <= 6 and g.fill <= 1.5
                    and len(g.corners) >= 3)

    def _update(self, gate, height, velocity, now, frame_time, speed=None):
        c = self.cfg
        if self.started is None:
            self.started = now
        if self.height is None:
            self.height = clamp(height if height is not None else c["min_height"], c["min_height"], c["max_height"])
        self.climb = 0.0

        def out(state, **kw):
            if state != "flicker":
                self.last_pitch = kw.get("pitch", 0.0)
            if (state not in ("aborted", "finished") and "pitch" in kw
                    and self.floor_until is not None and now < self.floor_until):
                # Just touched the ground: climb back to the floor at low forward
                # speed instead of pitching straight into the next impact.
                kw["pitch"] = clamp(kw["pitch"], -c["ground_pitch"], c["ground_pitch"])
            return Command(state, self.height, passes=self.passes, climb=self.climb, **kw)
        if self.failure:
            return out("aborted", abort=self.failure)
        if self.done:
            return out("finished", done=True)
        # Watchdog: in front of gate 10 the pilot hovered for 11 minutes without getting
        # anywhere (2026-10-25). The slowest gate so far took ~40 s.
        if self.last_pass_t is None:
            self.last_pass_t = now
        if now-self.last_pass_t > c["progress_s"]:
            self.failure = f"no gate passed for {c['progress_s']:.0f} s"
            return out("aborted", abort=self.failure)
        if (not all(math.isfinite(v) for v in (now, frame_time)) or now-frame_time > c["max_frame_age_s"]
                or now < frame_time or (self.last_frame is not None and frame_time <= self.last_frame)):
            self.failure = "stale or non-increasing camera timestamp"
            return out("aborted", abort=self.failure)
        if height is None or not math.isfinite(height) or not math.isfinite(velocity):
            self.failure = "altitude estimate unavailable"
            return out("aborted", abort=self.failure)
        dt = min(0.1, max(0.001, now-self.last_t)) if self.last_t is not None else 0.0
        self.last_t, self.last_frame = now, frame_time
        if self.reacquire_t0 is not None:
            if self.valid_gate(gate):
                self.reacquire_t0 = None  # gate back in view: approach it normally
            else:
                return self._reacquire(now, dt, out)
        if self.crossing_since is not None:
            return self._cross(gate, now, out, dt, height, speed)
        if not self.valid_gate(gate):
            lost_for = now-(self.last_seen if self.last_seen is not None else self.started)
            if gate is not None and gate.visible and self.x is not None and lost_for < c["lost_s"]:
                # Green still in view, just malformed for a frame (a sliver at the frame edge):
                # carry on as last commanded instead of restarting the approach. Gate 10
                # flickered like this and every flicker zeroed the pitch (2026-10-25).
                return out("flicker", pitch=self.last_pitch)
            self.acquire_since = self.candidate_since = None
            self.x = self.y = None
            # Neutral pitch removes the forward command; it does not cancel momentum.
            if lost_for >= c["search_s"]:
                self.failure = "next gate lost"
                return out("aborted", abort=self.failure)
            ahead = self._ahead()
            if ahead is not None:
                # Look ahead (the user's idea, 2026-10-26): no green gate, but the course is in
                # view in magenta; fly toward the nearest one until it turns green.
                yaw, roll = self._turn(ahead.x)
                pitch = c["forward_pitch"]*max(0, 1-abs(ahead.x)/c["alignment_x"])
                return out("look_ahead", yaw=yaw, pitch=c["forward_sign"]*pitch, roll=roll)
            if lost_for < c["lost_s"] or self.seen is None:
                return out("lost")
            return self._search(now, dt, out)
        self.last_seen = now
        self.seen = (gate.x, gate.y)
        if self.near_t is not None:
            if now-self.near_t > c["pass_window_s"]:
                self.near_t = self.near_size = self.candidate_since = None
            elif not gate.clipped and gate.size < self.near_size*c["pass_drop_ratio"]:
                if self.candidate_since is None:
                    self.candidate_since = now
                if now-self.candidate_since >= c["pass_confirm_s"]:
                    self.passes += 1
                    self.last_pass_t = now
                    self.near_t = self.near_size = self.candidate_since = None
                    self.acquire_since = None
                    self.x = self.y = None
                    self.done = self.passes >= c["max_gates"]
                    return out("finished" if self.done else "reacquire", done=self.done)
                return out("pass_candidate")
            else:
                self.candidate_since = None
        # A small (far) gate cut off by the frame edge is steered at like a whole one: losing
        # a few pixels barely moves its centre, and forward pitch tilts the camera down and
        # brings a low gate into view. Recover mode only sank in place below gate 9 while
        # gate 10 stayed at the bottom edge (2026-10-25).
        # Dive: a still-far gate cut off only by the bottom edge is below us on a downhill;
        # keep approaching (diving at it) instead of stopping to recover.
        bottom_only = (len(gate.bbox) == 4 and gate.bbox[3] >= 0.97 and gate.bbox[1] > -0.97
                       and gate.bbox[0] > -0.97 and gate.bbox[2] < 0.97)
        diving = c["dive"] and bottom_only and self.near_t is None and gate.size < c["near_size"]
        if gate.clipped and not diving and (self.near_t is not None or gate.size >= 0.5*c["near_size"]):
            # The remaining visible edge is not a reliable centre to steer at.
            if self.near_t is None:
                # only once it's close; a smaller clipped gate is just low/high/off to the side
                if gate.size < 0.8*c["near_size"] or not self._frames_path(gate, self.aim()):
                    return self._recover(gate, now, dt, out)
                self.near_t, self.near_size = now, gate.size  # it frames our path: go through
            elif c["commit_check"] and not self._frames_path(gate, self.aim()):
                # Lined up earlier, but at speed the drone slid past: at 30 deg tilt and pitch 0.7
                # it crossed with gate 2 drifting right (x 0.14 -> 0.35) and flew by on its left
                # (x1 logs 20261026_193104, 28 s). Turn in first, cross once it frames the path.
                return self._recover(gate, now, dt, out)
            self.crossing_since = self.crossing_start = now
            self.recover_since = None
            self.cross_peak, self.cross_gone, self.side_since, self.side_seen = gate.size, False, None, None
            self.cross_last, self.reacquire_t0 = (gate.x, gate.y), None
            return self._cross(gate, now, out, dt, height, speed)
        self.recover_since = None
        if self.acquire_since is None:
            self.acquire_since = now
        if now-self.acquire_since < c["acquire_s"]:
            self.x, self.y = gate.x, gate.y
            return out("acquiring")
        old_x = self.x
        alpha = 1-math.exp(-dt/c["filter_s"])
        self.x = gate.x if self.x is None else self.x+alpha*(gate.x-self.x)
        self.y = gate.y if self.y is None else self.y+alpha*(gate.y-self.y)
        dx = 0 if old_x is None or dt == 0 else (self.x-old_x)/dt
        aim = self.aim()
        target_y = self.target_y(self.y, gate.size)
        # Error of the point we steer for, not of the gate centre: with aim_above_frac the
        # centre sits below the level line by design, and close in that alone failed the
        # "lined up" test and sent the pilot into recover mode (2026-10-24).
        ey = target_y-aim
        near = gate.size >= c["near_size"]
        dh = self._climb_rate(target_y, speed)
        self.climb = dh
        # The reference may lead the measured height by 1 m at most, so it can't run away
        # while the drone lags behind the requested climb or sink.
        self.height = clamp(clamp(self.height+dh*dt, height-1.0, height+1.0),
                            self.min_height(now), c["max_height"])
        yaw = c["yaw_sign"]*clamp(c["yaw_kp"]*self.x+c["yaw_kd"]*dx, -c["max_yaw"], c["max_yaw"])
        # Far away the straight-line climb/sink takes care of height, so only steering has
        # to line up; close in, the gate should also sit near the level line.
        aligned = max(0, 1-abs(self.x)/c["alignment_x"]) * (max(0, 1-abs(ey)/c["alignment_y"]) if near else 1.0)
        # Don't accelerate while height control is still catching up.
        # Judged against the climb we asked for: on the uphill road a steady 0.6 m/s climb
        # failed "abs(velocity) <= 0.6" and the pilot kept stopping (2026-10-24).
        # Blind (stale ALT) there is nothing to judge; stopping kept the drone hovering
        # behind the tree that hid the readout (2026-10-24), so keep moving.
        # A sliding scale, not on/off: full pitch within 0.4 m of the height target and 0.6 m/s
        # of the asked-for climb, none beyond 0.8 m / 1.2 m/s. The on/off version made the flying
        # stop-start, and the vertical speed estimate is too noisy (ALT moves in 0.1 m steps)
        # for a tight speed limit (2026-10-25).
        err = max(abs(height-self.height)/0.8, abs(velocity-dh)/1.2)
        settled = 1.0 if self.blind else clamp(2.0*(1.0-err), 0.0, 1.0)
        pitch = (c["near_pitch"] if near else c["forward_pitch"])*aligned*settled
        if near and not c["near_brake"]:
            # The user's request (2026-10-26): don't slow down on the way into the gate. Watching
            # validation they saw it brake hard before every gate; the logs show ~-25% speed in
            # the last 3 s (near_pitch, then the vertical-alignment and height-settled fades).
            # Cruise pitch instead; only a sideways miss still takes pitch off, so it can turn in.
            pitch = c["forward_pitch"]*max(0, 1-abs(self.x)/c["alignment_x"])
        if c["vert_brake"] and near and ey > c["alignment_y"]:
            # Near gate well below the level line (flightfix, 2026-10-27): at full
            # cruise pitch the pursuit sink cannot catch up and the gate exits the
            # bottom of the frame (last sightings y 0.89-0.97 in three flights).
            # Slow in proportion to the vertical error so the sink can catch up;
            # the dive below still handles a gate low enough to leave the frame.
            pitch *= clamp(1.0-(ey-c["alignment_y"])/c["alignment_y"], 0.0, 1.0)
        if c["dive"] and self.y > c["dive_y"]:
            # Dive (the user, 2026-10-26: "with the upwards tilt you can't see the next gate
            # that's below you"). A low gate used to fade the pitch to zero, which tilts the
            # camera up and drops the gate out of the bottom of the frame (x4 logs
            # 20261026_195005, gate 9: y 0.83-0.90, pitch 0, camera 30 deg up). Nose down
            # instead, more the lower it sits: the camera follows and brings it back up.
            depth = clamp((self.y-c["dive_y"])/(0.85-c["dive_y"]), 0.0, 1.0)
            pitch = max(pitch, c["forward_pitch"]*depth*max(0, 1-abs(self.x)/c["alignment_x"]))
        if near and abs(gate.x) < c["alignment_x"]*0.5 and abs(self.target_y(gate.y, gate.size)-aim) < c["alignment_y"]*0.5:
            self.near_t, self.near_size = now, gate.size
        # Close in, also slide sideways (roll) toward the gate: yaw only turns the nose, and
        # after a turn the drone kept sliding and passed beside gate 13 (2026-10-25).
        roll = self._roll(self.x) if gate.size >= 0.7*c["near_size"] else 0.0
        if c["bank_per_yaw"]:
            # Banked turn (the user, 2026-10-26: "move the yaw and roll at the same time in one
            # direction"): roll follows the yaw, same way, at any distance. Yaw alone only turns
            # the nose; at 30 km/h the drone kept sliding outward and passed beside gate 2.
            bank = c["roll_sign"]*clamp(c["bank_per_yaw"]*yaw*c["yaw_sign"], -c["max_bank"], c["max_bank"])
            roll = bank if abs(bank) > abs(roll) else roll
        return out("approach" if pitch > 0 else "align", yaw=yaw, pitch=c["forward_sign"]*pitch, roll=roll)

    def _search(self, now, dt, out):
        """Gate out of sight for longer than lost_s: go where it was last seen. After gate 9
        on 2026-10-24 the next gate sat in a gully, slid out of the bottom of the frame and
        the pilot stopped 0.6 s later. No forward pitch; the ground and crash checks in the
        flight loop still apply while sinking."""
        c = self.cfg
        sx, sy = self.seen
        vz = -c["search_rate"] if sy > 0.5 else (c["search_rate"] if sy < -0.3 else 0.0)
        self.climb = vz
        self.height = clamp(self.height+vz*dt, self.min_height(now), c["max_height"])
        yaw = c["yaw_sign"]*c["max_yaw"]*0.5*(1 if sx > 0.3 else (-1 if sx < -0.3 else 0))
        # Last seen ahead: also move toward it. Getting closer makes a far gate bigger and
        # steadier to detect, and the forward tilt brings a low one up the frame. Sinking in
        # place left gate 10 a speck at the bottom edge, and hovering left gate 16 (far down a
        # canyon, overlapped by the magenta gate behind it) flickering (2026-10-25).
        pitch = c["forward_sign"]*c["search_pitch"] if abs(sx) < 0.4 else 0.0
        if c["dive"] and sy > c["dive_y"]:
            # Dive (2026-10-26): with the camera tilted up 30 deg, search pitch 0.12 still
            # looked 24 deg up and gate 10, down in the gully, never came back into view (x4
            # logs 20261026_195140, 78-84 s). Nose down until the camera looks ~10 deg below
            # the horizon, and sink at the full rate.
            dive = clamp((c["camera_tilt_deg"]+10)/c["deg_per_pitch"], c["search_pitch"], c["forward_pitch"])
            pitch = c["forward_sign"]*dive if abs(sx) < 0.4 else pitch
            self.climb = -c["max_climb_rate"]
            self.height = clamp(self.height+self.climb*dt-vz*dt, self.min_height(now), c["max_height"])
        return out("search", yaw=yaw, pitch=pitch)

    def target_y(self, y, size):
        """Image y of the point to fly through: aim_above_frac of the gate's height above
        its centre (gate height in image-y units: 16:9 frame, y spans half the height)."""
        return y-self.cfg["aim_above_frac"]*size*2*16/9

    def _climb_rate(self, target_y, speed):
        """Vertical speed that flies a straight line at the gate (pursuit) instead of first
        getting level with it.

        ALT counts from the start point, not the ground, so the gate is the only terrain
        reference. The terrain between the drone and the gate is below the line of sight to
        the gate's base (that base is visible), so a straight line at a point above it
        clears the terrain too. Levelling first dropped the drone onto the road on
        downhill stretches (2026-10-24). The aim point sits aim_above_frac of the gate's
        height above its centre; sinking runs a little slower than the line (pursuit_down)
        and climbing a little faster (pursuit_up), both towards more clearance.
        speed: forward speed in m/s from the OSD, None if unread."""
        c = self.cfg
        axis = math.radians(c["camera_tilt_deg"]-c["deg_per_pitch"]*self.pitch_att)
        elev = axis-math.atan(target_y*math.tan(math.radians(c["vfov_deg"]/2)))  # + = above level
        v = speed if speed is not None and math.isfinite(speed) else 0.0
        rate = (c["pursuit_up"] if elev > 0 else c["pursuit_down"])*v*math.tan(elev)
        if elev > 0:  # climbing never hurts, so it doesn't wait for forward speed
            rate = max(rate, c["vertical_gain"]*math.tan(elev))
        return clamp(rate, -c["max_climb_rate"], c["max_climb_rate"])

    def _frames_path(self, gate, aim):
        """Is the drone's flight path (image x 0, the level line) inside the gate, clear of
        the frame bars? Edges cut off by the image border lie beyond it, so only visible
        edges limit this. Close in, a gate's bottom bar always drops out of the frame (the
        camera looks 25 deg up), so "clipped" alone says nothing about being too high."""
        if len(gate.bbox) != 4:
            return False
        x0, y0, x1, y1 = gate.bbox
        m = self.cfg["frame_margin"]
        mx, my = m*(x1-x0), m*(y1-y0)
        return x0+mx < 0 < x1-mx and y0+my < aim < y1-my

    def _roll(self, x):
        """Sideways correction toward a gate at image x (-1 left .. 1 right)."""
        c = self.cfg
        return c["roll_sign"]*clamp(c["roll_kp"]*x, -c["max_roll"], c["max_roll"])

    def _recover(self, gate, now, dt, out):
        """Gate clipped and the flight path not inside it: no forward pitch, move so that it
        is (sink if the path runs over the top bar, climb if under a visible bottom bar, yaw
        toward the side the gate is on), then approach again.

        2026-10-24: sinking whenever the bottom was cut off looped for 8 minutes in front of
        a close gate the drone was in fact below (its bottom bar was out of view because of
        the camera tilt, not because the drone was high)."""
        c = self.cfg
        if self.recover_since is None:
            self.recover_since = now
        if now-self.recover_since > c["recover_s"]:
            self.failure = "clipped gate without an aligned approach"
            return out("aborted", abort=self.failure)
        x0, y0, x1, y1 = gate.bbox if len(gate.bbox) == 4 else (gate.x, gate.y, gate.x, gate.y)
        aim = self.aim()
        m = c["frame_margin"]
        my, mx = m*(y1-y0), m*(x1-x0)
        vz = -1 if aim < y0+my else (1 if (y1 < 0.97 and aim > y1-my) else 0)
        self.climb = vz*c["recover_rate"]
        self.height = clamp(self.height+self.climb*dt, self.min_height(now), c["max_height"])
        side = 1 if x0+mx > 0 else (-1 if x1-mx < 0 else 0)
        self.acquire_since = None
        return out("recover", yaw=c["yaw_sign"]*side*c["max_yaw"]*0.5)

    def _start_reacquire(self, now, out):
        """Crossing failed without a confirmed pass: hand the last sighting of
        the crossed gate to the reacquire search. The pass is NOT counted: the
        gate was missed, and counting it would hide the overflight."""
        self.seen, self.last_seen = self.cross_last, now
        self.reacquire_t0 = now
        self.crossing_since = self.crossing_start = None
        self.near_t = self.near_size = self.candidate_since = None
        self.acquire_since = self.recover_since = None
        self.x = self.y = None
        self.side_since = self.side_seen = None
        return self._reacquire(now, 0.0, out)

    def _reacquire(self, now, dt, out):
        """Bounded search for a gate lost in a crossing (flightfix, 2026-10-27).

        First reacquire_brake_s: no forward pitch, shed the ~9 m/s entry speed.
        Then search toward the last sighting like _search (yaw to its side,
        sink/climb to its height, dive if it left low), for reacquire_s in
        total. A gate back in view is approached normally (see _update); if
        none shows, abort with a diagnosable failure instead of flying on."""
        c = self.cfg
        if now-self.reacquire_t0 > c["reacquire_s"]:
            self.reacquire_t0 = None
            self.failure = "no next gate after crossing (reacquire failed)"
            return out("aborted", abort=self.failure)
        sx, sy = self.seen if self.seen is not None else (0.0, 0.0)
        vz = -c["search_rate"] if sy > 0.5 else (c["search_rate"] if sy < -0.3 else 0.0)
        if c["dive"] and sy > c["dive_y"]:
            vz = -c["max_climb_rate"]
        self.climb = vz
        self.height = clamp(self.height+vz*dt, self.min_height(now), c["max_height"])
        yaw = c["yaw_sign"]*c["max_yaw"]*0.5*(1 if sx > 0.3 else (-1 if sx < -0.3 else 0))
        if now-self.reacquire_t0 < c["reacquire_brake_s"]:
            pitch = 0.0
        elif abs(sx) < 0.4:
            pitch = c["forward_sign"]*c["search_pitch"]
            if c["dive"] and sy > c["dive_y"]:
                dive = clamp((c["camera_tilt_deg"]+10)/c["deg_per_pitch"], c["search_pitch"], c["forward_pitch"])
                pitch = c["forward_sign"]*dive
        else:
            pitch = 0.0
        return out("reacquire_search", yaw=yaw, pitch=pitch)

    def _side_pass(self, now, out, seen_at):
        """The crossed gate is behind us and the next one is off to the side: count the pass
        and hand over to the approach, which turns toward it (recover while it is cut off,
        search toward where it was once it has left the frame)."""
        self.passes += 1
        self.last_pass_t = now
        self.crossing_since = self.near_t = self.near_size = self.candidate_since = None
        self.acquire_since = self.recover_since = None
        self.x = self.y = None
        self.seen, self.last_seen = self.side_seen, seen_at
        self.side_since = self.side_seen = None
        self.done = self.passes >= self.cfg["max_gates"]
        return out("finished" if self.done else "reacquire", done=self.done)

    def _cross(self, gate, now, out, dt=0.0, height=None, speed=None):
        """Committed crossing: straight ahead at approach pitch until the next gate shows.

        On 2026-10-24 the drone went through gate 1, but the old gate's post stayed green
        and clipped at the frame edge for about a second, the 0.6 s lost rule fired and the
        pilot stopped. So inside the gate nothing counts as lost; only a gate smaller than
        the one we entered ends the crossing (a pass), or cross_timeout_s / cross_max_s."""
        c = self.cfg
        forward = c["forward_sign"]*c["forward_pitch"]
        # The next gate off to the side (hackathon fix, 2026-10-26): at the left bend after
        # the pilot's 28th pass, the next gate showed cut off at the left edge (x -0.8, size
        # 0.17) for 3 s right after the crossed gate left through the right. That size reads
        # as "the gate we're in", so the pilot flew straight into the field; every Roadtrip
        # attempt that got this far ended there. Once the crossed gate has vanished for a
        # frame, a cut-off blob at the side, well under the crossed gate's peak size, is the
        # next gate. In 642 logged crossings this happened only at missed gates; after normal
        # passes only 1-2 frame slivers (size <= 0.014) showed at the edges. Not at the top or
        # bottom edge: after climbing out over gate 19 the crossed gate's top bar came back in
        # at the bottom-left (y +0.9) and was counted twice (v2, 2026-10-26); real side gates
        # sat at |y| <= 0.73 in every log.
        visible = gate is not None and gate.visible and all(math.isfinite(v) for v in (gate.x, gate.y, gate.size))
        if not visible:
            self.cross_gone = True
        elif not self.cross_gone:
            self.cross_peak = max(self.cross_peak, gate.size)
        if (visible and self.cross_gone and gate.clipped and abs(gate.x) >= 0.5 and abs(gate.y) < 0.8
                and 0.02 <= gate.size < 0.6*self.cross_peak):
            self.side_seen = (gate.x, gate.y)
            if self.side_since is None:
                self.side_since = now
            if now-self.side_since >= c["pass_confirm_s"]:
                return self._side_pass(now, out, now)
            return out("side_candidate", pitch=forward)
        self.side_since = None
        small = self.valid_gate(gate) and gate.size < self.near_size*c["pass_drop_ratio"]
        if visible and not small:
            self.cross_last = (gate.x, gate.y)
        if c["cross_hold"] and visible and not small and height is not None:
            # Keep flying the centre inside the gate (flight
            # 20261027_170655: every damage onset, incl. gate 32, was a
            # crossing drooping at 1.1-1.7 m/s with climb frozen at 0 and
            # the height reference frozen). Same pursuit and reference
            # integration as the approach, so a crossing cannot droop
            # through the bottom bar or scrape the ground at low gates.
            rate = self._climb_rate(self.target_y(gate.y, gate.size), speed)
            self.climb = rate
            self.height = clamp(clamp(self.height+rate*dt, height-1.0, height+1.0),
                                self.min_height(now), c["max_height"])
        if (c["reacquire_s"] > 0 and visible and not small and self.cross_last is not None
                and gate.y > 0.85 and gate.size < 0.6*self.cross_peak):
            # Overflight (flightfix, 2026-10-27): the gate we are crossing is
            # leaving through the bottom of the frame, already past its peak
            # size, so we are passing over it, not through it. Reacquire now
            # instead of flying blind at full pitch until the timeout.
            return self._start_reacquire(now, out)
        # Time out from the last frame that still showed the gate we're in, not from the
        # first clipped frame: a slow crossing took >5 s on its own (2026-10-24), and the
        # game can take 1-2 s more to turn the next gate green.
        # Any large green blob is the gate we're in, even an odd-shaped strip: at gate 9 the
        # last 3 s of the passage failed the shape test and the timer ran out 0.6 s after
        # the drone came through (2026-10-25).
        if gate is not None and gate.visible and gate.size >= self.near_size*c["pass_drop_ratio"]:
            self.crossing_since = now
        # The next gate: smaller than the one we entered and whole in view; or, once the
        # crossed gate has been out of sight for 1 s, cut off by the frame edge but near the
        # middle. Gate 10 sits far below gate 9 and first shows at the bottom edge; the
        # pilot flew on past it for 12 s (2026-10-25). Posts of the crossed gate leave
        # through the sides, so they don't qualify.
        nxt = small and (not gate.clipped or (now-self.crossing_since >= 1.0 and abs(gate.x) < 0.5))
        if nxt:
            if self.candidate_since is None:
                self.candidate_since = now
            if now-self.candidate_since >= c["pass_confirm_s"]:
                self.passes += 1
                self.last_pass_t = now
                self.crossing_since = self.near_t = self.near_size = self.candidate_since = None
                # a recover clock left over from before this gate aborted the next one at once
                self.acquire_since = self.recover_since = None
                self.x = self.y = None
                self.last_seen = now
                self.done = self.passes >= c["max_gates"]
                return out("finished" if self.done else "reacquire", done=self.done)
            return out("pass_candidate", pitch=forward)
        self.candidate_since = None
        # The timeout above restarts while the gate stays in view; a drone lying still in
        # front of one sat "crossing" for 11 minutes (2026-10-24). Hard limit as well.
        if now-self.crossing_since > c["cross_timeout_s"] or now-self.crossing_start > c["cross_max_s"]:
            if self.side_seen is not None:
                # Only glimpsed at the edge (0.17 s at the same bend on 2026-10-25): search
                # that way straight away instead of stopping.
                return self._side_pass(now, out, now-c["lost_s"])
            if c["reacquire_s"] > 0 and self.cross_last is not None:
                # Blind after a crossing (flightfix, 2026-10-27): the gate exited
                # the frame (usually the bottom: overflight) and 4 s of straight
                # full-pitch flight found nothing. Slow down and search toward
                # the last sighting instead of aborting at speed.
                return self._start_reacquire(now, out)
            self.failure = "no next gate after crossing"
            return out("aborted", abort=self.failure)
        # Keep sliding toward the gate while it is still in view (its visible part, even cut
        # off, is on the right side of the frame).
        roll = self._roll(gate.x) if gate is not None and gate.visible and not small else 0.0
        if c["cross_steer"] and gate is not None and gate.visible and not small and len(gate.bbox) == 4:
            # Steer through the opening with yaw and roll together. Both runs of 2026-10-26 at
            # 35 km/h clipped a gate in the last half second of the crossing (x2 logs
            # 20261026_194111: gate 2 drifting right past its left post), when roll was
            # capped at 0.12 and yaw at 0.
            yaw, roll = self._turn(self._opening_x(gate))
            return out("crossing", pitch=forward, yaw=yaw, roll=roll)
        ahead = self._ahead()
        if ahead is not None and self.cross_gone and not (gate is not None and gate.visible):
            # Look ahead: the crossed gate is behind us and the next one isn't green yet (the
            # game takes 1-2 s): turn toward the nearest magenta gate now, not after the wait.
            yaw, roll = self._turn(ahead.x)
            return out("crossing", pitch=forward, yaw=yaw, roll=roll)
        if not visible and self.cross_gone and now-self.crossing_since >= c["blind_cross_s"]:
            # Blind crossing guard (the one addition over the finishing
            # pilot): every p2_center_ground_v1..v11 failure ended with a
            # crossing gone blind holding full pitch until the next gate
            # was lost. Hand over to the existing reacquire, which brakes
            # and searches toward the last sighting; only when no
            # reacquire is available, creep at blind_cross_pitch.
            if c["reacquire_s"] > 0 and self.cross_last is not None:
                return self._start_reacquire(now, out)
            return out("crossing", pitch=c["forward_sign"]*c["blind_cross_pitch"], roll=roll)
        return out("crossing", pitch=forward, roll=roll)

    def _opening_x(self, gate):
        """Where to steer (image x) inside a gate we're crossing. Its centre isn't reliable
        when it's cut off by the frame, so go by the side bars still in view: both visible,
        aim between them; one visible and closer to the flight path (x 0) than cross_margin,
        move away from it; otherwise the path is clear: 0."""
        x0, _, x1, _ = gate.bbox
        m = self.cfg["cross_margin"]
        left, right = x0 > -0.97, x1 < 0.97  # side bar in view, not cut off by the frame edge
        if left and right:
            return (x0+x1)/2
        if left and x0 > -m:
            return x0+m
        if right and x1 < m:
            return x1-m
        return 0.0

    def _ahead(self):
        """With look_ahead on: the nearest later (magenta) gate in view, else None."""
        if not self.cfg["look_ahead"]:
            return None
        gates = [g for g in self.future if self.valid_gate(g)]
        return max(gates, key=lambda g: g.size) if gates else None

    def _turn(self, x):
        """Yaw toward image x, with the banked roll the same way (bank_per_yaw)."""
        c = self.cfg
        yaw = c["yaw_sign"]*clamp(c["yaw_kp"]*x, -c["max_yaw"], c["max_yaw"])
        roll = c["roll_sign"]*clamp(c["bank_per_yaw"]*yaw*c["yaw_sign"], -c["max_bank"], c["max_bank"])
        return yaw, roll
