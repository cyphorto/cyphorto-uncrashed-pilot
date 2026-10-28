"""Flight control boundary: guidance states plus the height/throttle loop.

GateGuidance/Flight/GateFlight are V2's copied pilot classes. apply_map() layers a
map config over a gate_pilot settings dict without mutating its input.
"""
from . import _roots as _r
from . import maps as _maps

_LAZY = {
    "GateGuidance": ("pilot.guidance", "GateGuidance"),
    "Command": ("pilot.guidance", "Command"),
    "Flight": ("pilot.hover_test", "Flight"),
    "GateFlight": ("pilot.gate_run", "GateFlight"),
}


def __getattr__(name):
    try:
        mod_name, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"droneai.control has no {name!r}") from None
    import importlib
    return getattr(importlib.import_module(mod_name), attr)


def apply_map(gate_pilot_cfg, map_name, course_name):
    """Return a copy of gate_pilot_cfg with map+course values applied."""
    cfg = _maps.assert_unlocked(map_name)
    cdef = _maps.course(map_name, course_name)
    out = dict(gate_pilot_cfg)
    out["camera_tilt_deg"] = cfg["camera_tilt_deg"]
    out["max_gates"] = cdef["max_gates"]
    return out


__all__ = ["GateGuidance", "Command", "Flight", "GateFlight", "apply_map"]
