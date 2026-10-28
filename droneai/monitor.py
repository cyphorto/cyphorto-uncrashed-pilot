"""Near-real-time flight monitor. Tails the live pilot log at ~1 Hz, detects
attempt boundaries (new flight directory, or a manual T restart seen as a
telemetry discontinuity), and writes a diagnostic report within seconds.

No screenshots in the loop and no keyboard hooks: a rolling telemetry buffer
holds the last visible gate state, since T resets the sim faster than a
pre-reset screenshot. Never touches flight control or the original pilot.
"""
import argparse
import csv
import json
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT))

DAMAGE_ON = 0.03  # damage_icon share while the hit icon shows (~0.07 vs ~0)
BUFFER_S = 40.0  # rolling telemetry kept for instant diagnosis
RESET_ALT = 0.4  # |ALT| under this with no speed reads as "back on the pad"
RESET_SPEED = 0.5  # speed under this reads as "standing still"
RESET_HOLD_S = 2.0  # collapse must persist this long to count as a reset
AIRBORNE_ALT = 1.5  # |ALT| over this (or any pass) proves the segment flew
TAKEOFF_EXCLUSION_S = 5.0  # ignore collapses this soon after a segment starts:
# every flight begins with ~2 s on the pad, which looks exactly like a reset.
# A manual T inside the first 5 s is therefore reported as part of takeoff.


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class LogTail:
    """Incremental reader for one growing log.csv. Parses complete lines only."""

    def __init__(self, path):
        self.path = Path(path)
        self.pos = 0
        self.fields = None

    def read_new(self):
        rows = []
        with self.path.open(encoding="utf-8", newline="") as f:
            f.seek(self.pos)
            chunk = f.read()
            if not chunk or "\n" not in chunk:
                return rows  # nothing new, or a torn line: wait for completion
            complete, _, _ = chunk.rpartition("\n")
            self.pos += len(complete) + 1
            if complete.strip():
                rows = self._parse(complete)
        return rows

    def _parse(self, text):
        lines = text.splitlines()
        if self.fields is None:
            reader = csv.DictReader(lines)
            rows = [r for r in reader if r.get("t")]
            self.fields = reader.fieldnames
            return rows
        reader = csv.DictReader(lines, fieldnames=self.fields)
        return [r for r in reader if r.get("t")]


def damage_onsets(rows):
    onsets = []
    was = False
    for r in rows:
        is_on = (_f(r.get("damage")) or 0.0) > DAMAGE_ON
        if is_on and not was:
            onsets.append(_f(r.get("t")))
        was = is_on
    return [t for t in onsets if t is not None]


def state_episodes(rows, states):
    """Entries into any of `states` (e.g. recoveries)."""
    count, inside = 0, False
    for r in rows:
        if (r.get("guidance_state") or "") in states:
            if not inside:
                count += 1
            inside = True
        else:
            inside = False
    return count


def detect_reset(rows):
    """Index where a manual T restart starts, or None.

    Signature: the segment demonstrably flew (a pass, or |ALT| over
    AIRBORNE_ALT), then ALT and speed collapse to pad values and stay there
    RESET_HOLD_S. Conservative: level-phase rows at a normal flight end carry
    empty guidance_state and passes 0, never this collapse while in-flight.
    """
    if len(rows) < 10:
        return None
    flew = any((_i(r.get("gate_pass_candidates")) or 0) > 0 for r in rows)
    flew = flew or any(abs(_f(r.get("raw_h")) or 0.0) > AIRBORNE_ALT for r in rows)
    if not flew:
        return None
    t_first = _f(rows[0].get("t"))
    for i in range(len(rows)):
        r = rows[i]
        if (r.get("phase") or "") == "level" or not (r.get("guidance_state") or ""):
            continue
        t0 = _f(r.get("t"))
        if t0 is None:
            continue
        if t_first is not None and t0 - t_first < TAKEOFF_EXCLUSION_S:
            continue
        ok, tend = True, t0
        for j in range(i, len(rows)):
            s = rows[j]
            tj = _f(s.get("t"))
            if tj is None:
                ok = False
                break
            if abs(_f(s.get("raw_h")) or 0.0) > RESET_ALT:
                ok = False
                break
            sp = _f(s.get("speed_ms"))
            if sp is not None and sp > RESET_SPEED:
                ok = False
                break
            tend = tj
            if tend - t0 >= RESET_HOLD_S:
                break
        if ok and tend - t0 >= RESET_HOLD_S:
            return i
    return None


def _collapse_end(rows, start):
    """First index at/after start where the pad collapse no longer holds."""
    k = start
    while k < len(rows):
        r = rows[k]
        if abs(_f(r.get("raw_h")) or 0.0) > RESET_ALT:
            break
        sp = _f(r.get("speed_ms"))
        if sp is not None and sp > RESET_SPEED:
            break
        k += 1
    return k


def split_all(rows):
    """Split a full history on every T reset. Returns [seg0, seg1, ...]."""
    rows = list(rows)
    cuts, start = [], 0
    while start < len(rows):
        at = detect_reset(rows[start:])
        if at is None:
            break
        cut = start + at
        cuts.append(cut)
        # Resume past the collapse itself: the remainder starts on the pad,
        # which would otherwise match again at index 0 forever.
        start = max(_collapse_end(rows, cut), cut + 1)
    parts, prev = [], 0
    for cut in cuts:
        parts.append(rows[prev:cut])
        prev = cut
    parts.append(rows[prev:])
    return [p for p in parts if p]


def diagnose(rows, label):
    """Evidence-first diagnosis of one attempt segment."""
    ts = [_f(r.get("t")) for r in rows]
    ts = [t for t in ts if t is not None]
    # Pass counts only exist while guidance runs; level-phase rows carry a
    # stale 0 that must not fake a last-pass rise.
    inflight = [r for r in rows if (r.get("guidance_state") or "")
                not in ("", "aborted")]
    passes = [(_f(r.get("t")), _i(r.get("gate_pass_candidates"))) for r in inflight]
    passes = [(t, p) for t, p in passes if t is not None and p is not None]
    # Segment-relative: the pilot's counter never resets, so a post-T segment
    # reports only the gates it added.
    gates = max([p for _, p in passes], default=0) - (passes[0][1] if passes else 0)
    rises = [t for (t, p), (_, q) in zip(passes, passes[1:]) if q > p]
    last_pass_t = max(rises) if rises else None
    end_t = ts[-1] if ts else None
    start_t = ts[0] if ts else None
    tail = rows[-200:] if len(rows) > 200 else rows
    after = [r for r in rows if last_pass_t is None or (_f(r.get("t")) or 0) >= last_pass_t]
    vis = [r for r in after if (r.get("gate_visible") or "0") == "1"]
    last_vis = vis[-1] if vis else None
    recent = [r for r in rows if end_t is not None and (_f(r.get("t")) or 0) >= end_t - 2.0]
    speeds = [_f(r.get("speed_ms")) for r in recent]
    speeds = [s for s in speeds if s is not None]
    end_speed = sum(speeds) / len(speeds) if speeds else None
    end_visible = any((r.get("gate_visible") or "0") == "1" for r in recent)
    states = [r.get("guidance_state") or "" for r in after if r.get("guidance_state")]
    seq = []
    for s in states:
        if not seq or seq[-1] != s:
            seq.append(s)
    onsets = damage_onsets(rows)
    near_end = [t for t in onsets if end_t is not None and end_t - t <= 5.0]
    recoveries = state_episodes(rows, {"search", "recover"})
    # Heuristic classification from observed evidence only. Terminal states
    # ('aborted', level-phase blanks) mark the stop itself; the failure mode
    # is read from the last in-flight state before them.
    live = [s for s in seq if s != "aborted"]
    last_state = live[-1] if live else ""
    if last_state == "crossing" and not end_visible and (end_speed or 0) > 2:
        failure = "no_next_gate_after_crossing"
    elif near_end and (end_speed or 99) < 1.0:
        failure = "hit_then_stopped"
    elif not end_visible and (end_speed or 0) > 2:
        failure = "gate_lost_moving"
    elif not end_visible:
        failure = "gate_lost"
    elif end_visible:
        failure = "stopped_with_gate_visible"
    else:
        failure = "undetermined"
    return {
        "attempt": label,
        "rows": len(rows),
        "elapsed_s": round(end_t - start_t, 1) if start_t is not None and end_t is not None else None,
        "gates": gates,
        "last_pass_t": round(last_pass_t - start_t, 1) if last_pass_t is not None and start_t is not None else None,
        "failure_window_s": round(end_t - (last_pass_t or start_t or end_t), 1) if end_t is not None else None,
        "next_gate_visible_after_last_pass": f"{len(vis)}/{len(after)} rows",
        "last_seen_gate": ({k: last_vis.get(k) for k in ("gate_x", "gate_y", "gate_size")}
                           if last_vis else None),
        "last_seen_ago_s": (round(end_t - (_f(last_vis.get("t")) or end_t), 1)
                            if last_vis and end_t is not None else None),
        "trailing_states": seq[-8:],
        "recovery_attempted": recoveries > 0,
        "recovery_episodes": recoveries,
        "end_speed_ms": round(end_speed, 2) if end_speed is not None else None,
        "damage_onsets": len(onsets),
        "first_damage_s": (round(onsets[0] - start_t, 1)
                           if onsets and start_t is not None else None),
        "failure_class_heuristic": failure,
    }


def render_md(diag, log_name):
    d = diag
    lines = [
        f"# Attempt {d['attempt']} — {d['failure_class_heuristic']}",
        "",
        f"Log: {log_name}. Rows: {d['rows']}. Elapsed: {d['elapsed_s']} s.",
        "",
        "## Confirmed observations",
        "",
        f"- Gates completed: {d['gates']}.",
        f"- Last pass at segment t={d['last_pass_t']} s; "
        f"failure window after it: {d['failure_window_s']} s.",
        f"- Next gate visible after last pass: {d['next_gate_visible_after_last_pass']}.",
        f"- Last seen gate: {d['last_seen_gate']} "
        f"({d['last_seen_ago_s']} s before segment end).",
        f"- Trailing guidance states: {d['trailing_states']}.",
        f"- End speed: {d['end_speed_ms']} m/s.",
        f"- Damage-icon onsets: {d['damage_onsets']} "
        f"(first at {d['first_damage_s']} s).",
        f"- Recovery attempted (search/recover states): {d['recovery_attempted']} "
        f"({d['recovery_episodes']} episodes).",
        "",
        "## Classification (heuristic, from the evidence above)",
        "",
        f"- {d['failure_class_heuristic']}.",
        "- no_next_gate_after_crossing means: last state was crossing, the gate "
        "was gone at the end, and the drone was still moving fast — it flew "
        "through and found nothing ahead within the crossing timeout.",
        "- Treat any other cause as undetermined unless the rows above show it.",
        "",
    ]
    return "\n".join(lines)


SUMMARY_FIELDS = ("attempt", "log", "elapsed_s", "gates", "damage_onsets",
                  "recovery_episodes", "failure_class", "ended")


class Monitor:
    def __init__(self, version="p2_fast_baseline", out_dir=None, poll_s=1.0,
                 max_iterations=None, logs_root=None, quiet=False, idle_s=15.0):
        self.logs = Path(logs_root or V2_ROOT / "versions" / version / "logs")
        self.out = Path(out_dir or V2_ROOT / "eval" / "roadtrip")
        self.out.mkdir(parents=True, exist_ok=True)
        self.summary = self.out / "summary.csv"
        if not self.summary.exists():
            self.summary.write_text(",".join(SUMMARY_FIELDS) + "\n", encoding="utf-8")
        self.poll_s = poll_s
        self.max_iterations = max_iterations
        self.quiet = quiet
        self.idle_s = idle_s
        self.buffer = deque()
        self.open_rows = []
        self.tail = None
        self.current = None
        self.segment = 0
        self.sealed = False
        self.last_new_wall = time.time()
        self.n = 0

    def newest_dir(self):
        dirs = sorted(self.logs.glob("*_gate_live"), key=lambda p: p.stat().st_mtime)
        return dirs[-1] if dirs else None

    def _label(self, logdir, segment):
        return f"{logdir.name}#{segment}" if segment else logdir.name

    def _summary_has(self, label):
        try:
            with self.summary.open(encoding="utf-8") as f:
                return any(r.get("attempt") == label for r in csv.DictReader(f))
        except OSError:
            return False

    def start_segment(self, logdir):
        if logdir != self.current:
            self.current, self.segment = logdir, 0
        else:
            self.segment += 1
        self.tail = LogTail(logdir / "log.csv")
        self.buffer.clear()
        self.open_rows = []
        self.sealed = False
        self.last_new_wall = time.time()
        # Late attach: split the rows already on disk so history before the
        # rolling window is still reported, then keep the tail open.
        initial = self.tail.read_new()
        if initial:
            parts = split_all(initial)
            for part in parts[:-1]:
                lbl = self._label(logdir, self.segment)
                self.buffer = deque(part)
                self.open_rows = list(part)
                self.finalize(lbl, "t_reset_detected")
                self.segment += 1
            self.open_rows = list(parts[-1])
            self.buffer = deque(parts[-1])
            self.prune()
        label = self._label(logdir, self.segment)
        if not self.quiet:
            print(f"monitoring {label}", flush=True)
        return label

    def finalize(self, label, ended):
        rows = self.open_rows or list(self.buffer)
        if not rows:
            return None
        diag = diagnose(rows, label)
        (self.out / f"{label}.json").write_text(json.dumps(diag, indent=1), encoding="utf-8")
        (self.out / f"{label}.md").write_text(render_md(diag, self.current.name
                                                        if self.current else "?"),
                                              encoding="utf-8")
        if not self._summary_has(label):
            with self.summary.open("a", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
                w.writerow({"attempt": label, "log": self.current.name if self.current else "?",
                            "elapsed_s": diag["elapsed_s"], "gates": diag["gates"],
                            "damage_onsets": diag["damage_onsets"],
                            "recovery_episodes": diag["recovery_episodes"],
                            "failure_class": diag["failure_class_heuristic"], "ended": ended})
        if not self.quiet:
            print(f"saved {label}: {diag['gates']} gates, {diag['elapsed_s']} s, "
                  f"{diag['failure_class_heuristic']}", flush=True)
        return diag

    def prune(self):
        while len(self.buffer) > 1:
            t0 = _f(self.buffer[0].get("t"))
            t1 = _f(self.buffer[-1].get("t"))
            if t0 is None or t1 is None or t1 - t0 <= BUFFER_S:
                break
            self.buffer.popleft()

    def _flight_ended(self):
        """True when in-flight rows stopped at least a second ago and every
        row since is terminal (level phase, blank or aborted state): the
        pilot stopped and the log is only draining. The normal level hold
        lasts 1.5 s, so 1.0 s of terminal tail cannot be a mid-flight gap."""
        if len(self.buffer) < 3:
            return False
        tend = _f(self.buffer[-1].get("t"))
        if tend is None:
            return False
        last_fly = None
        for r in self.buffer:
            if (r.get("guidance_state") or "") not in ("", "aborted"):
                last_fly = _f(r.get("t"))
        if last_fly is None or tend - last_fly < 1.0:
            return False
        for r in self.buffer:
            t = _f(r.get("t"))
            if t is not None and t > last_fly:
                if not ((r.get("phase") or "") == "level"
                        or (r.get("guidance_state") or "") in ("", "aborted")):
                    return False
        return True

    def tick(self):
        newest = self.newest_dir()
        if newest is None:
            return True
        label = (f"{self.current.name}#{self.segment}" if self.segment and self.current
                 else (self.current.name if self.current else None))
        if newest != self.current:
            if self.current is not None and self.buffer and not self.sealed:
                self.finalize(label, "new_flight_dir")
            label = self.start_segment(newest)
        new_rows = self.tail.read_new()
        if new_rows:
            for r in new_rows:
                self.buffer.append(r)
                self.open_rows.append(r)
            self.prune()
            self.last_new_wall = time.time()
            if self.sealed and any((r.get("guidance_state") or "")
                                   not in ("", "aborted") for r in new_rows):
                self.segment += 1  # unexpected in-flight rows after an end
                self.open_rows = list(new_rows)
                self.sealed = False
        if self.sealed or not self.buffer:
            return True
        if self._flight_ended():
            self.finalize(label, "flight_ended")
            self.sealed = True
            return True
        if time.time() - self.last_new_wall > self.idle_s:
            self.finalize(label, "log_idle")
            self.sealed = True
            return True
        if self.buffer:
            last = self.buffer[-1]
            if not self.quiet:
                print(f"  t={_f(last.get('t'))} passes={last.get('gate_pass_candidates')} "
                      f"state={last.get('guidance_state')} speed={last.get('speed_ms')} "
                      f"dmg={last.get('damage')}", flush=True)
            at = detect_reset(list(self.buffer))
            if at is not None:
                buf = list(self.buffer)
                cut_t = _f(buf[at].get("t"))
                pre = [r for r in self.open_rows
                       if cut_t is None or (_f(r.get("t")) or 0) < cut_t]
                post = [r for r in self.open_rows
                        if cut_t is None or (_f(r.get("t")) or 0) >= cut_t]
                if not pre or not post:
                    return True  # degenerate cut at the open edge: already split
                self.buffer, self.open_rows = deque(pre), pre
                self.finalize(label, "t_reset_detected")
                self.segment += 1
                self.sealed = False
                label = self._label(newest, self.segment)
                self.open_rows = post
                self.buffer = deque(post)
                self.prune()
                if not self.quiet:
                    print(f"monitoring {label} (after T reset)", flush=True)
        return True

    def run(self):
        try:
            while self.max_iterations is None or self.n < self.max_iterations:
                self.tick()
                self.n += 1
                time.sleep(self.poll_s)
        except KeyboardInterrupt:
            pass
        if self.current is not None and self.buffer and not self.sealed:
            label = (f"{self.current.name}#{self.segment}" if self.segment
                     else self.current.name)
            self.finalize(label, "monitor_stopped")
        return self.n


def main(argv=None):
    p = argparse.ArgumentParser(description="Tail the live flight log, split attempts "
                                "on new flights and manual T resets, and diagnose each.")
    p.add_argument("--version", default="p2_fast_baseline")
    p.add_argument("--poll", type=float, default=1.0)
    p.add_argument("--out", default=None)
    p.add_argument("--max-iterations", type=int, default=None)
    p.add_argument("--idle-s", type=float, default=15.0)
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)
    Monitor(version=a.version, out_dir=a.out, poll_s=a.poll,
            max_iterations=a.max_iterations, quiet=a.quiet,
            idle_s=a.idle_s).run()


if __name__ == "__main__":
    main()
