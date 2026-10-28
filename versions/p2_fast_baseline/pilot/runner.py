"""One long-running process that owns the virtual controller and runs jobs.

    python pilot/runner.py                  # leave it running (Claude starts it in the background)
    python tools/job.py gate -- --set gate_pilot.max_gates=3      # then submit jobs

Why: each pilot used to connect its own virtual controller and remove it on exit.
With none connected, Uncrashed falls back to any other controller (the DJI remote
flew to 70 m that way), and every run needed F8 and F12 at the keyboard. The runner
keeps one controller at zero throttle with Angle held between jobs, restarts the
race itself (T), and reads the game window, not the screen.

Jobs are JSON files in jobs/; each result goes to results/<same name>.json. Only these:
  {"type": "gate", "argv": ["--height", "2", "--set", "gate_pilot.max_gates=3"], "restart": true}
  {"type": "restart"}                       T (RestartRace), then zero throttle while it arms
  {"type": "key", "key": "T"}               only keys in KEYS
  {"type": "button", "button": "RT", "hold_s": 0.3}    a pad button or trigger
  {"type": "shot"}                          save the game window to logs/shots/
  {"type": "quit", "pause": true}           ESC (pause the game) first, then exit
"gate" argv goes through pilot/gate_run.py's own argument checks. F12 during a flight
cuts throttle as before; the runner keeps running.
"""
import importlib
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ROOT, config as C  # noqa: E402
from core import window as W  # noqa: E402
from core.alt_reader import AltReader  # noqa: E402
from core.gamepad import BUTTONS, Gamepad  # noqa: E402
import core.alt_reader as alt_mod  # noqa: E402
import core.controller as controller_mod  # noqa: E402
import core.estimator as estimator_mod  # noqa: E402
import core.gate_detector as detector_mod  # noqa: E402
import core.osd_mode as osd_mode  # noqa: E402
import core.reference as reference_mod  # noqa: E402
import core.speed_reader as speed_mod  # noqa: E402
import pilot.guidance as guidance_mod  # noqa: E402
import pilot.hover_test as hover_test_mod  # noqa: E402
from pilot import gate_run  # noqa: E402

JOBS, RESULTS = ROOT / "jobs", ROOT / "results"
KEYS = {"T", "R", "ESC", "TAB", "ENTER"}
ARM_S = 3.0


class Runner:
    def __init__(self):
        self.cfg = C.load()
        self.hwnd = W.find_game_window()
        if not self.hwnd:
            raise SystemExit("Uncrashed is not running (python tools/game.py launch)")
        self.cap = W.WindowCapture(self.hwnd)
        self.cap.grab(timeout=3.0)
        self.pad = Gamepad(self.cfg["controls"])
        self.angle = getattr(self.pad.vg.XUSB_BUTTON, BUTTONS["A"])
        self.alt = AltReader(ROOT / "data" / "alt_templates")
        self.state = "idle"
        self.job = None
        self.next_beat = 0.0
        self._beat_lock = threading.Lock()
        JOBS.mkdir(exist_ok=True)
        RESULTS.mkdir(exist_ok=True)
        # Flights block the main loop for a minute; the heartbeat must keep going.
        threading.Thread(target=self._beat_forever, daemon=True).start()

    def _beat_forever(self):
        while True:
            self.beat()
            time.sleep(0.2)

    # ------------------------------------------------------------ helpers
    def safe(self):
        """Zero throttle, sticks centred, Angle held, triggers released."""
        self.pad.trigger("L", 0)
        self.pad.trigger("R", 0)
        self.pad.pad.press_button(button=self.angle)
        self.pad.send(0.0)

    def hold_safe(self, seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            self.safe()
            self.beat()
            time.sleep(0.02)

    def beat(self, force=False):
        now = time.time()
        if (force or now >= self.next_beat) and self._beat_lock.acquire(blocking=False):
            self.next_beat = now + 1.0
            # Windows refuses the replace while tools/job.py has the file open. Skip this
            # beat: the runner dying would remove the controller (see the module docstring).
            try:
                tmp = RESULTS / "_runner.tmp"
                tmp.write_text(json.dumps({"pid": os.getpid(), "state": self.state, "job": self.job, "time": now}))
                os.replace(tmp, RESULTS / "_runner.json")
            except OSError:
                self.next_beat = now + 0.1
            finally:
                self._beat_lock.release()

    def read_alt(self):
        _, img, _ = self.cap.grab(timeout=1.0)
        h, text, score = self.alt.read(img)
        return h

    def press_key(self, key):
        if key.upper() not in KEYS:
            raise ValueError(f"key {key!r} not allowed")
        if not W.press(self.hwnd, key):
            raise RuntimeError("could not bring the game to the front")

    # ------------------------------------------------------------ jobs
    def mode(self):
        _, img, _ = self.cap.grab(timeout=1.0)
        return osd_mode.mode_width(img)

    def restart(self):
        self.safe()
        self.press_key("T")
        self.hold_safe(ARM_S)
        # A crash switched the game to "3D" mode, and that survives T. Angle is switched on
        # by a press of A, so let go of it and press again until the OSD reads ANGLE.
        for _ in range(3):
            if osd_mode.is_angle(self.mode()) is not False:
                break
            self.pad.pad.release_button(button=self.angle)
            self.pad.send(0.0)
            time.sleep(0.4)
            self.hold_safe(0.6)
        return {"alt_after_restart": self.read_alt(), "mode_width": self.mode()}

    def gate(self, job):
        # Pick up edits to the pilot without restarting the runner (a restart drops the
        # controller). Dependencies first: gate_run copies names out of the other two.
        global gate_run
        for mod in (alt_mod, osd_mode, speed_mod, reference_mod, estimator_mod, controller_mod, detector_mod,
                    guidance_mod, hover_test_mod):
            importlib.reload(mod)
        gate_run = importlib.reload(gate_run)
        p = gate_run.build_parser(modes_required=False)
        try:
            args = p.parse_args([str(a) for a in job.get("argv", [])])
            cfg = gate_run.check_args(p, args)
        except SystemExit:
            return {"status": "error", "reason": "bad argv (see runner output)"}
        out = {}
        if job.get("restart", True):
            out.update(self.restart())
            if out["alt_after_restart"] is None or abs(out["alt_after_restart"]) > 0.3:
                out.update(status="error", reason="drone not on the ground after restart")
                return out
            if osd_mode.is_angle(out["mode_width"]) is False:
                out.update(status="error", reason="OSD mode is not ANGLE after restart")
                return out
        folder = ROOT / "logs" / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_gate_live")
        folder.mkdir(parents=True)
        io = gate_run.LiveIO(cfg, args.angle_button, pad=self.pad, cap=self.cap)
        reset = []

        def finish():
            # Still hovering here: T puts the drone back on the start pad, then zero
            # throttle so it stays there and re-arms. Better than landing on the course.
            reset.append(W.press(self.hwnd, "T"))
            self.safe()

        try:
            out.update(gate_run.fly_live(io, cfg, args, folder, finish=finish))
        finally:
            io.close()
            self.safe()
            if not reset:  # safety cut or error: the drone is down somewhere, send it home
                W.press(self.hwnd, "T")
                self.hold_safe(0.5)
        out["log"] = str(folder)
        return out

    def button(self, job):
        name = job["button"].upper()
        hold = min(2.0, float(job.get("hold_s", 0.3)))
        if name in ("LT", "RT"):
            self.pad.trigger(name[0], 1.0)
            self.pad.send(0.0)
            time.sleep(hold)
            self.pad.trigger(name[0], 0.0)
        else:
            self.pad.press(name, hold)
        self.hold_safe(0.5)
        return {"pressed": name}

    def ensure_capture(self):
        """The game restarted (new window) or the capture ended: capture the new window."""
        hwnd = W.find_game_window()
        if not hwnd:
            raise RuntimeError("Uncrashed is not running")
        if hwnd != self.hwnd or self.cap.closed:
            self.cap.close()
            self.hwnd, self.cap = hwnd, W.WindowCapture(hwnd)
            self.cap.grab(timeout=3.0)
            print(f"Capturing the game window again (hwnd {hwnd})", flush=True)

    def run_job(self, path):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("type") != "quit":
            self.ensure_capture()
        kind = job.get("type")
        self.state, self.job = "running", path.name
        self.beat(force=True)
        print(f"[{time.strftime('%H:%M:%S')}] job {path.name}: {job}", flush=True)
        t0 = time.time()
        try:
            if kind == "gate":
                res = self.gate(job)
            elif kind == "restart":
                res = self.restart()
            elif kind == "key":
                self.press_key(job["key"])
                res = {"pressed": job["key"]}
            elif kind == "button":
                res = self.button(job)
            elif kind == "shot":
                from tools.game import shot
                out, _ = shot(self.hwnd, scale=float(job.get("scale", 0.5)))
                res = {"shot": str(out)}
            elif kind == "quit":
                if job.get("pause", True):
                    self.press_key("ESC")
                res = {"quit": True}
            else:
                res = {"status": "error", "reason": f"unknown job type {kind!r}"}
        except Exception as e:
            traceback.print_exc()
            res = {"status": "error", "reason": f"{type(e).__name__}: {e}"}
        finally:
            self.safe()
        res.setdefault("status", "ok")
        res.update(job=job, seconds=round(time.time() - t0, 1))
        tmp = RESULTS / (path.stem + ".tmp")
        tmp.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, RESULTS / path.name)
        path.unlink()
        print(json.dumps({k: v for k, v in res.items() if k != "job"}, default=str), flush=True)
        self.state, self.job = "idle", None
        self.beat(force=True)
        return kind != "quit"

    def loop(self):
        print(f"Runner ready (pid {os.getpid()}). Controller at zero throttle, Angle held. "
              f"Jobs: {JOBS}", flush=True)
        next_scan = 0.0
        while True:
            self.safe()
            self.beat()
            if time.perf_counter() >= next_scan:
                next_scan = time.perf_counter() + 0.25
                jobs = sorted(JOBS.glob("*.json"))
                try:
                    if jobs and not self.run_job(jobs[0]):
                        return
                except Exception:  # a broken job file must not stop the runner
                    traceback.print_exc()
                    jobs[0].replace(jobs[0].with_suffix(".bad"))
                    self.state, self.job = "idle", None
            time.sleep(0.02)

    def close(self):
        self.pad.pad.release_button(button=self.angle)
        self.pad.min_throttle()
        self.cap.close()
        (RESULTS / "_runner.json").unlink(missing_ok=True)


def main():
    r = Runner()
    try:
        r.loop()
    except KeyboardInterrupt:
        print("Ctrl+C", flush=True)
    finally:
        r.close()
    print("Runner stopped. The virtual controller is gone now.", flush=True)


if __name__ == "__main__":
    main()
