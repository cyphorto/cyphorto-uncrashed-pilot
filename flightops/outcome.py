"""Turn one runner result + its flight log into an attempt record.

Everything here is read from what the existing pilot already writes:
  results/<job>.json      runner result: status, reason, summary (pilot/gate_run.py)
  logs/<..>_gate_live/log.csv   one row per control tick (pilot/hover_test.py COLS)

The pilot's gate count is its own visual pass counter (pilot/guidance.py), not the game's.
It is labelled "self-reported" everywhere; confirmed numbers come from annotations.
"""
import csv
import statistics

DAMAGE_ON = 0.03  # pilot/hover_test.py treats damage_icon() > 0.03 as the icon showing
# A real hit leaves the icon on to the end of the attempt. While the drone passes through a
# gate, the gate's white frame sweeps the icon corner and reads as the icon for 0.0-0.2 s;
# before 2026-10-26 those blips were counted as hits (e.g. 20261026_154118_5905_01 at 97 s).
DAMAGE_HOLD_S = 1.0

# (substring of the reason, category). First match wins. Reasons are the exact strings the
# baseline code raises (pilot/guidance.py, pilot/hover_test.py, pilot/gate_run.py, runner.py).
REASONS = (
    ("OSD mode no longer ANGLE", "crash_mode_change"),
    ("stuck: no speed and no height change", "crash_stuck"),
    ("no gate passed for", "progress_timeout"),
    ("gate approach time limit reached", "duration_timeout"),
    ("no next gate after crossing", "no_next_gate"),
    ("next gate lost", "gate_lost"),
    ("clipped gate without an aligned approach", "recover_timeout"),
    ("altitude did not settle", "settle_failed"),
    ("ALT unreadable in the air", "alt_lost"),
    ("altitude estimate unavailable", "alt_lost"),
    ("stale or non-increasing camera timestamp", "capture_stale"),
    ("no fresh OSD reading", "safety_stale_osd"),
    ("above ceiling", "safety_ceiling"),
    ("throttle saturated", "safety_saturation"),
    ("kill key", "operator_kill"),
    ("Ctrl+C", "operator_kill"),
    ("drone not on the ground after restart", "reset_failed"),
    ("OSD mode is not ANGLE after restart", "reset_failed"),
    ("no liftoff", "liftoff_failed"),
    ("no ALT reading on the ground", "reset_failed"),
)
TIMEOUTS = {"progress_timeout", "duration_timeout"}
CRASHES = {"crash_mode_change", "crash_stuck"}


def categorize(status, reason):
    if status == "complete":
        return "target_reached"
    for needle, cat in REASONS:
        if needle in (reason or ""):
            return cat
    return "error" if status == "error" else f"other_{status}"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_log(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def first_damage_t(t, rows):
    """Time the damage icon came on and then stayed on for DAMAGE_HOLD_S (or until the log ends)."""
    on = None
    for ti, r in zip(t, rows):
        if (_f(r.get("damage")) or 0) > DAMAGE_ON:
            on = ti if on is None else on
            if ti - on >= DAMAGE_HOLD_S:
                return on
        else:
            on = None
    return on


def log_metrics(rows):
    """Timing, pass times and damage from log.csv rows (strings, as written)."""
    if not rows:
        return {"log_rows": 0}
    t = [_f(r["t"]) for r in rows]
    t0 = t[0]
    lift = next((ti for ti, r in zip(t, rows) if r["phase"] == "liftoff"), None)
    passes, last = [], 0
    for ti, r in zip(t, rows):
        n = int(_f(r.get("gate_pass_candidates")) or 0)
        if n > last:
            passes.append(round(ti - (lift if lift is not None else t0), 2))
            last = n
    dmg_t = first_damage_t(t, rows)
    dts = sorted(_f(r["dt"]) for r in rows if r["phase"] == "gate" and _f(r["dt"]) is not None)
    q = (lambda p: round(dts[min(len(dts) - 1, int(p * len(dts)))], 4)) if dts else (lambda p: None)
    gate_rows = [r for r in rows if r["phase"] == "gate"]
    speeds = [_f(r["speed_ms"]) for r in gate_rows if _f(r.get("speed_ms")) is not None]
    return {
        "log_rows": len(rows),
        "log_seconds": round(t[-1] - t0, 2),
        "liftoff_at_s": None if lift is None else round(lift - t0, 2),
        "pass_times_s": passes,  # seconds after liftoff began, one per self-reported pass
        "damage_icon": dmg_t is not None,
        # The icon stays once shown (checked on 20261025_130028: on from 516.6 s to the end),
        # so only the first hit is visible in the log; later hits can't be counted from it.
        "first_damage_s": None if dmg_t is None else round(dmg_t - (lift if lift is not None else t0), 2),
        "loop_dt_median_s": q(0.5), "loop_dt_p95_s": q(0.95),
        "mean_speed_ms": round(statistics.fmean(speeds), 2) if speeds else None,
    }


def build_record(result, rows, target_gates):
    """Attempt record from the runner result dict and its log rows (may be [])."""
    status = result.get("status")
    reason = result.get("reason", "")
    summ = result.get("summary") or {}
    gates = summ.get("gates", result.get("candidate_passes", 0)) or 0
    cat = categorize(status, reason)
    m = log_metrics(rows)
    reached = bool(target_gates) and gates >= target_gates
    pt = m.get("pass_times_s") or []
    return {
        "status": status, "reason": reason, "category": cat,
        "gates_selfreported": gates,
        "target_gates": target_gates,
        "target_reached_selfreported": reached,
        # time from liftoff start to the target-th pass; only for attempts that got there
        "segment_time_s": pt[target_gates - 1] if reached and len(pt) >= target_gates else None,
        "crash_ended": cat in CRASHES,
        "timeout": cat in TIMEOUTS,
        "flight_seconds": summ.get("seconds"),
        "alt_unreadable_pct": summ.get("alt_unreadable_pct"),
        "gate_seen_pct": summ.get("gate_seen_pct"),
        "hover_measured": summ.get("hover_measured"),
        # pilot/hover_test.py logs the tick time but not the frame's capture time, so
        # frame-to-command latency can't be computed from baseline logs.
        "obs_to_control_latency_s": "unavailable: baseline log.csv has no capture timestamp",
        **m,
    }
