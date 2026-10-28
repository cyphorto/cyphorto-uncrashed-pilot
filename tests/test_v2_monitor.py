"""Offline tests for the flight monitor: diagnosis, T-reset splitting,
incremental tailing, and report outputs. No game, no runner, no network."""
import csv
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from droneai import monitor

HEADER = ("t,phase,dt,raw_h,read_status,h_filt,v_filt,h_ref,v_ref,u,u_p,u_d,u_i,sat,"
          "gate_visible,gate_x,gate_y,gate_size,gate_clipped,alt_text,alt_score,abort,"
          "yaw,pitch,roll,guidance_state,gate_pass_candidates,speed_ms,climb,mode_w,"
          "damage,u_tilt").split(",")


def write_log(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in HEADER})


def row(t, **kw):
    r = {"t": t, "phase": "fly", "mode_w": "0.604", "damage": "0.0"}
    r.update(kw)
    return r


def flight_a():
    """3 passes, a mid-flight hit, then crossing with the gate gone and fast
    straight flight: the no_next_gate_after_crossing signature."""
    rows = [
        row(0.0, raw_h="0.0", speed_ms="0.0", guidance_state="approach",
            gate_pass_candidates="0", gate_visible="1", gate_size="0.05"),
        row(1.0, raw_h="2.1", speed_ms="4.1", guidance_state="approach",
            gate_pass_candidates="0", gate_visible="1", gate_size="0.09"),
        row(2.0, raw_h="3.0", speed_ms="5.2", guidance_state="approach",
            gate_pass_candidates="1", gate_visible="1", gate_size="0.06"),
        row(3.0, raw_h="4.2", speed_ms="5.9", guidance_state="search",
            gate_pass_candidates="1", gate_visible="0"),
        row(4.0, raw_h="4.0", speed_ms="5.1", guidance_state="approach",
            gate_pass_candidates="1", gate_visible="1", gate_size="0.08"),
        row(5.0, raw_h="5.5", speed_ms="6.0", guidance_state="approach",
            gate_pass_candidates="2", gate_visible="1", gate_size="0.05"),
        row(6.0, raw_h="6.1", speed_ms="6.2", guidance_state="approach",
            gate_pass_candidates="2", gate_visible="1", gate_size="0.10",
            damage="0.07"),
        row(7.0, raw_h="5.8", speed_ms="6.0", guidance_state="approach",
            gate_pass_candidates="2", gate_visible="1", gate_size="0.12",
            damage="0.07"),
        row(8.0, raw_h="5.0", speed_ms="6.4", guidance_state="approach",
            gate_pass_candidates="3", gate_visible="1", gate_size="0.06",
            damage="0.07"),
        row(9.0, raw_h="4.6", speed_ms="8.6", guidance_state="crossing",
            gate_pass_candidates="3", gate_visible="1", gate_size="0.43",
            damage="0.07"),
        row(10.0, raw_h="4.4", speed_ms="9.4", guidance_state="crossing",
            gate_pass_candidates="3", gate_visible="0", damage="0.07"),
        row(11.0, raw_h="4.2", speed_ms="10.3", guidance_state="crossing",
            gate_pass_candidates="3", gate_visible="0", damage="0.07"),
        row(12.0, raw_h="4.0", speed_ms="11.1", guidance_state="crossing",
            gate_pass_candidates="3", gate_visible="0", damage="0.07"),
    ]
    rows += [{"t": round(12.5 + 0.1 * i, 1), "phase": "level", "guidance_state": "",
              "gate_pass_candidates": "0", "mode_w": "0.604", "damage": "0.07"}
             for i in range(15)]  # 1.5 s level hold, like a real flight end
    return rows


def flight_b():
    """2 passes, then a manual T at t=11: ALT and speed collapse to pad
    values for 4 s while the pilot log keeps its pass count, then takeoff."""
    rows = [row(float(t), raw_h=str(4.0 + t * 0.3), speed_ms="6.0",
                guidance_state="approach", gate_pass_candidates=str(min(t // 5, 2)),
                gate_visible="1", gate_size="0.08")
            for t in range(0, 11)]
    rows += [row(float(t), raw_h="0.0", speed_ms="0.0",
                 guidance_state="approach", gate_pass_candidates="2",
                 gate_visible="1", gate_size="0.05")
             for t in range(11, 15)]
    rows += [row(float(t), raw_h=str((t - 14) * 1.5), speed_ms="3.0",
                 guidance_state="approach", gate_pass_candidates="2",
                 gate_visible="1", gate_size="0.06")
             for t in range(15, 18)]
    return rows


def read_rows(rows):
    return [{k: v for k, v in r.items()} for r in rows]


class TestDiagnose(unittest.TestCase):
    def test_no_next_gate_signature(self):
        d = monitor.diagnose(read_rows(flight_a()), "A")
        self.assertEqual(d["gates"], 3)
        self.assertEqual(d["failure_class_heuristic"], "no_next_gate_after_crossing")
        self.assertEqual(d["damage_onsets"], 1)
        self.assertTrue(d["recovery_attempted"])
        self.assertEqual(d["recovery_episodes"], 1)
        self.assertIsNotNone(d["last_seen_gate"])
        self.assertGreater(d["failure_window_s"], 0)

    def test_gates_are_segment_relative(self):
        rows = read_rows(flight_b())
        post = [r for r in rows if float(r["t"]) >= 11.0]
        d = monitor.diagnose(post, "B1")
        self.assertEqual(d["gates"], 0)  # counter sits at 2 through the pad-sit
        post2 = ([dict(r, gate_pass_candidates="2") for r in post[:3]]
                 + [dict(r, gate_pass_candidates="5") for r in post[3:]])
        self.assertEqual(monitor.diagnose(post2, "B2")["gates"], 3)

    def test_no_false_reset_on_normal_flight(self):
        self.assertIsNone(monitor.detect_reset(read_rows(flight_a())))

    def test_terminal_aborted_keeps_classification(self):
        rows = read_rows(flight_a()) + [
            {"t": "14.5", "phase": "level", "guidance_state": "aborted",
             "gate_pass_candidates": "0", "gate_visible": "0", "speed_ms": "9.0",
             "damage": "0.07", "raw_h": "4.0", "mode_w": "0.604"},
        ]
        d = monitor.diagnose(rows, "A2")
        self.assertEqual(d["failure_class_heuristic"], "no_next_gate_after_crossing")

    def test_detect_manual_t(self):
        at = monitor.detect_reset(read_rows(flight_b()))
        self.assertIsNotNone(at)
        rows = flight_b()
        self.assertEqual(rows[at]["t"], 11.0)

    def test_takeoff_pad_sit_is_not_a_reset(self):
        pad = [row(float(t), raw_h="0.0", speed_ms="0.0",
                   guidance_state="approach", gate_pass_candidates="0",
                   gate_visible="1", gate_size="0.05") for t in range(0, 3)]
        fly = [row(float(t), raw_h="5.0", speed_ms="6.0",
                   guidance_state="approach", gate_pass_candidates="1",
                   gate_visible="1", gate_size="0.08") for t in range(3, 12)]
        self.assertIsNone(monitor.detect_reset(read_rows(pad + fly)))

    def test_split_all_terminates_on_trailing_collapse(self):
        parts = monitor.split_all(read_rows(flight_b()[:14]))
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0][-1]["t"], 10.0)

    def test_split_all_double_t(self):
        seg = [row(float(t), raw_h="5.0", speed_ms="6.0",
                   guidance_state="approach", gate_pass_candidates="1",
                   gate_visible="1", gate_size="0.08") for t in range(0, 8)]
        pad = [row(float(t), raw_h="0.0", speed_ms="0.0",
                   guidance_state="approach", gate_pass_candidates="1",
                   gate_visible="1", gate_size="0.05") for t in (8.0, 9.0, 10.0)]
        seg2 = [row(float(t), raw_h="5.0", speed_ms="6.0",
                    guidance_state="approach", gate_pass_candidates="2",
                    gate_visible="1", gate_size="0.08") for t in range(11, 20)]
        pad2 = [row(float(t), raw_h="0.0", speed_ms="0.0",
                    guidance_state="approach", gate_pass_candidates="2",
                    gate_visible="1", gate_size="0.05") for t in (20.0, 21.0, 22.0)]
        tail = [row(float(t), raw_h="5.0", speed_ms="6.0",
                    guidance_state="approach", gate_pass_candidates="2",
                    gate_visible="1", gate_size="0.08") for t in range(23, 28)]
        parts = monitor.split_all(read_rows(seg + pad + seg2 + pad2 + tail))
        self.assertEqual(len(parts), 3)


class TestLogTail(unittest.TestCase):
    def test_incremental_no_dupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "log.csv"
            write_log(p, flight_a()[:5])
            tail = monitor.LogTail(p)
            first = tail.read_new()
            self.assertEqual(len(first), 5)
            with p.open("a", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=HEADER)
                for r in flight_a()[5:8]:
                    w.writerow({k: r.get(k, "") for k in HEADER})
            second = tail.read_new()
            self.assertEqual([r["t"] for r in second], ["5.0", "6.0", "7.0"])
            self.assertEqual(tail.read_new(), [])


class TestMonitorFlow(unittest.TestCase):
    def test_t_split_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            write_log(logs / "20261027_120000_000000_gate_live" / "log.csv", flight_b())
            out = Path(tmp) / "out"
            m = monitor.Monitor(logs_root=logs, out_dir=out, poll_s=0,
                                max_iterations=3, quiet=True)
            m.run()
            names = sorted(p.name for p in out.iterdir())
            self.assertIn("summary.csv", names)
            base = "20261027_120000_000000_gate_live"
            self.assertIn(base + ".md", names)
            self.assertIn(base + ".json", names)
            self.assertIn(base + "#1.md", names)
            with (out / "summary.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["ended"], "t_reset_detected")
            self.assertEqual(rows[0]["gates"], "2")
            self.assertEqual(rows[1]["ended"], "monitor_stopped")

    def test_new_dir_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            d1 = logs / "20261027_120000_000000_gate_live"
            write_log(d1 / "log.csv", flight_a()[:13])  # still flying, no level tail
            out = Path(tmp) / "out"
            m = monitor.Monitor(logs_root=logs, out_dir=out, poll_s=0, quiet=True)
            m.tick()
            d2 = logs / "20261027_121000_000000_gate_live"
            write_log(d2 / "log.csv", flight_a()[:4])
            now = time.time()
            os.utime(d2 / "log.csv", (now + 5, now + 5))
            m.tick()
            with (out / "summary.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ended"], "new_flight_dir")
            self.assertEqual(rows[0]["gates"], "3")

    def test_flight_end_auto_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            write_log(logs / "20261027_120000_000000_gate_live" / "log.csv", flight_a())
            out = Path(tmp) / "out"
            m = monitor.Monitor(logs_root=logs, out_dir=out, poll_s=0,
                                max_iterations=2, quiet=True)
            m.run()
            with (out / "summary.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ended"], "flight_ended")
            self.assertEqual(rows[0]["gates"], "3")

    def test_late_attach_reports_full_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            base = "20261027_120000_000000_gate_live"
            write_log(logs / base / "log.csv", flight_b())
            out = Path(tmp) / "out"
            m = monitor.Monitor(logs_root=logs, out_dir=out, poll_s=0,
                                max_iterations=1, quiet=True)
            m.run()
            with (out / "summary.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["attempt"], base)
            self.assertEqual(rows[0]["ended"], "t_reset_detected")
            self.assertEqual(rows[0]["elapsed_s"], "10.0")
            self.assertEqual(rows[0]["gates"], "2")
            self.assertEqual(rows[1]["attempt"], base + "#1")

    def test_reattach_writes_no_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            write_log(logs / "20261027_120000_000000_gate_live" / "log.csv", flight_b())
            out = Path(tmp) / "out"
            for _ in range(2):
                m = monitor.Monitor(logs_root=logs, out_dir=out, poll_s=0,
                                    max_iterations=1, quiet=True)
                m.run()
            with (out / "summary.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)

    def test_idle_backstop(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            write_log(logs / "20261027_120000_000000_gate_live" / "log.csv",
                      flight_a()[:13])
            out = Path(tmp) / "out"
            m = monitor.Monitor(logs_root=logs, out_dir=out, poll_s=0, quiet=True)
            m.tick()
            m.last_new_wall -= 60
            m.tick()
            with (out / "summary.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ended"], "log_idle")


if __name__ == "__main__":
    unittest.main()
