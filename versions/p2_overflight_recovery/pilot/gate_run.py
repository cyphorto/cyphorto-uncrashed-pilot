"""First-gate visual approach in Uncrashed. Default use: offline --replay; --live enables control."""
import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ROOT, config as C
from core.alt_reader import AltReader
from core.gate_detector import GateDetector, draw
from core.reference import Hold
from pilot.guidance import GateGuidance
from pilot.hover_test import Aborted, Crashed, Flight, GuidanceStop, LiveIO


class GateFlight(Flight):
    """finish: called while still hovering at the end of a flight, instead of landing.
    The runner passes one that restarts the race (T), so the drone goes back to the start
    rather than dropping onto the course (it landed on a gate on 2026-10-24)."""
    finish = None

    def end(self, height):
        self.run_for("level", 1.5, ref=Hold(height))
        if self.finish is not None:
            self.finish()
        else:
            self.land()

    def fly(self):
        try:
            self.takeoff()
            return self._approach()
        except Crashed as crash:
            if self.finish is None:
                raise  # handled as an abort: throttle cut
            self.finish()  # restart the race straight away; hovering a broken drone is pointless
            return {"status": "crashed", "reason": str(crash),
                    "candidate_passes": self.last_command.passes if self.last_command else 0}
        except GuidanceStop as stop:
            # Height is still trusted: centre the sticks and hold height.
            h_now, _ = self.est.now(self.io.now())
            hold_h = self.last_command.height if self.last_command else (h_now or self.args.height)
            # Hold where it is (or the guidance target, if higher). "At least --height" made
            # sense when ALT was taken for height above ground; at -43 m it ordered a climb
            # to +2 m and the throttle saturated (2026-10-25).
            self.end(max(hold_h, h_now) if h_now is not None else hold_h)
            return {"status": "stopped", "reason": str(stop),
                    "candidate_passes": self.last_command.passes if self.last_command else 0}

    def _probe_roll(self):
        """Which way does +roll move the drone? Hover facing gate 1, roll +0.15 for 1.5 s with
        no forward pitch, and see where the gate goes: moving right shifts it left (x falls)."""
        def gate_x(rows):
            xs = [r["gate_x"] for r in rows if r["gate_visible"] == 1]
            return sum(xs)/len(xs) if xs else None
        h = self.args.height
        for _ in range(30):
            self.tick("probe_hold", ref=Hold(h), sticks=(0, 0, 0))
        before = gate_x(self.rows[-30:])
        end = self.io.now()+1.5
        while self.io.now() < end:
            self.tick("probe_roll", ref=Hold(h), sticks=(0, 0, 0.15))
        end = self.io.now()+1.0
        while self.io.now() < end:
            self.tick("probe_after", ref=Hold(h), sticks=(0, 0, 0))
        after = gate_x(self.rows[-25:])
        self.end(h)
        moved = None if before is None or after is None else round(after-before, 3)
        verdict = None if moved is None else ("+roll moves RIGHT (roll_sign 1 is right)" if moved < 0
                                              else "+roll moves LEFT (set roll_sign -1)")
        return {"status": "probe", "gate_x_before": before, "gate_x_after": after, "shift": moved,
                "verdict": verdict}

    def _approach(self):
        # Require actual settled altitude before adding lateral commands.
        stable_since = None
        end = self.io.now()+8.0
        while self.io.now() < end:
            t, h, v, _ = self.tick("settle", ref=Hold(self.args.height))
            # The height control wobbles about +-0.25 m; 0.35 m / 0.5 m/s for 0.6 s
            # sometimes never happened within 8 s (2026-10-24).
            if h is not None and abs(h-self.args.height) < 0.5 and abs(v) < 0.6:
                stable_since = t if stable_since is None else stable_since
                if t-stable_since >= 0.4:
                    break
            else:
                stable_since = None
        else:
            raise GuidanceStop("altitude did not settle before gate approach")
        if getattr(self.args, "probe", None) == "roll":
            return self._probe_roll()
        self.guidance = GateGuidance(self.cfg["gate_pilot"])
        end = self.io.now()+self.args.duration
        while self.io.now() < end:
            self.tick("gate", guidance=self.guidance)
            if self.last_command.done:
                # Image transition is only a candidate pass, not authoritative scoring.
                self.end(self.last_command.height)
                return {"status":"complete", "candidate_passes":self.last_command.passes,
                        "note":"Visual gate transition detected; confirm passage in saved images"}
        raise GuidanceStop("gate approach time limit reached")


def flight_summary(rows):
    """What a flight log says at a glance; goes into meta.json and the runner's results."""
    if not rows:
        return {}
    air = [r for r in rows if r["phase"] not in ("arm", "cut")]
    hs = [r["h_filt"] for r in air if r["h_filt"] is not None]
    states = {}
    for r in rows:
        if r["guidance_state"]:
            states[r["guidance_state"]] = states.get(r["guidance_state"], 0)+1
    # Throttle while the height is steady and read: the drone's real hover throttle.
    steady = [r["u"] for r in rows if r["phase"] in ("settle", "gate", "level") and r["raw_h"] is not None
              and abs(r["v_filt"]) < 0.15 and r["pitch"] == 0]
    gates = sum(1 for a, b in zip(rows, rows[1:]) if b["guidance_state"] in ("reacquire", "finished")
                and a["guidance_state"] != b["guidance_state"])
    return {"seconds": round(rows[-1]["t"]-rows[0]["t"], 1), "last_phase": rows[-1]["phase"], "gates": gates,
            "hover_measured": round(sorted(steady)[len(steady)//2], 3) if len(steady) >= 10 else None,
            "max_height_m": round(max(hs), 2) if hs else None,
            "alt_unreadable_pct": round(100*sum(r["raw_h"] is None for r in air)/len(air), 1) if air else None,
            "gate_seen_pct": round(100*sum(r["gate_visible"] == 1 for r in air)/len(air), 1) if air else None,
            "guidance_states": states}


def fly_live(io, cfg, args, folder, finish=None):
    """One gate flight on a connected LiveIO. Writes meta.json and returns the result."""
    flight = None
    result = {"status":"error"}
    try:
        flight = GateFlight(io, cfg, args, folder)
        flight.finish = finish
        result = flight.fly()
    except (Aborted, KeyboardInterrupt) as exc:
        result = {"status":"aborted", "reason":str(exc) or "Ctrl+C"}
    except Exception as exc:
        result = {"status":"error", "reason":f"{type(exc).__name__}: {exc}"}
    finally:
        io.send(0)
        if flight is not None:
            flight.csv_file.close()
            result["summary"] = flight_summary(flight.rows)
        meta = {"args":{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
                "config":cfg, "result":result,
                "controller_used":flight.ccfg if flight else None,
                "hover_estimate":flight.hover_estimate if flight else None}
        (folder/"meta.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    return result


def run_live(cfg, args, folder):
    io = None
    result = {"status":"error"}
    try:
        io = LiveIO(cfg, args.angle_button)
        print("Select XboxController in Uncrashed. Confirm ANGLE mode and neutral sticks.", flush=True)
        print("Reset with T. Hold F8 to begin. Hold F12 to cut throttle.", flush=True)
        wait_end = time.perf_counter()+300
        while not io.f8():
            if io.kill_pressed() or time.perf_counter() >= wait_end:
                raise Aborted("cancelled or setup timed out")
            io.send(0)
            time.sleep(0.01)
        print("Starting in 3 seconds", flush=True)
        end = time.perf_counter()+3
        while time.perf_counter() < end:
            if io.kill_pressed():
                raise Aborted("F12 during countdown")
            io.send(0)
            time.sleep(0.01)
        result = fly_live(io, cfg, args, folder)
    except (Aborted, KeyboardInterrupt) as exc:
        result = {"status":"aborted", "reason":str(exc) or "Ctrl+C"}
    except Exception as exc:
        result = {"status":"error", "reason":str(exc)}
    finally:
        print(json.dumps(result, indent=2), flush=True)
        if io is not None:
            io.send(0)
            # If the virtual controller vanished now, Uncrashed would fall back to the DJI
            # remote and fly on its spring-centred (50%) throttle.
            io.park()
            io.close()
    return result


def replay(cfg, args, folder):
    """Recorded images drive hypothetical commands. No gamepad is constructed."""
    import cv2
    source = args.replay
    with (source/"frames.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    cap = cv2.VideoCapture(str(source/"video.avi"))
    if not cap.isOpened():
        raise ValueError("Cannot open source video")
    det = GateDetector()
    reader = AltReader(ROOT/"data"/"alt_templates")
    guide = GateGuidance(cfg["gate_pilot"])
    counts = {}
    examples = folder/"view"
    examples.mkdir()
    try:
        with (folder/"decisions.csv").open("w",newline="") as f:
            fields = ["frame","t","state","yaw","pitch","height_target","visible","x","y","size",
                      "raw_altitude","candidate_passes","abort"]
            writer = csv.DictWriter(f,fieldnames=fields)
            writer.writeheader()
            for i,row in enumerate(rows):
                ok, frame = cap.read()
                if not ok:
                    raise ValueError("Video shorter than input log")
                t = float(row["capture_start_s"])
                g = det.detect(frame)
                altitude, _, _ = reader.read(frame) if reader.ready else (None,"",0)
                # Replay isolates steering decisions assuming a settled hover. It
                # is not a flight simulation: commands cannot alter recorded images.
                cmd = guide.update(g,args.height,0.0,t,t)
                counts[cmd.state] = counts.get(cmd.state,0)+1
                writer.writerow(dict(frame=i,t=t,state=cmd.state,yaw=cmd.yaw,pitch=cmd.pitch,
                                     height_target=cmd.height,visible=g.visible,x=g.x,y=g.y,size=g.size,
                                     raw_altitude=altitude,candidate_passes=cmd.passes,abort=cmd.abort))
                if i % 20 == 0:
                    overlay=draw(frame,g,f"{cmd.state} Y={cmd.yaw:+.2f} P={cmd.pitch:+.2f}")
                    cv2.imwrite(str(examples/f"{i:05d}.jpg"),overlay)
            if cap.read()[0]:
                raise ValueError("Video longer than input log")
    finally:
        cap.release()
    result={"source":str(source.resolve()),"frames":len(rows),"states":counts,
            "candidate_passes":guide.passes,"controller_connected":False,
            "limitation":"Steering-only replay assumes settled altitude; this is not a closed-loop flight test",
            "config":cfg}
    (folder/"meta.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="config"},indent=2))


def build_parser(modes_required=True):
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=modes_required)
    modes.add_argument("--live",action="store_true")
    modes.add_argument("--replay",type=Path)
    p.add_argument("--height",type=float,default=2.0)
    p.add_argument("--duration",type=float,default=30)
    p.add_argument("--ramp-start",type=float,default=0.1)
    p.add_argument("--ramp-rate",type=float,default=0.025)
    p.add_argument("--ramp-max",type=float,default=0.5)
    p.add_argument("--probe",choices=["roll"],help="instead of racing: a short control test")
    p.add_argument("--hover-backoff",type=float,default=0.06,
                   help="hover estimate = liftoff throttle minus this (game: liftoff 0.291, hover ~0.23)")
    p.add_argument("--ki",type=float,default=0.02)
    p.add_argument("--i-max",type=float,default=0.08)
    p.add_argument("--angle-button",choices=["A","B","X","Y"],default="A")
    p.add_argument("--set",action="append",default=[])
    return p


def check_args(p, args):
    """Load config with the run's overrides and reject unsafe arguments (p.error exits)."""
    cfg=C.apply_overrides(C.load(),args.set)
    guide=GateGuidance(cfg["gate_pilot"])
    vals=(args.height,args.duration,args.ramp_start,args.ramp_rate,args.ramp_max,args.ki,args.i_max)
    if not all(math.isfinite(v) for v in vals):
        p.error("Arguments must be finite")
    if not guide.cfg["min_height"] <= args.height <= guide.cfg["max_height"] < cfg["safety"]["ceiling_m"]:
        p.error("Height bounds must be within the configured ceiling")
    if not 0<args.duration<=900 or not 0<=args.ramp_start<args.ramp_max<=cfg["controller"]["u_max"] or not 0<args.ramp_rate<=0.1:
        p.error("Invalid duration or liftoff ramp")
    if args.ki < 0 or not 0<=args.i_max<=0.2:
        p.error("Invalid integral limits")
    if not 0<=args.hover_backoff<=0.15:
        p.error("Invalid hover backoff")
    return cfg


def main():
    p=build_parser()
    args=p.parse_args()
    cfg=check_args(p, args)
    folder=ROOT/"logs"/(datetime.now().strftime("%Y%m%d_%H%M%S_%f")+("_gate_live" if args.live else "_gate_replay"))
    folder.mkdir(parents=True)
    print(f"Logs: {folder}",flush=True)
    if args.live:
        result=run_live(cfg,args,folder)
        if result["status"]!="complete":
            raise SystemExit(1)
    else:
        replay(cfg,args,folder)


if __name__=="__main__":
    main()
