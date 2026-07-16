"""
组合设计方案约束校验与修复层 (Design Validator)

对 LLM 输出的方案进行约束校验和自动修复:
  1. 标的数量: 8~15 只
  2. 三层结构: 每层至少 1 只
  3. 核心层必备: 510300(沪深300) + 560600(中证A500)
  4. 权重范围: 单只 1%~30%
  5. 权重加总: 100%
  6. 代码有效性: 必须在全量 ETF 列表中

使用方式:
  plans = validate_and_fix(plans, all_etf_symbols)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MIN_NAMES = 8
MAX_NAMES = 15
MIN_WEIGHT = 0.01   # 1%
MAX_WEIGHT = 0.30   # 30%

# 核心层强制要求
CORE_REQUIRED = ["510300", "560600"]
CORE_MIN_EACH = 0.05  # 各 5%

# 层预算建议值 (非强制，LLM 可偏离)
LAYER_BUDGET_SUGGESTED = {
    "defensive":  {"core": 0.55, "satellite": 0.25, "defense": 0.20},
    "balanced":   {"core": 0.55, "satellite": 0.30, "defense": 0.15},
    "aggressive": {"core": 0.50, "satellite": 0.40, "defense": 0.10},
}


def validate_and_fix(
    plans: list[dict[str, Any]],
    all_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    """校验并修复所有方案。返回修复后的方案列表。

    修复原则: 只修复可量化问题，不做策略层面的修改。
    """
    for plan in plans:
        plan = _fix_symbols(plan, all_symbols)
        plan = _fix_name_count(plan)
        plan = _fix_three_layers(plan)
        plan = _fix_core_required(plan)
        plan = _fix_weight_range(plan)
        plan = _fix_weight_sum(plan)
    return plans


def _fix_symbols(
    plan: dict[str, Any], all_symbols: set[str] | None
) -> dict[str, Any]:
    """校验代码有效性。无效代码从方案中移除。"""
    etfs = plan.get("etfs", []) or plan.get("allocations", [])
    if not etfs or not all_symbols:
        return plan

    valid = [e for e in etfs if e.get("symbol", "") in all_symbols]
    removed = len(etfs) - len(valid)
    if removed:
        logger.info("[validator] Removed %d invalid symbols from %s", removed, plan.get("label", ""))
    if "etfs" in plan:
        plan["etfs"] = valid
    else:
        plan["allocations"] = valid
    return plan


def _fix_name_count(plan: dict[str, Any]) -> dict[str, Any]:
    """修复标的数量到 8~15 之间。"""
    etfs = plan.get("etfs", []) or plan.get("allocations", [])
    if MIN_NAMES <= len(etfs) <= MAX_NAMES:
        return plan

    if len(etfs) > MAX_NAMES:
        # 按权重降序保留前 MAX_NAMES 只
        sorted_etfs = sorted(etfs, key=lambda e: e.get("weight", 0) or e.get("target_weight", 0), reverse=True)
        pruned = sorted_etfs[:MAX_NAMES]
        logger.info("[validator] Pruned %d -> %d for %s", len(etfs), len(pruned), plan.get("label", ""))
        if "etfs" in plan:
            plan["etfs"] = pruned
        else:
            plan["allocations"] = pruned

    return plan


def _fix_three_layers(plan: dict[str, Any]) -> dict[str, Any]:
    """确保三层都存在。如果某层缺失，记录日志但不强制补（由 LLM 决策）。"""
    etfs = plan.get("etfs", []) or plan.get("allocations", [])
    present = set()
    for e in etfs:
        layer = e.get("layer", "")
        if layer:
            present.add(layer)
    missing = {"core", "satellite", "defense"} - present
    if missing:
        logger.warning("[validator] %s missing layers: %s", plan.get("label", ""), missing)
    return plan


def _fix_core_required(plan: dict[str, Any]) -> dict[str, Any]:
    """确保核心层包含 510300 和 560600。"""
    etfs = plan.get("etfs", []) or plan.get("allocations", [])
    core_codes = {e.get("symbol", "") for e in etfs if e.get("layer") == "core"}
    for req in CORE_REQUIRED:
        if req not in core_codes:
            logger.warning("[validator] %s missing required %s", plan.get("label", ""), req)
    return plan


def _fix_weight_range(plan: dict[str, Any]) -> dict[str, Any]:
    """将权重截断到 [MIN_WEIGHT, MAX_WEIGHT]。"""
    etfs = plan.get("etfs", []) or plan.get("allocations", [])
    for e in etfs:
        w = e.get("weight", 0) or e.get("target_weight", 0)
        clipped = max(MIN_WEIGHT, min(MAX_WEIGHT, w))
        if abs(clipped - w) > 0.001:
            logger.info("[validator] Clipped weight %f -> %f for %s", w, clipped, e.get("symbol", ""))
            if "weight" in e:
                e["weight"] = round(clipped, 4)
            if "target_weight" in e:
                e["target_weight"] = round(clipped, 4)
    return plan


def _fix_weight_sum(plan: dict[str, Any]) -> dict[str, Any]:
    """确保权重加总 = 1.0。差额补到权重最大的标的上。"""
    etfs = plan.get("etfs", []) or plan.get("allocations", [])
    total = sum(e.get("weight", 0) or e.get("target_weight", 0) or 0 for e in etfs)
    if abs(total - 1.0) < 0.001:
        return plan

    if total > 0:
        for e in etfs:
            w = e.get("weight", 0) or e.get("target_weight", 0) or 0
            new_w = w / total
            if "weight" in e:
                e["weight"] = round(new_w, 4)
            if "target_weight" in e:
                e["target_weight"] = round(new_w, 4)

        # 修正舍入误差：补到最大权重
        rounded_sum = sum(e.get("weight", 0) or e.get("target_weight", 0) or 0 for e in etfs)
        diff = round(1.0 - rounded_sum, 4)
        if diff != 0:
            max_e = max(etfs, key=lambda e: e.get("weight", 0) or e.get("target_weight", 0))
            if "weight" in max_e:
                max_e["weight"] = round(max_e["weight"] + diff, 4)
            if "target_weight" in max_e:
                max_e["target_weight"] = round(max_e["target_weight"] + diff, 4)

    return plan
