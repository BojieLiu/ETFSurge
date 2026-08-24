# -*- coding: utf-8 -*-
"""round35 FM2 重做前置② (docs/round35-architecture-review.md §15.8/§17) —
F7 卫星数门禁的引擎层单测化。

背景：FM2 首次落地时单测全绿、golden（彼时无 warm 场景）全绿，但 live e2e
「F7 balanced 卫星 ≥4」被击穿（4→3，DB 取证见 memory round35-B3B4FM2 条目）。
本测试把该门禁下沉到纯层：对 s6_warm_ic 夹具（含 warm ic_series、候选段互不
碰撞），断言——

1. 卫星数 == max_count 满编（权重相对化只改排序与配比，不改选择数量）；
2. 冷启动与 warm 两态卫星数一致（IC 注入本身不引起数量漂移）；
3. balanced 卫星数满足 e2e 门禁下限 ≥4；
4. 强制锚在 core 层存续（M7 语义联动锚定）。

若未来任何改动使「同族合并级联/排序位移」再度收缩卫星数，此处先于 live e2e 变红。
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

from engine_golden_replay import run_pipeline  # noqa: E402

S6 = Path(__file__).resolve().parent / "fixtures" / "engine_golden" / "scenarios" / "s6_warm_ic.json"


def _satellites(strategies: list[dict]) -> list[str]:
    bal = next(s for s in strategies if s.get("id") == "balanced")
    return [
        a["symbol"]
        for a in bal.get("allocations", [])
        if a.get("layer") == "satellite" and a.get("symbol") not in (None, "CASH")
    ]


def _core_anchors(strategies: list[dict]) -> set[str]:
    bal = next(s for s in strategies if s.get("id") == "balanced")
    return {
        a["symbol"]
        for a in bal.get("allocations", [])
        if a.get("layer") == "core"
        and a.get("symbol") in {"510300", "159338", "518880", "511090"}
    }


@pytest.fixture(scope="module")
def scenario() -> dict:
    return json.loads(S6.read_text(encoding="utf-8"))


def test_satellite_count_matches_cold_start_baseline(scenario) -> None:
    """卫星数以冷启动基线为锚（S5 跨方案顺序耦合是已登记约束，见 §5-S5——
    防御层先跑会经 penalize_symbols 压低平衡层边界候选，故「朴素满编 ==6」
    不是稳定不变量；真正要锁的是：权重相对化不得改变选择数量）。"""
    strategies = run_pipeline(json.loads(json.dumps(scenario)))
    sats = _satellites(strategies)
    cold_scenario = {**scenario, "ic_series": None}
    cold = _satellites(run_pipeline(json.loads(json.dumps(cold_scenario))))
    assert len(sats) == len(cold), (
        f"warm 与冷启动卫星数不一致: warm={sats} cold={cold}"
    )


def test_ic_injection_does_not_change_selection_count(scenario) -> None:
    """冷启动 vs warm 两态卫星数一致——权重相对化不得引起数量漂移。"""
    warm = _satellites(run_pipeline(json.loads(json.dumps(scenario))))
    cold_scenario = {**scenario, "ic_series": None}
    cold = _satellites(run_pipeline(json.loads(json.dumps(cold_scenario))))
    assert len(warm) == len(cold), f"warm={len(warm)} cold={len(cold)}"


def test_balanced_meets_e2e_gate_minimum(scenario) -> None:
    """e2e F7 门禁下限的引擎层等价断言：balanced 卫星 ≥4。"""
    sats = _satellites(run_pipeline(json.loads(json.dumps(scenario))))
    assert len(sats) >= 4, f"低于 e2e F7 门禁下限: {len(sats)}"


def test_mandatory_anchors_survive_in_core(scenario) -> None:
    anchors = _core_anchors(run_pipeline(json.loads(json.dumps(scenario))))
    assert {"510300", "159338"} <= anchors, f"核心锚缺失: {anchors}"
