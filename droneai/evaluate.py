"""Offline performance evaluation. Reads attempt records and human labels;
needs no game, no runner and no network.

Finish truth is annotations.csv (finished_confirmed + race time). Self-counted
gates are progress, never finishes.
"""
import csv
import json
import statistics
import sys


def summarize_attempts(attempts_path, annotations_path=None):
    gates, versions, categories, crashes = [], {}, {}, 0
    with open(attempts_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            g = r.get("gates_selfreported") or 0
            gates.append(g)
            v = versions.setdefault(r.get("version", "?"), [])
            v.append(g)
            c = r.get("category", "?")
            categories[c] = categories.get(c, 0) + 1
            if r.get("crash_ended"):
                crashes += 1
    out = {
        "attempts": len(gates),
        "median_gates": statistics.median(gates) if gates else 0,
        "best_gates": max(gates) if gates else 0,
        "crash_ended": crashes,
        "categories": categories,
        "by_version": {v: {"attempts": len(g),
                            "median_gates": statistics.median(g)}
                       for v, g in versions.items()},
    }
    if annotations_path is not None:
        finished, hits, labelled = 0, 0, 0
        with open(annotations_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("finished_confirmed") or "").strip().lower() == "yes":
                    finished += 1
                try:
                    hits += int(row.get("hits_observed") or 0)
                except ValueError:
                    pass
                labelled += 1
        out["annotations"] = {"rows": labelled, "finished_confirmed": finished,
                              "hits_observed": hits}
    return out


def main(argv):
    from . import training as _t
    split = argv[1] if len(argv) > 1 else "train"
    out = summarize_attempts(_t.attempts_path(split), _t.ANNOTATIONS)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv)
