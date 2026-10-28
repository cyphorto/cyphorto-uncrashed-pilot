"""Map configurations. Every map-specific value lives in droneai/maps/*.json.

Nothing here steers the drone. Use to_overrides() to build --set args for the
frozen runner, so a new map never requires editing flight code.
"""
import json
from pathlib import Path

MAPS_DIR = Path(__file__).resolve().parent / "maps"

REQUIRED = ("map_id", "game", "courses", "camera_tilt_deg", "flight_mode",
            "vfov_deg_assumed", "status")
COURSE_REQUIRED = ("game_menu", "duration_s", "max_gates")


def available():
    return sorted(p.stem for p in MAPS_DIR.glob("*.json"))


def load_map(name):
    path = MAPS_DIR / f"{name}.json"
    if not path.exists():
        raise ValueError(f"unknown map {name!r}; available: {available()}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ValueError(f"map {name}: missing keys {missing}")
    if cfg["status"] not in ("active", "locked"):
        raise ValueError(f"map {name}: status must be active or locked")
    for course, cdef in cfg["courses"].items():
        missing = [k for k in COURSE_REQUIRED if k not in cdef]
        if missing:
            raise ValueError(f"map {name} course {course}: missing keys {missing}")
    return cfg


def assert_unlocked(name):
    cfg = load_map(name)
    if cfg["status"] == "locked":
        raise ValueError(f"map {name!r} is locked: "
                         + "; ".join(cfg.get("unlock_checklist", ["no checklist"])))
    return cfg


def course(map_name, course_name):
    cfg = load_map(map_name)
    try:
        return cfg["courses"][course_name]
    except KeyError:
        raise ValueError(f"map {map_name!r} has no course {course_name!r}; "
                         f"available: {sorted(cfg['courses'])}") from None


def to_overrides(map_name, course_name):
    """--set args applying this map+course to the frozen runner. Pure function."""
    cfg = assert_unlocked(map_name)
    cdef = course(map_name, course_name)
    return [f"gate_pilot.camera_tilt_deg={cfg['camera_tilt_deg']}",
            f"gate_pilot.max_gates={cdef['max_gates']}"]
