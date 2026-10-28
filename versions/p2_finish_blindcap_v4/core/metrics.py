"""Pass/fail scoring for altitude step tests. Used by run_alt_test.py and analyze.py.

The ±0.2 m tolerance is checked on the DISPLAYED value (0.1 m steps), the same thing you can see
in the game, so true error can reach ~0.25 m. In the sim the true numbers are reported as well.
"""
import csv
import math

GOOD = ("ok", "skip", "reset")


def _f(x):
    if x in ("", None):
        return None
    try:
        return float(x)
    except ValueError:
        return x


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append({k: (v if k in ("phase", "read_status", "abort") else _f(v)) for k, v in r.items()})
    return rows


def step_metrics(rows, test_cfg, h1, h2, ground_m):
    tol = float(test_cfg["tolerance_m"])
    step = [r for r in rows if r["phase"] == "step"]
    out = {"h1": h1, "h2": h2}
    abort = next((r["abort"] for r in rows if r.get("abort")), "")
    out["abort"] = abort
    airborne_rows = [r for r in rows if r["phase"] in ("settle", "step")]
    out["ground_contact"] = any(
        r["raw_h"] is not None and r["read_status"] in GOOD and r["raw_h"] <= ground_m for r in airborne_rows)
    if not step:
        out["pass"] = False
        out["why"] = ["step phase never ran" + (f" (abort: {abort})" if abort else "")]
        return out
    t0 = step[0]["t"]
    s = 1.0 if h2 >= h1 else -1.0
    disp = [(r["t"], r["raw_h"]) for r in step if r["raw_h"] is not None and r["read_status"] in GOOD]
    over = max([s * (z - h2) for _, z in disp] + [0.0])
    t_end = step[-1]["t"]
    win = float(test_cfg["final_window_s"])
    final = [z for t, z in disp if t >= t_end - win]
    final_err = (sum(final) / len(final) - h2) if final else math.nan
    outside = [t for t, z in disp if abs(z - h2) > tol + 1e-9]
    settle = (max(outside) - t0) if outside else 0.0
    sats = [int(r["sat"] or 0) for r in step]
    sat_frac = sum(sats) / len(sats)
    episodes = sum(1 for a, b in zip([0] + sats, sats) if b and not a)
    out.update(overshoot_m=round(over, 3), final_err_m=round(final_err, 3), settle_s=round(settle, 2),
               sat_frac=round(sat_frac, 4), sat_episodes=episodes)
    true = [(r["t"], r["true_h"]) for r in step if isinstance(r.get("true_h"), float)]
    if true:
        out["true_overshoot_m"] = round(max([s * (h - h2) for _, h in true] + [0.0]), 3)
        tf = [h for t, h in true if t >= t_end - win]
        out["true_final_err_m"] = round(sum(tf) / len(tf) - h2, 3)
    why = []
    if abort:
        why.append(f"aborted: {abort}")
    if out["ground_contact"]:
        why.append("touched the ground after takeoff")
    if over > float(test_cfg["max_overshoot_m"]) + 1e-9:
        why.append(f"overshoot {over:.2f} m > {test_cfg['max_overshoot_m']} m")
    if not (abs(final_err) <= tol + 1e-9):
        why.append(f"final error {final_err:+.2f} m outside ±{tol} m")
    if sat_frac > float(test_cfg["max_sat_frac"]):
        why.append(f"throttle saturated {sat_frac:.0%} of the step")
    if episodes > int(test_cfg["max_sat_episodes"]):
        why.append(f"{episodes} saturation episodes")
    out["pass"] = not why
    out["why"] = why
    return out


def format_step(m):
    lines = [f"Step {m['h1']} -> {m['h2']} m: {'PASS' if m['pass'] else 'FAIL'}"]
    if "overshoot_m" in m:
        lines.append(f"  overshoot {m['overshoot_m']:.2f} m | final error {m['final_err_m']:+.2f} m | "
                     f"settle {m['settle_s']:.1f} s | saturation {m['sat_frac']:.1%} ({m['sat_episodes']} episodes)")
    if "true_overshoot_m" in m:
        lines.append(f"  (sim truth: overshoot {m['true_overshoot_m']:.2f} m, final error {m['true_final_err_m']:+.2f} m)")
    for w in m.get("why", []):
        lines.append(f"  - {w}")
    return "\n".join(lines)
