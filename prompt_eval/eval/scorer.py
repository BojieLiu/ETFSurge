import json
import yaml
from pathlib import Path
from typing import Dict, List

DIM_NAMES = ["signal", "trigger", "execution", "horizon", "compliance", "adaptation"]

def score_output(output: dict, ptype: str) -> Dict[str, float]:
    scores = {}
    sigs = output.get("signals", [])
    dec = output.get("decision")
    trg = output.get("trigger_rule_id")
    plan = output.get("rebalance_plan")
    ta = output.get("type_adaptation", {})
    comp = output.get("compliance_pass")

    # 1 signal
    if not sigs or not isinstance(sigs, list):
        scores["signal"] = 0
    elif len(sigs) > 3:
        scores["signal"] = 40
    elif all(k in s for s in sigs for k in ("source","direction","strength","horizon","affected_tickers")):
        scores["signal"] = 100
    else:
        scores["signal"] = 70

    # 2 trigger
    if dec in ("REBALANCE","HOLD") and trg:
        scores["trigger"] = 100
    elif dec in ("REBALANCE","HOLD"):
        scores["trigger"] = 70
    elif dec:
        scores["trigger"] = 40
    else:
        scores["trigger"] = 0

    # 3 execution
    if dec == "HOLD" and plan is None:
        scores["execution"] = 100
    elif plan and all(k in plan for k in ("sell","buy","post_check")):
        scores["execution"] = 100
    elif plan:
        scores["execution"] = 40
    else:
        scores["execution"] = 0

    # 4 horizon
    if all("horizon" in s for s in sigs):
        scores["horizon"] = 100
    elif any("horizon" in s for s in sigs):
        scores["horizon"] = 70
    else:
        scores["horizon"] = 0

    # 5 compliance
    if comp is True and plan and plan.get("post_check"):
        scores["compliance"] = 100
    elif plan and plan.get("post_check"):
        scores["compliance"] = 70
    elif plan:
        scores["compliance"] = 40
    else:
        scores["compliance"] = 0

    # 6 adaptation
    if ta.get("thresholds_used"):
        scores["adaptation"] = 100
    elif ta.get("type"):
        scores["adaptation"] = 70
    else:
        scores["adaptation"] = 40

    return scores

def weighted_total(scores: Dict[str, float], ptype: str, weights: dict) -> float:
    w = weights[ptype]
    return sum(scores[d]*w[i] for i,d in enumerate(DIM_NAMES))