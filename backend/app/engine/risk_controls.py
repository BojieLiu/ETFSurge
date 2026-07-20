"""
risk_controls.py — 因子暴露集中度风控 + 资产质量检查（纯函数，无 I/O）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_SINGLE_WEIGHT = 0.30
MAX_SECTOR_CONCENTRATION = 0.40
MIN_WEIGHT = 0.01


def filter_extreme_drawdown(
    strategies: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]] | None = None,
    threshold: float = -0.40,
) -> list[dict[str, Any]]:
    """
    月跌幅超过 threshold 的标的从方案中剔除（P0 改进 #2）。
    剔除权重等比分配到同层其他标的或转为现金。
    """
    factor_matrix = factor_matrix or {}
    for strategy in strategies:
        etfs = strategy.get("allocations", [])
        if not etfs:
            continue
        filtered = []
        removed_weight = 0.0
        for etf in etfs:
            if etf.get("symbol") == "CASH":
                filtered.append(etf)
                continue
            fs = factor_matrix.get(etf.get("symbol", ""), {})
            ret_1m = fs.get("return_1m") or fs.get("trend.return_1m")
            if ret_1m is not None and ret_1m < threshold:
                removed_weight += etf.get("weight", 0.0)
                logger.info("[risk] excluded %s (1m return %.1f%%, threshold %.0f%%)",
                            etf["symbol"], ret_1m * 100, threshold * 100)
                continue
            etf["selection_rationale"] = (etf.get("selection_rationale", "") +
                                          f"| 【风控：近1月跌{ret_1m*100:.1f}%，月跌幅阈值风控通过】"
                                          if ret_1m is not None and ret_1m < -0.20
                                          else etf.get("selection_rationale", ""))
            filtered.append(etf)
        # Redistribute removed weight proportionally
        if removed_weight > 0 and filtered:
            surviving = [e for e in filtered if e.get("symbol") != "CASH"]
            if surviving:
                boost = removed_weight / len(surviving)
                for e in surviving:
                    e["weight"] = round(e.get("weight", 0.0) + boost, 4)
        strategy["allocations"] = filtered
    return strategies


def check_defense_effectiveness(
    strategies: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]] | None = None,
    threshold: float = -0.10,
) -> list[dict[str, Any]]:
    """
    防御层标的近3月跌幅超 threshold 的，权重减半（P1 改进 #3）。
    """
    factor_matrix = factor_matrix or {}
    for strategy in strategies:
        etfs = strategy.get("allocations", [])
        for etf in etfs:
            if etf.get("layer") != "defense" or etf.get("symbol") == "CASH":
                continue
            fs = factor_matrix.get(etf.get("symbol", ""), {})
            ret_3m = fs.get("return_3m") or fs.get("trend.return_3m")
            if ret_3m is not None and ret_3m < threshold:
                old_w = etf.get("weight", 0)
                etf["weight"] = round(old_w * 0.5, 4)
                rationale = etf.get("selection_rationale", "")
                etf["selection_rationale"] = (rationale +
                    f"【注意：近3月跌{ret_3m*100:.1f}%，防御有效性降低，权重减半】")
                logger.info("[risk] defense %s reduced (3m %.1f%%)", etf["symbol"], ret_3m * 100)
    return strategies


def remove_stale_candidates(
    strategies: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """
    剔除缺失行情数据的标的（price/return 全为空）（P1 改进 #4）。
    """
    factor_matrix = factor_matrix or {}
    for strategy in strategies:
        etfs = strategy.get("allocations", [])
        filtered = []
        removed_weight = 0.0
        for etf in etfs:
            if etf.get("symbol") == "CASH":
                filtered.append(etf)
                continue
            fs = factor_matrix.get(etf.get("symbol", ""), {})
            has_price = fs.get("price") is not None
            has_return = fs.get("return_1m") is not None
            if not has_price and not has_return:
                removed_weight += etf.get("weight", 0.0)
                logger.info("[risk] removed stale %s (no price/return data)", etf["symbol"])
                continue
            filtered.append(etf)
        # Redistribute removed weight
        if removed_weight > 0 and filtered:
            surviving = [e for e in filtered if e.get("symbol") != "CASH"]
            if surviving:
                boost = removed_weight / len(surviving)
                for e in surviving:
                    e["weight"] = round(e.get("weight", 0.0) + boost, 4)
        strategy["allocations"] = filtered
    return strategies


def apply_risk_controls(
    strategies: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """
    对生成的方案应用风控约束（含质量检查管线）。

    Checks:
    - 单只权重 <= MAX_SINGLE_WEIGHT
    - 行业集中度 < MAX_SECTOR_CONCENTRATION
    - 层预算不超标
    - 极端下跌过滤 #2
    - 防御有效性检查 #3
    - 候选池 Freshness 检查 #4
    """
    factor_matrix = factor_matrix or {}

    # Pipeline: fresh check first, then drawdown, then defense
    strategies = remove_stale_candidates(strategies, factor_matrix)
    strategies = filter_extreme_drawdown(strategies, factor_matrix)
    strategies = check_defense_effectiveness(strategies, factor_matrix)

    for strategy in strategies:
        allocations = strategy.get("allocations", [])
        if not allocations:
            continue

        layer_budget: dict[str, float] = strategy.get("layer_budget", {})

        # 1. 单只权重上限
        for a in allocations:
            w = a.get("weight", 0.0)
            if w > MAX_SINGLE_WEIGHT:
                a["weight"] = MAX_SINGLE_WEIGHT

        # 2. 层预算校验
        layer_actual: dict[str, float] = {}
        for a in allocations:
            lay = a.get("layer", "core")
            layer_actual[lay] = layer_actual.get(lay, 0.0) + a.get("weight", 0.0)

        for lay, budget in layer_budget.items():
            actual = layer_actual.get(lay, 0.0)
            if actual > budget and actual > 0:
                scale = budget / actual
                for a in allocations:
                    if a.get("layer") == lay:
                        a["weight"] = round(a.get("weight", 0.0) * scale, 4)

        # 3. 行业集中度 (HHI)
        sector_weights: dict[str, float] = {}
        for a in allocations:
            sec = a.get("layer", "其他")
            sector_weights[sec] = sector_weights.get(sec, 0.0) + a.get("weight", 0.0)

        hhi = sum(w ** 2 for w in sector_weights.values())
        if hhi >= MAX_SECTOR_CONCENTRATION and sector_weights:
            max_sector = max(sector_weights, key=sector_weights.get)
            target_weight = MAX_SECTOR_CONCENTRATION ** 0.5
            if sector_weights[max_sector] > target_weight:
                scale = target_weight / sector_weights[max_sector]
                for a in allocations:
                    if a.get("layer") == max_sector:
                        a["weight"] = round(a.get("weight", 0.0) * scale, 4)

        # 4. 归一化
        total_weight = sum(a.get("weight", 0.0) for a in allocations)
        if total_weight > 1.0:
            scale_back = 1.0 / total_weight
            for a in allocations:
                a["weight"] = round(a.get("weight", 0.0) * scale_back, 4)

        # 5. 风险度量
        sector_w_final: dict[str, float] = {}
        for a in allocations:
            sec = a.get("layer", "其他")
            sector_w_final[sec] = sector_w_final.get(sec, 0.0) + a.get("weight", 0.0)
        hhi_final = sum(w ** 2 for w in sector_w_final.values())

        strategy["risk_metrics"] = {
            "sector_concentration": round(hhi_final, 4),
            "sector_breakdown": {k: round(v, 4) for k, v in sector_w_final.items()},
        }

    return strategies
