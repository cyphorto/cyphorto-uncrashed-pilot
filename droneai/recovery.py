"""Crash detection and recovery boundary.

Detection: OSD mode text width (ANGLE vs ACRO/3D) and the white damage icon
(core/osd_mode.py), stuck checks and ground contact (pilot/hover_test.py),
abort rules (core/safety.py). Recovery: guidance recover/search states plus a
race restart through GateFlight.finish (pilot/gate_run.py).
"""
from . import _roots as _r

RECOVERY_CHAIN = (
    "detect: core/osd_mode.mode_width + is_angle, damage_icon; "
    "pilot/hover_test Flight.tick stuck/ground branches; core/safety.Safety. "
    "recover: pilot/guidance recover/search states; "
    "pilot/gate_run GateFlight.finish restarts the race (T) instead of landing."
)

_LAZY = {
    "mode_width": ("core.osd_mode", "mode_width"),
    "damage_icon": ("core.osd_mode", "damage_icon"),
    "is_angle": ("core.osd_mode", "is_angle"),
    "Safety": ("core.safety", "Safety"),
}


def __getattr__(name):
    try:
        mod_name, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"droneai.recovery has no {name!r}") from None
    import importlib
    return getattr(importlib.import_module(mod_name), attr)


__all__ = ["mode_width", "damage_icon", "is_angle", "Safety", "RECOVERY_CHAIN"]
