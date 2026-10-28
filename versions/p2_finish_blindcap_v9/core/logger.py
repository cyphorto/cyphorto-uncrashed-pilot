"""Every run writes logs/<time>_<mode>.csv plus a .json with the exact config and result."""
import csv
import json
import time

from . import ROOT

COLUMNS = ["t", "phase", "t_grab", "raw_h", "read_status", "h_filt", "v_filt", "h_ref", "v_ref",
           "a_ref", "ref_moving", "u", "u_raw", "u_ff", "u_aff", "u_p", "u_d", "u_i", "sat",
           "abort", "true_h", "true_v"]


class RunLogger:
    def __init__(self, mode, cfg, args=None, folder=None, tag=""):
        folder = folder or (ROOT / "logs")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = f"{stamp}_{mode}{('_' + tag) if tag else ''}"
        i = 1
        while (folder / f"{name}.csv").exists():
            name = f"{stamp}_{mode}{('_' + tag) if tag else ''}_{i}"
            i += 1
        self.csv_path = folder / f"{name}.csv"
        self.json_path = folder / f"{name}.json"
        self.f = open(self.csv_path, "w", newline="", encoding="utf-8")
        self.w = csv.DictWriter(self.f, fieldnames=COLUMNS, extrasaction="ignore")
        self.w.writeheader()
        self.meta = {"mode": mode, "started": stamp, "args": args or {}, "config": cfg}

    def row(self, **kw):
        out = {}
        for k in COLUMNS:
            v = kw.get(k, "")
            if isinstance(v, float):
                v = f"{v:.5f}"
            elif v is None:
                v = ""
            out[k] = v
        self.w.writerow(out)

    def close(self, result=None):
        self.f.close()
        self.meta["result"] = result or {}
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2)
