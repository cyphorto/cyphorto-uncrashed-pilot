"""Machine learning and training boundary. Read-only: it reports resumable
state, never writes it. Training progress lives in V2's training_data/
(copied from the original project on 2026-10-27; new attempts append there
when flown from V2).

Learned progress is attempt records plus small JSON state, not binary model
files. The local ridge predictor is still collecting and has no fitted
weights yet; see checkpoints/manifest.json.
"""
import json

from . import _roots as _r

DATA = _r.V2_ROOT / "training_data"
STATE = DATA / "runs/tune/full_course_learning.json"
FEEDBACK = DATA / "meta/learning/feedback.json"
ANNOTATIONS = DATA / "runs/annotations.csv"
SPLITS = ("train", "valid", "baseline", "smoke")

STATE_REQUIRED = ("version", "space_version", "prompt", "baseline_required",
                  "candidate_attempts")
FEEDBACK_REQUIRED = ("training_attempts", "baseline_collected", "model",
                     "baseline_required")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def attempts_path(split):
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {SPLITS}")
    return DATA / f"runs/{split}/attempts.jsonl"


def count_attempts(split):
    path = attempts_path(split)
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def resume_state():
    """Load coordinator state plus feedback. Raises if anything is unreadable,
    so a broken training store fails loudly instead of silently restarting."""
    state = _read_json(STATE)
    feedback = _read_json(FEEDBACK)
    missing = [k for k in STATE_REQUIRED if k not in state]
    if missing:
        raise ValueError(f"learning state missing keys {missing}")
    missing = [k for k in FEEDBACK_REQUIRED if k not in feedback]
    if missing:
        raise ValueError(f"learning feedback missing keys {missing}")
    model = feedback["model"]
    if model.get("status") not in ("collecting", "fitted"):
        raise ValueError(f"unknown ridge status {model.get('status')!r}")
    return {
        "version": state["version"],
        "space_version": state["space_version"],
        "prompt": state["prompt"],
        "baseline_required": state["baseline_required"],
        "baseline_collected": feedback["baseline_collected"],
        "candidate": state.get("candidate"),
        "decisions": state.get("decisions", []),
        "ridge_status": model["status"],
        "ridge_samples": model.get("samples"),
        "ridge_distinct_settings": model.get("distinct_settings"),
        "attempts": {s: count_attempts(s) for s in SPLITS},
    }


__all__ = ["STATE", "FEEDBACK", "ANNOTATIONS", "SPLITS", "attempts_path",
           "count_attempts", "resume_state"]
