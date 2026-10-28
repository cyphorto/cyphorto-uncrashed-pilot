"""Simulator interaction boundary: window capture, input and the runner.

Uses V2's own copied core/pilot code (identical to the original at copy
time). One runner owns the virtual controller; flights are submitted as
job files. No game is touched at import time.
"""
import sys

from . import _roots as _r

_LAZY = {
    "WindowCapture": ("core.window", "WindowCapture"),
    "find_game_window": ("core.window", "find_game_window"),
    "Gamepad": ("core.gamepad", "Gamepad"),
    "BUTTONS": ("core.gamepad", "BUTTONS"),
    "Runner": ("pilot.runner", "Runner"),
    "V2_ROOT": (None, None),
}


def __getattr__(name):
    if name == "V2_ROOT":
        return _r.V2_ROOT
    try:
        mod_name, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"droneai.sim has no {name!r}") from None
    import importlib
    return getattr(importlib.import_module(mod_name), attr)


def _python():
    venv = _r.V2_ROOT / ".venv/Scripts/python.exe"
    return str(venv) if venv.exists() else sys.executable


def runner_argv(version="p2_fast_baseline"):
    """Command starting the controller-owning runner for a frozen version."""
    if version == "workspace":
        rel = "pilot/runner.py"
    else:
        rel = f"versions/{version}/pilot/runner.py"
    return [_python(), "-u", str(_r.V2_ROOT / rel)]


__all__ = ["WindowCapture", "find_game_window", "Gamepad", "BUTTONS", "Runner",
           "V2_ROOT", "runner_argv"]
