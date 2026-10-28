"""Gate and OSD perception boundary.

GateDetector/AltReader/HeightKF are V2's copied core classes. Known gap, stated
not solved: there is no obstacle detector. Ground clearance comes from
core/ground_flow.py (height above ground) and post-hit damage-icon sensing.
"""
from . import _roots as _r

NO_OBSTACLE_DETECTOR = (
    "No obstacle detector exists. Ground safety is core/ground_flow.py "
    "(height above ground) plus core/osd_mode.damage_icon (post-hit only). "
    "Any new map needs a perception check on stills before flight."
)

_LAZY = {
    "GateDetector": ("core.gate_detector", "GateDetector"),
    "Gate": ("core.gate_detector", "Gate"),
    "AltReader": ("core.alt_reader", "AltReader"),
    "HeightKF": ("core.estimator", "HeightKF"),
}


def __getattr__(name):
    try:
        mod_name, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"droneai.perception has no {name!r}") from None
    import importlib
    return getattr(importlib.import_module(mod_name), attr)


__all__ = ["GateDetector", "Gate", "AltReader", "HeightKF", "NO_OBSTACLE_DETECTOR"]
