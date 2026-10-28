"""Optional Meta API integration. Disabled by default.

Meta only ever produces bounded between-flight setting proposals. It never
steers, never runs during flight, and the pilot imports none of this module.
Ledger and config readers below are offline, reading V2's copied
training_data/meta/. V2 makes no live Meta calls.
"""
import json
import os

from . import _roots as _r

CONFIG = _r.V2_ROOT / "training_data/meta/meta_config.json"
LEDGER = _r.V2_ROOT / "training_data/meta/ledger.jsonl"
ALLOW_ENV = "DRONEAI_V2_ALLOW_LIVE"


def config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def ledger_totals():
    calls, spent = 0, 0.0
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                calls += 1
                spent += float(row.get("cost_usd", 0.0))
    budget = float(config().get("budget_usd", 0.0))
    return {"calls": calls, "spent_usd": round(spent, 6), "budget_usd": budget,
            "within_budget": spent <= budget}


def request_live():
    """Always refuses: V2 makes no live Meta calls, opted in or not."""
    raise RuntimeError(
        "Meta live calls are disabled in V2. Proposals are an offline, "
        "human-run step outside the drone application; no key is handled here.")


__all__ = ["CONFIG", "LEDGER", "ALLOW_ENV", "config", "ledger_totals",
           "request_live"]
