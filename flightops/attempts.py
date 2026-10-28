r"""Fly recorded attempts through the existing runner and write one record per attempt.

    # 1. start the runner for the version you want to fly (it owns the virtual controller):
    .\.venv\Scripts\python.exe -u versions\v0\pilot\runner.py
    # 2. in another terminal:
    .\.venv\Scripts\python.exe flightops\attempts.py run --version v0 --course roadtrip_full --split smoke --n 3
    .\.venv\Scripts\python.exe flightops\attempts.py run --version workspace --course roadtrip_g10 --split train --n 3 --set gate_pilot.forward_pitch=0.33

Each attempt is one gate job: the runner presses T (restart race), arms, checks ANGLE, takes
off and flies until the pilot stops, then presses T again. This tool adds nothing to the
flight itself; it checks the version, submits the job, waits, and appends a record to
training_data/runs/<split>/attempts.jsonl.

Rules (flightops/common.py check_split): smoke, baseline, eval and heldout fly a frozen
version with no --set; only the heldout split may fly a held-out course, and only once
protocol.json says "heldout_unlocked": true. A frozen version is re-hashed before every
attempt and the run stops if anything in it changed.

Emergency stop: hold F12 (the pilot's kill key) to cut throttle mid-flight; the runner stays
up and keeps the controller at zero. Ctrl+C here only stops submitting new attempts.
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightops import outcome  # noqa: E402
from flightops.common import (ROOT, RUNS, VERSIONS, GuardError, check_split, course,  # noqa: E402
                              load_protocol, tree_hash, version_files)
from flightops.freeze import load_version, verify  # noqa: E402


def version_root(name):
    return ROOT if name == "workspace" else VERSIONS / name


def runner_alive(root, max_age=5.0):
    f = Path(root) / "results" / "_runner.json"
    for _ in range(10):
        try:
            beat = json.loads(f.read_text())
            return beat if time.time() - beat["time"] < max_age else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError):
            time.sleep(0.05)
    return None


def submit(root, job, timeout, poll=0.25):
    """Same protocol as tools/job.py, against the runner living in `root`."""
    root = Path(root)
    if not runner_alive(root):
        raise SystemExit(f"no runner in {root}: start it with  .venv\\Scripts\\python.exe -u "
                         f"{Path(root, 'pilot', 'runner.py').relative_to(ROOT)}")
    jobs, results = root / "jobs", root / "results"
    jobs.mkdir(exist_ok=True)
    name = time.strftime("%Y%m%d_%H%M%S") + f"_{uuid.uuid4().hex[:6]}_{job['type']}"
    tmp = jobs / (name + ".tmp")
    tmp.write_text(json.dumps(job), encoding="utf-8")
    os.replace(tmp, jobs / (name + ".json"))
    out = results / (name + ".json")
    end = time.time() + timeout
    while time.time() < end:
        if out.exists():
            try:
                return name, json.loads(out.read_text(encoding="utf-8"))
            except ValueError:
                pass  # being written
        if not runner_alive(root, 15.0):
            raise SystemExit("runner stopped while the attempt was flying")
        time.sleep(poll)
    raise SystemExit(f"no result after {timeout:.0f} s (job {name})")


def smoke_checks(result, rec):
    """What the first milestone asks to verify, from one attempt's own evidence."""
    lift = rec.get("liftoff_at_s")
    hov = rec.get("hover_measured")
    checks = [
        ("reset: drone on the start pad after T", result.get("alt_after_restart") is not None
         and abs(result["alt_after_restart"]) <= 0.3, f"ALT after restart {result.get('alt_after_restart')}"),
        ("reset: OSD reads ANGLE after T", result.get("mode_width") is not None
         and 0.55 <= result["mode_width"] <= 0.68, f"mode width {result.get('mode_width')}"),
        ("observation: ALT readable", rec.get("alt_unreadable_pct") is not None
         and rec["alt_unreadable_pct"] < 25, f"unreadable {rec.get('alt_unreadable_pct')}%"),
        ("observation: gate detected", rec.get("gate_seen_pct") is not None
         and rec["gate_seen_pct"] > 50, f"gate seen {rec.get('gate_seen_pct')}%"),
        ("control: throttle lifted the drone", lift is not None, f"liftoff at {lift} s"),
        ("control: hover throttle plausible", hov is not None and 0.15 <= hov <= 0.35, f"hover {hov}"),
        ("control: drone moved through a gate", rec.get("gates_selfreported", 0) >= 1,
         f"{rec.get('gates_selfreported')} self-reported passes"),
        ("timing: control loop under 50 ms", rec.get("loop_dt_p95_s") is not None
         and rec["loop_dt_p95_s"] < 0.05, f"dt median {rec.get('loop_dt_median_s')} p95 {rec.get('loop_dt_p95_s')}"),
        ("recording: log and result read", rec.get("log_rows", 0) > 0, f"{rec.get('log_rows')} log rows"),
    ]
    return [{"check": c, "ok": bool(ok), "detail": d} for c, ok, d in checks]


def course_argv(c):
    argv = ["--duration", str(c.get("duration_s", 900))]
    if c.get("gates_target"):
        # a course parameter, not a pilot one: the pilot stops after this many passes
        argv += ["--set", f"gate_pilot.max_gates={int(c['gates_target'])}"]
    return argv


def run_series(version, course_name, split, n, overrides=(), label="", timeout=1200,
               runs=RUNS, protocol=None, submit_fn=submit):
    protocol = protocol or load_protocol()
    check_split(split, version, course_name, protocol, overrides)
    c = course(protocol, course_name)
    root = version_root(version)
    if version != "workspace":
        meta = load_version(version)
        vhash = meta["tree_sha256"]
    out_dir = Path(runs) / split
    out_dir.mkdir(parents=True, exist_ok=True)
    series_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    records = []
    print(f"{split}: {n} attempts of {version} on {course_name}{' - ' + label if label else ''}", flush=True)
    for i in range(n):
        if version == "workspace":
            vhash = tree_hash(version_files(ROOT))
        else:
            bad = verify(version)
            if bad:
                raise SystemExit(f"version {version} changed since it was frozen: {bad[:3]}")
        argv = course_argv(c) + [x for kv in overrides for x in ("--set", kv)]
        job = {"type": "gate", "argv": argv, "restart": True}
        started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        t0 = time.time()
        job_name, res = submit_fn(root, job, timeout)
        ended = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        rows = []
        log = res.get("log")
        if log and Path(log, "log.csv").exists():
            rows = outcome.read_log(Path(log, "log.csv"))
        rec = {
            "attempt_id": f"{series_id}_{i + 1:02d}", "series_id": series_id, "attempt": i + 1,
            "split": split, "version": version, "version_tree_sha256": vhash, "overrides": list(overrides),
            "course": course_name, "course_def": c, "settings": protocol.get("settings", {}),
            "label": label, "started_at": started, "ended_at": ended,
            "wall_seconds": round(time.time() - t0, 1), "job": job_name, "log": log,
            "alt_after_restart": res.get("alt_after_restart"), "mode_width_after_restart": res.get("mode_width"),
            **outcome.build_record(res, rows, c.get("gates_target") or c.get("gates_course")),
        }
        if split == "smoke":
            rec["smoke_checks"] = smoke_checks(res, rec)
        with open(out_dir / "attempts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        records.append(rec)
        print(f"  {i + 1:2}: {rec['gates_selfreported']:2} gates (self-reported)  "
              f"{rec['flight_seconds'] or 0:6.0f} s  {rec['category']}", flush=True)
        for ch in rec.get("smoke_checks", []):
            print(f"      [{'ok' if ch['ok'] else 'FAIL'}] {ch['check']}: {ch['detail']}", flush=True)
    return records


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--version", required=True, help="frozen version name, or 'workspace' (train/valid only)")
    r.add_argument("--course", required=True)
    r.add_argument("--split", required=True)
    r.add_argument("--n", type=int, default=1)
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    r.add_argument("--label", default="")
    r.add_argument("--timeout", type=float, default=1200, help="seconds to wait for one attempt")
    a = p.parse_args()
    try:
        run_series(a.version, a.course, a.split, a.n, a.set, a.label, a.timeout)
    except GuardError as e:
        raise SystemExit(f"refused: {e}")


if __name__ == "__main__":
    main()
