"""Check the ALT reader against every live crop we have. Run after any reader or template change.

    python tools/check_alt.py

Two sources, both under logs/<run>/:
  alt_fail/labels.txt   hand labels for crops the reader couldn't read ("<crop name> <metres>"
                        per line; write them by looking at the crops)
  alt/<time>_<value>.png  periodic crops, named with the value accepted during the flight
A wrong number is worse than none: the exit code is 1 if any crop reads as a different value.
"""
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ROOT  # noqa: E402
from core.alt_reader import AltReader  # noqa: E402


def main():
    r = AltReader(ROOT / "data" / "alt_templates")
    tally = {"labelled": [0, 0, 0], "periodic": [0, 0, 0]}  # right, unreadable, wrong
    wrong = []

    def check(kind, path, value):
        h, text, _ = r.read_crop(cv2.imread(str(path)))
        if h is None:
            tally[kind][1] += 1
        elif abs(h - value) < 1e-6:
            tally[kind][0] += 1
        else:
            tally[kind][2] += 1
            wrong.append(f"{path} label {value} read {text}")

    for labels in sorted(ROOT.glob("logs/*/alt_fail/labels.txt")):
        for line in labels.read_text().split("\n"):
            if line.strip():
                name, value = line.split()
                check("labelled", labels.parent / f"{name}.png", float(value))
    for p in sorted(ROOT.glob("logs/*/alt/*.png")):
        if "sim" in p.parent.parent.name:
            continue
        value = p.stem.split("_", 1)[1]
        if value != "none":
            check("periodic", p, float(value))
    for kind, (ok, none, bad) in tally.items():
        n = max(1, ok + none + bad)
        print(f"{kind:9} {ok + none + bad:5} crops: right {ok} ({100 * ok / n:.1f}%), unreadable {none}, WRONG {bad}")
    for w in wrong:
        print("WRONG", w)
    raise SystemExit(1 if wrong else 0)


if __name__ == "__main__":
    main()
