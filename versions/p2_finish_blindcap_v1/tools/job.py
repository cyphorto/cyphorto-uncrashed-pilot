"""Submit a job to pilot/runner.py and wait for its result.

    python tools/job.py gate                          # restart the race (T), then a gate flight
    python tools/job.py gate -- --height 2.5 --set gate_pilot.max_gates=3
    python tools/job.py gate --no-restart
    python tools/job.py gate --repeat 5 --label "pitch 0.3" -- --duration 900   # back-to-back attempts
    python tools/job.py restart | shot | quit
    python tools/job.py key T
    python tools/job.py button RT --hold 0.3
    python tools/job.py status                        # is the runner alive, what is it doing

Prints the result JSON (results/<job>.json). Exit code 2 if the runner isn't running.
With --repeat, runs the attempts one after another (each restarts the race with T) and
prints a table of gates passed per attempt; the series is saved as results/series_<time>.json.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ROOT  # noqa: E402

JOBS, RESULTS = ROOT / "jobs", ROOT / "results"


def runner_alive(max_age=5.0):
    for _ in range(10):  # the runner may be replacing the file right now
        try:
            beat = json.loads((RESULTS / "_runner.json").read_text())
            return beat if time.time() - beat["time"] < max_age else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.05)
    return None


def submit(job, timeout):
    if not runner_alive():
        print("runner is not running: start it with  .venv\\Scripts\\python.exe pilot\\runner.py")
        raise SystemExit(2)
    JOBS.mkdir(exist_ok=True)
    name = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}_{job['type']}"
    tmp = JOBS / (name + ".tmp")
    tmp.write_text(json.dumps(job), encoding="utf-8")
    os.replace(tmp, JOBS / (name + ".json"))
    out = RESULTS / (name + ".json")
    end = time.time() + timeout
    while time.time() < end:
        if out.exists():
            return json.loads(out.read_text(encoding="utf-8"))
        if not runner_alive(15.0):
            raise SystemExit("runner stopped while the job was waiting")
        time.sleep(0.25)
    raise SystemExit(f"no result after {timeout:.0f} s (job {name})")


def main():
    argv = sys.argv[1:]
    passthru = []
    if "--" in argv:
        i = argv.index("--")
        argv, passthru = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("type", choices=["gate", "restart", "shot", "quit", "key", "button", "status"])
    p.add_argument("value", nargs="?", help="key name or button name")
    p.add_argument("--no-restart", action="store_true")
    p.add_argument("--no-pause", action="store_true", help="quit without pausing the game (ESC) first")
    p.add_argument("--hold", type=float, default=0.3)
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--repeat", type=int, default=1, help="gate: this many attempts back to back")
    p.add_argument("--label", default="", help="gate --repeat: what this series is testing")
    a = p.parse_args(argv)
    if a.type == "status":
        print(json.dumps(runner_alive() or {"running": False}))
        return
    job = {"type": a.type}
    if a.type == "gate":
        job.update(argv=passthru, restart=not a.no_restart)
    elif a.type == "key":
        job["key"] = a.value
    elif a.type == "button":
        job.update(button=a.value, hold_s=a.hold)
    elif a.type == "quit":
        job["pause"] = not a.no_pause
    if a.type == "gate" and a.repeat > 1:
        series(job, a.repeat, a.timeout, a.label)
        return
    res = submit(job, a.timeout)
    res.pop("job", None)
    print(json.dumps(res, indent=2, default=str))


def series(job, n, timeout, label):
    """Attempts back to back; one line per attempt as it finishes, then a summary."""
    rows = []
    name = RESULTS / ("series_" + time.strftime("%Y%m%d_%H%M%S") + ".json")
    course = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("race", {}).get("gates")
    print(f"series: {n} attempts{' - ' + label if label else ''}", flush=True)
    for i in range(n):
        res = submit(job, timeout)
        row = {"attempt": i + 1, "gates": res.get("summary", {}).get("gates", res.get("candidate_passes", 0)), "status": res.get("status"),
               "reason": res.get("reason", ""), "seconds": res.get("summary", {}).get("seconds"),
               "log": res.get("log")}
        row["finished"] = bool(course and row["gates"] >= course)
        rows.append(row)
        end = "FINISHED THE RACE" if row["finished"] else row["reason"]
        print(f"  {row['attempt']:2}: {row['gates']:2} gates  {row['seconds'] or 0:6.0f} s  {end}", flush=True)
        name.write_text(json.dumps({"label": label, "argv": job.get("argv"), "attempts": rows}, indent=2),
                        encoding="utf-8")
    g = sorted(r["gates"] for r in rows)
    done = sum(r["finished"] for r in rows)
    print(f"gates: best {g[-1]}, median {g[len(g) // 2]}, worst {g[0]}; finished {done} of {len(rows)}"
          f"  ({name.name})", flush=True)


if __name__ == "__main__":
    main()
