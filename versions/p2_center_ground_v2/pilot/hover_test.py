"""Hover test: take off in angle mode, hold a height, watch for the gate, land.

    python pilot/hover_test.py                 # real game: waits for F8, then flies
    python pilot/hover_test.py --sim           # offline, vertical-only simulator
    python pilot/hover_test.py --height 3 --hold 10

What it does
  1. Connects the virtual controller: throttle 0, sticks centred, button A held
     (A is bound to Angle in Uncrashed, so the drone self-levels).
  2. Waits for F8. Before pressing it: select the Xbox controller in Uncrashed and
     press T so the drone is on the start line.
  3. Arms (2 s at zero throttle), then ramps throttle slowly until the ALT readout
     shows the drone leaving the ground. That throttle is the first hover estimate,
     so a wrong config guess can't fling the drone into the sky.
  4. Climbs to --height with the altitude controller, holds for --hold seconds.
     Roll, pitch and yaw stay at zero. The gate detector runs on every frame and is
     logged, but it does not steer.
  5. Descends to 0.3 m and cuts throttle.
Hold F12 at any time to cut throttle. Safety aborts (stale ALT reading, ceiling,
saturated throttle) also cut it.

Writes logs/<time>_hover/: log.csv (every tick), alt/*.png (ALT crops with the
reading, to check the reader on live frames), view/*.jpg (frames with the gate
overlay), meta.json (config + result).
"""
import argparse
import math
import csv
import json
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ROOT, config as C  # noqa: E402
from core.alt_reader import AltReader, crop as alt_crop  # noqa: E402
from core.controller import AltitudeController, bounced, tilt_feedforward  # noqa: E402
from core.estimator import HeightKF  # noqa: E402
from core.gate_detector import GateDetector, draw  # noqa: E402
from core.ground_flow import GroundWarn, GroundWorker, attitude_deg  # noqa: E402
from core.osd_mode import damage_icon, is_angle, mode_width  # noqa: E402
from core.speed_reader import SpeedReader  # noqa: E402
from core.reference import Hold, MoveProfile, Track  # noqa: E402
from core.safety import Safety  # noqa: E402

VK_F8 = 0x77
BLIND_BELOW_HOVER = 0.015  # throttle below the hover estimate while ALT is unreadable (slow sink)
BLIND_FLY_S = 12.0         # steering may continue this long past safety.stale_s without ALT
BLIND_MAX_S = BLIND_FLY_S + 4.0  # then give up and cut throttle
BLIND_CLIMB_GAIN = 0.04    # throttle per m/s of guidance climb while blind (vision-only height)
STUCK_S = 6.0              # asking to move, but no speed and no height change this long: stuck
STUCK_HIT_S = 2.0          # ... this long while the damaged-drone icon shows
STICK_TAU_S = 0.25         # yaw/pitch/roll eased toward the guidance command (smooth flying)
THROTTLE_BAND = (-0.10, 0.12)  # closed-loop throttle limits around the learned hover, in the air
COLS = ["t", "phase", "dt", "raw_h", "read_status", "h_filt", "v_filt", "h_ref", "v_ref", "u", "u_p", "u_d", "u_i",
        "sat", "gate_visible", "gate_x", "gate_y", "gate_size", "gate_clipped", "alt_text", "alt_score", "abort",
        "yaw", "pitch", "roll", "guidance_state", "gate_pass_candidates", "speed_ms", "climb", "mode_w", "damage",
        "u_tilt", "ground_h"]


FLOW_SIZE = (320, 180)  # recorded frame size for the camera ground check


def save_flow_frame(frame, folder, t, size=FLOW_SIZE):
    """One small grayscale JPEG of the game frame, named by the log's t (4 decimals)."""
    code = cv2.COLOR_BGRA2GRAY if frame.ndim == 3 and frame.shape[2] == 4 else cv2.COLOR_BGR2GRAY
    gray = cv2.cvtColor(cv2.resize(frame, size, interpolation=cv2.INTER_AREA), code)
    path = folder / f"{t:.4f}.jpg"
    cv2.imwrite(str(path), gray, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path


class Aborted(Exception):
    """Safety stop: throttle is cut. Used when the altitude can't be trusted (stale ALT,
    ceiling, saturation) or on F12."""


class Crashed(Aborted):
    """The OSD mode stopped reading ANGLE in the air: the drone crashed (it shows "3D" and a
    damaged-drone icon). Nothing to save; the race has to restart."""


class GuidanceStop(Exception):
    """Soft stop: the height reading is still good, so the caller levels, holds and lands
    instead of dropping the drone."""


class LiveIO:
    """Real game: one frame per tick feeds both the ALT reader and the gate detector.

    Frames come from the game window (core.window), so other windows can't cover the
    ALT readout. pad and cap can be shared with a caller that outlives this flight
    (pilot/runner.py); then close() leaves them alone."""
    is_sim = False

    def __init__(self, cfg, angle_button="A", pad=None, cap=None):
        from core.gamepad import BUTTONS, Gamepad
        from core.gameio import KillKey
        from core.window import open_capture
        self.alt = AltReader(ROOT / "data" / "alt_templates")
        if not self.alt.ready:
            raise RuntimeError("ALT templates missing digits " + ",".join(self.alt.missing()))
        self.own_cap, self.own_pad = cap is None, pad is None
        self.cap = cap or open_capture(cfg)
        self.pad = pad or Gamepad(cfg["controls"])
        self.btn = getattr(self.pad.vg.XUSB_BUTTON, BUTTONS[angle_button]) if angle_button else None
        if self.btn is not None:
            self.pad.pad.press_button(button=self.btn)
        self.pad.send(0.0)
        self.kill = KillKey(cfg["controls"].get("kill_key", "F12"))
        self.det = GateDetector()
        self.speed = SpeedReader(ROOT / "data" / "speed_templates")
        self.frame = None
        self.frame_count = None

    def now(self):
        return time.perf_counter()

    def wait_until(self, t):
        while True:
            left = t - time.perf_counter()
            if left <= 0:
                return
            time.sleep(left - 0.002 if left > 0.003 else 0)

    def read(self):
        # Always a newer frame than last tick: the guidance aborts on a repeated timestamp.
        t, self.frame, self.frame_count = self.cap.grab(newer_than=self.frame_count, timeout=0.5)
        h, text, score = self.alt.read(self.frame)
        return t, h, {"gate": self.det.detect(self.frame), "alt_text": text, "alt_score": score,
                      "mode_w": mode_width(self.frame), "speed": self.speed.read_ms(self.frame),
                      "damage": round(damage_icon(self.frame), 3)}

    def send(self, throttle, yaw=0.0, pitch=0.0, roll=0.0):
        self.pad.send(throttle, yaw, pitch, roll)  # update() also re-sends the held button

    def kill_pressed(self):
        return self.kill.pressed()

    def f8(self):
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_F8) & 0x8000)

    def park(self, max_s=600):
        """Keep the controller connected at zero throttle until F12 is pressed again.

        When this process exits the virtual controller disappears and Uncrashed falls back
        to any other connected controller. The DJI remote's throttle springs to the middle
        (about 50%), which flew the drone to 70 m on 2026-10-24. Turn the remote off, or
        pause the game, before pressing F12 here."""
        print("\nController parked at zero throttle so the game can't fall back to another controller.\n"
              "Turn off the DJI remote or pause the game, then hold F12 to exit.", flush=True)
        while self.kill_pressed():  # wait for the F12 that may have stopped the flight to be released
            self.send(0.0)
            time.sleep(0.02)
        end = time.perf_counter() + max_s
        while time.perf_counter() < end and not self.kill_pressed():
            self.send(0.0)
            time.sleep(0.02)

    def close(self):
        self.pad.min_throttle()
        if self.own_pad and self.btn is not None:
            self.pad.pad.release_button(button=self.btn)
            self.pad.pad.update()
        if self.own_cap:
            self.cap.close()


def make_sim(cfg):
    from core.sim import SimIO
    io = SimIO(cfg["sim"])
    io.frame = None
    return io


class Flight:
    def __init__(self, io, cfg, args, folder):
        self.io, self.cfg, self.args, self.folder = io, cfg, args, folder
        self.est = HeightKF(cfg["estimator"], cfg["osd"]["extra_latency_s"])
        ccfg = dict(cfg["controller"])
        ccfg.update(ki=args.ki, i_max=args.i_max)
        self.ccfg = ccfg
        self.ctrl = AltitudeController(ccfg)
        self.safety = Safety(cfg["safety"])
        self.rows = []
        self.t_last = io.now()
        self.next_alt_png = 0.0
        self.next_alt_fail = 0.0
        self.next_view = 0.0
        # High-rate frames for the camera ground check (2026-10-26): small grayscale JPEGs
        # named by the log's own t, so each lines up with that tick's speed, pitch and ALT.
        hz = float(cfg.get("gate_pilot", {}).get("record_hz", 0) or 0)
        self.record_dt, self.next_rec = (1.0 / hz if hz > 0 else None), 0.0
        (folder / "alt").mkdir(parents=True, exist_ok=True)
        (folder / "view").mkdir(parents=True, exist_ok=True)
        if self.record_dt:
            (folder / "flow").mkdir(parents=True, exist_ok=True)
        # Camera ground detector (gate_pilot.ground_warn): off unless switched on.
        gp = cfg.get("gate_pilot", {})
        self.ground_warn = self.ground_worker = None
        self.ground_frames, self.next_ground, self.ground_h = [], 0.0, None
        if gp.get("ground_warn"):
            self.ground_warn = GroundWarn(warn_m=float(gp.get("ground_warn_m", 1.2)))
            self.ground_worker = GroundWorker()
        f = open(folder / "log.csv", "w", newline="", encoding="utf-8")
        self.csv_file = f
        self.csv = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        self.csv.writeheader()
        self.airborne = False
        self.in_air = False  # from liftoff until the final throttle cut (airborne clears at landing start)
        self.last_command = None
        self.hover_estimate = None
        self.gc_t0 = self.gc_h0 = None  # ground-contact check window
        self.u_prev = self.u_low_prev = None  # last throttle and the bottom of its band (bounce check)
        self.mode_bad_since = None
        self.last_speed = (None, 0.0)  # (m/s, time read)
        self.still_since = self.still_h = None  # stuck check window
        self.sticks = (0.0, 0.0, 0.0)  # yaw, pitch, roll actually sent

    def tick(self, phase, ref=None, open_u=None, period=1 / 30, guidance=None, sticks=None):
        """sticks: fixed (yaw, pitch, roll) for probe flights without guidance."""
        io = self.io
        t_grab, z, extra = io.read()
        status = self.est.update(t_grab, z)
        t = io.now()
        dt = max(1e-3, t - self.t_last)
        self.t_last = t
        h, v = self.est.now(t)
        good = z if status in ("ok", "skip", "reset") else None
        self.safety.note_reading(good, self.airborne)
        if self.in_air and is_angle(extra.get("mode_w")) is False:
            self.mode_bad_since = self.mode_bad_since or t
            if t - self.mode_bad_since >= 0.3:
                raise Crashed(f"OSD mode no longer ANGLE (width {extra['mode_w']}): crashed")
        else:
            self.mode_bad_since = None
        command = None
        note = ""
        last_good = self.est.last_good_t if self.est.last_good_t is not None else t
        alt_stale = self.in_air and t - last_good > self.safety.stale_s
        if guidance is not None:
            speed = self._speed(t, extra.get("speed"))
            # Later (magenta) gates only when this flight looks ahead: ~4 ms a frame.
            det, frame = getattr(io, "det", None), getattr(io, "frame", None)
            future = (det.detect_future(frame) if guidance.cfg.get("look_ahead") and det is not None
                      and frame is not None else None)
            ground_h = self._ground_sense(t, h, v, speed, guidance, extra) if self.ground_warn is not None else None
            command = guidance.update(extra.get("gate"), h, v, t, t_grab, speed=speed, blind=alt_stale,
                                      future=future, ground_h=ground_h)
            if ground_h is not None and ground_h < guidance.cfg["ground_warn_m"]:
                note = f"ground detector: camera reads {ground_h:.2f} m above ground"
            self.last_command = command
            if self._stuck(t, good, speed, command, extra.get("damage", 0.0) > 0.03):
                raise Crashed("stuck: no speed and no height change while flying"
                              + (" (damaged-drone icon shown)" if extra.get("damage", 0.0) > 0.03 else ""))
            if good is not None and self._on_ground(t, good, command.height):
                guidance.ground_contact(good, t)
                command.height, command.climb = guidance.height, 0.0
                note = f"ground contact at {good:.1f} m"
                print(f"{note}: holding {guidance.height:.1f} m for a while", flush=True)
            elif (good is not None and guidance.cfg.get("bounce_ground")
                  and bounced(v, self.u_prev, self.u_low_prev, status)):
                guidance.ground_contact(good, t)
                command.height, command.climb = guidance.height, 0.0
                note = f"bounce at {good:.1f} m"
                print(f"{note}: holding {guidance.height:.1f} m for a while", flush=True)
            ref = Track(command.height, command.climb)
        terms, rv, closed = {}, (None, None, None, False), False
        # Blind: in the air, ALT unreadable for longer than safety.stale_s. Cutting throttle
        # here dropped the drone from ~3 m on 2026-10-24, so descend just under the hover
        # estimate with the sticks centred, and only cut after BLIND_MAX_S without a reading.
        last_good = self.est.last_good_t if self.est.last_good_t is not None else t
        stale_for = t - last_good
        blind = (self.in_air and self.hover_estimate is not None and open_u is None
                 and stale_for > self.safety.stale_s)
        # A short dropout while steering (a gate frame behind the readout, 2026-10-24) keeps
        # flying on the throttle that was holding height; only a long one stops the run.
        fly_on = blind and command is not None and stale_for <= self.safety.stale_s + BLIND_FLY_S
        # Tilt compensation (speed experiment, 2026-10-26): forward pitch and roll take lift
        # off the drone; add what the tilt costs on top of the controller and move the
        # throttle band with it, so the band doesn't cut it off.
        u_tilt = 0.0
        if (guidance is not None and guidance.cfg.get("tilt_ff") and self.in_air
                and self.hover_estimate is not None and open_u is None):
            u_tilt = tilt_feedforward(float(self.ccfg["hover"]) + self.ctrl.i_term, guidance.pitch_att,
                                      self.sticks[2], guidance.cfg["deg_per_pitch"])
        if blind:
            # The controller's learned hover (feed-forward + integral), not recent throttle:
            # an average taken while recover mode sank at 1 m/s was a sinking throttle, and
            # 0.7 s blind on it dropped the drone 2.2 m (2026-10-24).
            base = float(self.ccfg["hover"]) + self.ctrl.i_term + u_tilt
            # While steering, the gate still says climb or sink (its place in the image), so
            # height stays under vision control: a tree behind the readout at gate 9 kept ALT
            # unreadable for 4.5 s on 2026-10-24 and ended two attempts.
            u = (base + BLIND_CLIMB_GAIN * command.climb) if fly_on else base - BLIND_BELOW_HOVER
            u = min(max(u, base + THROTTLE_BAND[0]), base + THROTTLE_BAND[1])
        elif open_u is not None:
            u = open_u
        elif ref is None or h is None:
            u = 0.0
        else:
            rv = ref(t)
            u, terms = self.ctrl.update(dt, h, v, *rv)
            u += u_tilt
            if self.in_air and self.hover_estimate is not None:
                # A reading after a short ALT gap can make the filter's vertical speed jump;
                # the D term then held 0.45 throttle for 0.5 s and launched the drone from 10
                # to 17 m into a tree (2026-10-24). Hover+0.12 still climbs at ~1.5 g.
                base = float(self.ccfg["hover"]) + self.ctrl.i_term + u_tilt
                u = min(max(u, base + THROTTLE_BAND[0]), base + THROTTLE_BAND[1])
            closed = True
        if blind and stale_for <= self.safety.stale_s + BLIND_MAX_S:
            # Suppress the stale-reading abort while descending blind; the height estimate
            # is meaningless now, so skip the ceiling check too.
            reason = self.safety.check(t, t, None, 0, False)
        else:
            reason = self.safety.check(t, self.est.last_good_t, h, terms.get("sat", 0), closed)
        if not reason and io.kill_pressed():
            reason = "kill key (F12)"
        if not reason and h is None and closed is False and command is not None and not blind:
            reason = "altitude estimate unavailable"
        soft = ""
        if not reason and blind and command is not None and not fly_on:
            soft = "ALT unreadable in the air"
        elif not reason and command is not None and command.abort:
            # Height is still trusted: keep the altitude controller's throttle (holding
            # command.height) and centre the sticks. The caller then levels and lands.
            soft = command.abort
        if reason:
            u = 0.0
        steer = command is not None and not reason and not soft
        yaw, pitch, roll = (command.yaw, command.pitch, command.roll) if steer else (0.0, 0.0, 0.0)
        if sticks is not None and command is None and not reason:
            yaw, pitch, roll = sticks
            steer = True
        if steer:
            # Ease the sticks instead of jumping: the guidance switches pitch on and off and
            # the flying looked jerky (user, 2026-10-25). Stops and aborts stay immediate.
            k = 1.0 - math.exp(-dt / STICK_TAU_S)
            self.sticks = tuple(a + k * (b - a) for a, b in zip(self.sticks, (yaw, pitch, roll)))
            yaw, pitch, roll = self.sticks
        else:
            self.sticks = (0.0, 0.0, 0.0)
        io.send(u, yaw, pitch, roll)
        # For the bounce check on the next tick: only closed-loop throttle in the air has a band.
        in_band = closed and self.in_air and self.hover_estimate is not None and not reason
        self.u_prev = u if in_band else None
        self.u_low_prev = (float(self.ccfg["hover"]) + self.ctrl.i_term + u_tilt + THROTTLE_BAND[0]) if in_band else None
        g = extra.get("gate")
        row = dict(t=round(t, 4), phase=phase, dt=round(dt, 4), raw_h=z, read_status=status,
                   h_filt=None if h is None else round(h, 3), v_filt=round(v, 3),
                   h_ref=None if rv[0] is None else round(rv[0], 3), v_ref=None if rv[1] is None else round(rv[1], 3),
                   u=round(u, 4), u_p=terms.get("u_p"), u_d=terms.get("u_d"), u_i=terms.get("u_i"), sat=terms.get("sat"),
                   u_tilt=round(u_tilt, 4), ground_h=None if self.ground_h is None else round(self.ground_h, 2),
                   gate_visible=int(g.visible) if g else "", gate_x=round(g.x, 3) if g and g.visible else "",
                   gate_y=round(g.y, 3) if g and g.visible else "", gate_size=round(g.size, 4) if g and g.visible else "",
                   gate_clipped=int(g.clipped) if g and g.visible else "", alt_text=extra.get("alt_text", ""),
                   alt_score=round(extra.get("alt_score", 0), 3) if "alt_score" in extra else "",
                   abort=reason or (f"guidance: {soft}" if soft else ("blind descent" if blind else note)),
                   yaw=yaw, pitch=pitch, roll=roll, guidance_state=command.state if command else "",
                   gate_pass_candidates=command.passes if command else 0,
                   speed_ms=None if extra.get("speed") is None else round(extra["speed"], 2),
                   climb=round(command.climb, 3) if command else None, mode_w=extra.get("mode_w"),
                   damage=extra.get("damage"))
        self.csv.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in COLS})
        self.rows.append(row)
        if io.frame is not None:
            self._snapshots(t, z, extra, g, phase)
        if not io.is_sim:
            io.wait_until(t_grab + period)
        else:
            io.wait_until(t + period)
        if reason:
            raise Aborted(reason)
        if soft:
            raise GuidanceStop(soft)
        return t, h, v, u

    def _speed(self, t, ms):
        """Forward speed from the OSD; a missed read keeps the last one for 0.5 s."""
        if ms is not None:
            self.last_speed = (ms, t)
            return ms
        last, at = self.last_speed
        return last if last is not None and t - at <= 0.5 else None

    def _stuck(self, t, z, speed, command, hit):
        """The pilot asks to move but nothing moves: OSD speed < 0.3 m/s and ALT within 0.3 m
        for STUCK_S (STUCK_HIT_S with the damaged-drone icon showing). 2026-10-24: the drone
        lay crashed on the road for 11 minutes, mode still ANGLE, pilot still "crossing"."""
        wants = abs(command.pitch) > 0.01 or abs(command.yaw) > 0.02 or abs(command.climb) > 0.1
        if not (self.in_air and wants and speed is not None and speed < 0.3 and z is not None):
            self.still_since = None
            return False
        if self.still_since is None or abs(z - self.still_h) > 0.3:
            self.still_since, self.still_h = t, z
            return False
        return t - self.still_since >= (STUCK_HIT_S if hit else STUCK_S)

    # Ground readings are trusted on approach, not inside a crossing (see _ground_sense).
    def _ground_sense(self, t, h, v, speed, guidance, extra):
        """Camera ground detector: every 0.2 s, estimate the height above the ground
        from this frame and one ~1/15 s older (background thread), filter it
        (GroundWarn) and return the filtered height above ground (m), or None
        when unreliable. Guidance (pilot/guidance.py, ground_h) acts on it
        before contact, instead of only reacting after a hit."""
        if self.io.frame is None:
            return None
        small = cv2.resize(self.io.frame, (160, 90), interpolation=cv2.INTER_AREA)
        if small.ndim == 3:
            small = cv2.cvtColor(small, cv2.COLOR_BGRA2GRAY if small.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
        self.ground_frames = (self.ground_frames + [(t, small)])[-6:]
        for tr, est, info, sp in self.ground_worker.take():
            self.ground_warn.add(tr, est, info, sp)
        if t >= self.next_ground and speed is not None and abs(self.sticks[2]) <= 0.15:
            older = [f for f in self.ground_frames if 0.05 <= t - f[0] <= 0.12]
            if older:
                t0, f0 = older[-1]
                elev = guidance.cfg["camera_tilt_deg"] - attitude_deg(self.sticks[1])
                if self.ground_worker.submit(t, f0, small, t - t0, speed, -v, elev):
                    self.next_ground = t + 0.2
        self.ground_h = self.ground_warn.height(t)
        # Readings stay live on the approach, however big the gate: in flight
        # 20261027_160010 the old size>=0.15 cutoff blinded guidance for the
        # last seconds before the gate while the filtered height fell to
        # 0.75 m, no ground floor was set, and the drone hit the bottom rung.
        # Inside a crossing no new reading is trusted (the gate frame spoils
        # the match and lifting there could hit the top bar); guidance holds
        # the floor latched on approach until the crossing ends instead.
        if h is None or self.ground_h is None or guidance.crossing_since is not None:
            return None
        return self.ground_h

    def _on_ground(self, t, z, wanted):
        """True once the guidance has wanted the drone 0.5 m lower for 1 s but ALT hasn't
        moved: the ground is in the way. ALT counts from the start point, so on a hillside
        "18.1 m" can be the road surface (the drone sat there for minutes, 2026-10-24)."""
        if wanted >= z - 0.5 or self.gc_h0 is None or abs(z - self.gc_h0) > 0.15:
            self.gc_t0, self.gc_h0 = t, z
            return False
        if t - self.gc_t0 >= 1.0:
            self.gc_t0, self.gc_h0 = t, z
            return True
        return False

    def _snapshots(self, t, z, extra, g, phase):
        rel = t - self.rows[0]["t"]
        if z is None and rel >= self.next_alt_fail:
            # Every unreadable crop (5/s at most) is a candidate template: label and add
            # them with core.alt_reader.save_crop_glyphs.
            self.next_alt_fail = rel + 0.2
            (self.folder / "alt_fail").mkdir(exist_ok=True)
            cv2.imwrite(str(self.folder / "alt_fail" / f"{rel:06.2f}_{phase}.png"), alt_crop(self.io.frame))
        if rel >= self.next_alt_png:
            self.next_alt_png = rel + 0.5
            name = f"{rel:06.2f}_{'none' if z is None else z}.png"
            cv2.imwrite(str(self.folder / "alt" / name), alt_crop(self.io.frame))
        if self.record_dt and rel >= self.next_rec:
            self.next_rec = rel + self.record_dt
            save_flow_frame(self.io.frame, self.folder / "flow", t)
        if rel >= self.next_view:
            self.next_view = rel + 1.0
            small = cv2.resize(self.io.frame, (960, 540), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(self.folder / "view" / f"{rel:06.2f}_{phase}.jpg"), draw(small, g, phase),
                        [cv2.IMWRITE_JPEG_QUALITY, 80])

    def run_for(self, phase, seconds, **kw):
        end = self.io.now() + seconds
        out = []
        while self.io.now() < end:
            out.append(self.tick(phase, **kw))
        return out

    def takeoff(self):
        a = self.args
        self.safety.reset(self.io.now())
        self.t_last = self.io.now()
        # 1. arm at zero throttle
        self.run_for("arm", 2.0, open_u=0.0)
        h0, _ = self.est.now(self.io.now())
        if h0 is None:
            raise Aborted("no ALT reading on the ground; is the readout visible?")
        # 2. slow throttle ramp until the drone leaves the ground
        u = a.ramp_start
        t0 = self.io.now()
        while True:
            u = a.ramp_start + a.ramp_rate * (self.io.now() - t0)
            if u > a.ramp_max:
                raise Aborted(f"no liftoff by throttle {a.ramp_max}; check the controller is selected")
            _, h, v, _ = self.tick("liftoff", open_u=u)
            if h is not None and h - h0 >= 0.15 and v > 0.1:
                break
        # The ramp keeps rising while the drone climbs far enough to see. Backing off one
        # second of ramp put the estimate within 0.01 of the true hover in the simulator
        # for true hovers of 0.22, 0.33 and 0.45. The game needs more: on 2026-10-24 it
        # lifted off at 0.291 (ramp 0.025/s) and then held height at 0.22-0.24, so the
        # gate pilot passes --hover-backoff 0.06.
        hover = round(u - getattr(a, "hover_backoff", a.ramp_rate * 1.0), 4)
        self.hover_estimate = hover
        self.ccfg["hover"] = hover
        self.airborne = True
        self.in_air = True
        print(f"Lifted off at throttle {u:.3f}; hover estimate {hover:.3f}", flush=True)
        # 3. climb, 4. hold
        rc = self.cfg["reference"]
        h_now, _ = self.est.now(self.io.now())
        prof = MoveProfile(h_now, a.height, self.io.now(), float(rc["v_max"]), float(rc["a_max"]))
        self.run_for("climb", prof.T + 1.0, ref=prof)
        return hover

    def land(self):
        rc = self.cfg["reference"]
        # 5. land
        self.airborne = False
        h_now, _ = self.est.now(self.io.now())
        prof = MoveProfile(h_now, 0.3, self.io.now(), 0.6, float(rc["a_max"]))
        self.run_for("land", prof.T + 0.5, ref=prof)
        self.in_air = False
        self.run_for("cut", 1.0, open_u=0.0)

    def fly(self):
        hover = self.takeoff()
        hold = self.run_for("hold", self.args.hold, ref=Hold(self.args.height))
        self.land()
        return hover, hold


def summarize(rows, hover, args):
    hold = [r for r in rows if r["phase"] == "hold"]
    res = {"hover_from_liftoff": hover}
    if hold:
        last = hold[len(hold) // 2:]
        hs = [r["h_filt"] for r in hold if r["h_filt"] is not None]
        res["hover_from_hold"] = round(statistics.fmean(r["u"] for r in last), 4)
        res["height_mean_m"] = round(statistics.fmean(hs), 2) if hs else None
        res["height_max_err_m"] = round(max(abs(h - args.height) for h in hs), 2) if hs else None
        res["alt_readable_pct"] = round(100 * sum(r["raw_h"] is not None for r in hold) / len(hold), 1)
        vis = [r for r in hold if r["gate_visible"] == 1]
        if hold[0]["gate_visible"] != "":
            res["gate_visible_pct"] = round(100 * len(vis) / len(hold), 1)
            if vis:
                res["gate_mean_x"] = round(statistics.fmean(r["gate_x"] for r in vis), 3)
                res["gate_mean_y"] = round(statistics.fmean(r["gate_y"] for r in vis), 3)
                res["gate_mean_size"] = round(statistics.fmean(r["gate_size"] for r in vis), 4)
        dts = [r["dt"] for r in rows]
        res["loop_hz"] = round(1 / statistics.median(dts), 1)
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sim", action="store_true")
    p.add_argument("--height", type=float, default=3.0)
    p.add_argument("--hold", type=float, default=10.0)
    p.add_argument("--ramp-start", type=float, default=0.10)
    p.add_argument("--ramp-rate", type=float, default=0.05, help="throttle per second while finding liftoff")
    p.add_argument("--ramp-max", type=float, default=0.60)
    p.add_argument("--ki", type=float, default=0.02)
    p.add_argument("--i-max", type=float, default=0.08)
    p.add_argument("--angle-button", default="A", help="button bound to Angle in Uncrashed; '' for none")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    args = p.parse_args()
    cfg = C.apply_overrides(C.load(), args.set)

    folder = ROOT / "logs" / (time.strftime("%Y%m%d_%H%M%S") + ("_hover_sim" if args.sim else "_hover"))
    folder.mkdir(parents=True, exist_ok=True)
    io = make_sim(cfg) if args.sim else LiveIO(cfg, args.angle_button or None)
    result, hover = {}, None
    flight = Flight(io, cfg, args, folder)
    try:
        if not args.sim:
            print("Controller connected: throttle 0, angle button held.")
            print("In Uncrashed: select the Xbox controller, press T to reset, then hold F8 here to fly. F12 = cut.",
                  flush=True)
            while not io.f8():
                if io.kill_pressed():
                    raise Aborted("F12 before start")
                io.send(0.0)
                time.sleep(0.02)
            print("Starting in 2 s.", flush=True)
            end = time.perf_counter() + 2
            while time.perf_counter() < end:
                io.send(0.0)
                time.sleep(0.02)
        hover, _ = flight.fly()
        result["status"] = "complete"
    except Aborted as e:
        result.update(status="aborted", abort=str(e))
        print(f"ABORT: {e}", flush=True)
    except KeyboardInterrupt:
        result.update(status="stopped", abort="ctrl+c")
    finally:
        try:
            io.send(0.0)
        finally:
            flight.csv_file.close()
    result.update(summarize(flight.rows, hover, args))
    with open(folder / "meta.json", "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "config": cfg, "controller_used": flight.ccfg, "result": result}, f, indent=2)
    print(json.dumps(result, indent=2), flush=True)
    if not io.is_sim:
        io.park()
    io.close()
    print(f"log: {folder}")


if __name__ == "__main__":
    main()
