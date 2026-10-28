"""Shared paths, hashing and the course/split rules for the V2 flightops tooling.

Nothing here touches the game or the controller. Pure Python + stdlib, so it runs and is
tested on any OS.
"""
import fnmatch
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HK = ROOT / "flightops"
VERSIONS = ROOT / "versions"
RUNS = ROOT / "training_data" / "runs"
PROTOCOL = ROOT / "training_data" / "protocol.json"

# Everything that decides how a pilot flies. A frozen version is a copy of exactly these.
# tools/ is included because the runner imports tools.game (shot) and job.py submits to it.
VERSION_PATTERNS = (
    "config.json",
    "core/*.py",
    "pilot/*.py",
    "tools/*.py",
    "data/alt_templates/*",
    "data/speed_templates/*",
)

SPLITS = ("smoke", "baseline", "train", "valid", "eval", "heldout")
FROZEN_ONLY = {"smoke", "baseline", "eval", "heldout"}  # no --set, no workspace code


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_version_file(rel):
    rel = rel.replace("\\", "/")
    if "__pycache__" in rel or rel.endswith(".pyc"):
        return False
    return any(fnmatch.fnmatchcase(rel, pat) and rel.count("/") == pat.count("/") for pat in VERSION_PATTERNS)


def version_files(root):
    """{relative posix path: sha256} for the files that define a pilot under root."""
    root = Path(root)
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".venv", "logs", "results", "jobs",
                                                        "flightops", "versions", "training_data", "droneai",
                                                        "eval", "tests", "checkpoints", "data_recordings")]
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if is_version_file(rel):
                out[rel] = sha256_file(p)
    return dict(sorted(out.items()))


def tree_hash(files):
    """One hash for a {path: sha256} map (order independent)."""
    return sha256_bytes("\n".join(f"{k}\t{v}" for k, v in sorted(files.items())).encode())


def load_protocol(path=PROTOCOL):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def course(protocol, name):
    try:
        return protocol["courses"][name]
    except KeyError:
        raise SystemExit(f"unknown course {name!r}; defined: {', '.join(protocol['courses'])}")


class GuardError(Exception):
    """A request that would mix training and evaluation, or touch the held-out course."""


def check_split(split, version_name, course_name, protocol, overrides=()):
    """Raise GuardError unless this combination keeps training and evaluation apart.

    - smoke/baseline/eval/heldout fly a frozen version exactly as frozen: no workspace
      code, no --set overrides (so nothing learned on the fly can leak into a score).
    - Only the heldout split may fly a held-out course, and the heldout split only flies
      held-out courses.
    """
    if split not in SPLITS:
        raise GuardError(f"unknown split {split!r}; one of {', '.join(SPLITS)}")
    c = course(protocol, course_name)
    held = c.get("role") == "heldout"
    if split in FROZEN_ONLY:
        if version_name == "workspace":
            raise GuardError(f"split {split!r} needs a frozen version (flightops/freeze.py), not the workspace")
        if overrides:
            raise GuardError(f"split {split!r} flies a frozen version as is: --set is not allowed")
    if held and split != "heldout":
        raise GuardError(f"course {course_name!r} is held out: only the 'heldout' split may fly it")
    if split == "heldout" and not held:
        raise GuardError(f"the 'heldout' split only flies held-out courses, not {course_name!r}")
    if split == "heldout" and not protocol.get("heldout_unlocked", False):
        raise GuardError("held-out evaluation is locked until the final versions are frozen: "
                         "set \"heldout_unlocked\": true in training_data/protocol.json when you're ready")


def heldout_courses(protocol):
    return {k for k, v in protocol["courses"].items() if v.get("role") == "heldout"}


def is_heldout_path(path):
    """True for anything under the held-out results. Analysis code refuses these paths."""
    parts = Path(path).resolve().parts
    return "heldout" in parts and "runs" in parts
