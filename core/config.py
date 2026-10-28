"""Load config.json and apply command-line overrides like --set controller.kd=0.06."""
import copy
import json
from pathlib import Path

from . import ROOT

CONFIG_PATH = ROOT / "config.json"


def load(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(cfg, path=CONFIG_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def _parse_value(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text  # plain string


def set_path(cfg, dotted, value):
    keys = dotted.split(".")
    node = cfg
    for k in keys[:-1]:
        if k not in node or not isinstance(node[k], dict):
            raise KeyError(f"unknown config section '{k}' in '{dotted}'")
        node = node[k]
    if keys[-1] not in node:
        raise KeyError(f"unknown config key '{dotted}' (check spelling in config.json)")
    node[keys[-1]] = value


def apply_overrides(cfg, overrides):
    """overrides: list of 'a.b.c=value' strings. Returns a modified deep copy."""
    cfg = copy.deepcopy(cfg)
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"--set needs key=value, got '{item}'")
        key, val = item.split("=", 1)
        set_path(cfg, key.strip(), _parse_value(val.strip()))
    return cfg


def save_value(dotted, value, path=CONFIG_PATH):
    """Persist one value to config.json (used by --save)."""
    cfg = load(path)
    set_path(cfg, dotted, value)
    save(cfg, path)


def resolve(rel):
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p
