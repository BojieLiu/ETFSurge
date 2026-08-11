"""
risk_controls.py — 因子暴露集中度风控 + 资产质量检查（纯函数，无 I/O）

Constraints can be customized by importing and reassigning the settings object:
    from app.engine.risk_controls import RISK_SETTINGS
    RISK_SETTINGS.max_single_weight = 0.25
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

# F6 (round6 §14.4): 核心层成长风格集中度判定复用 allocation_engine 的
# _is_growth_wide_basis（科创50/创业板/科创100 高 beta 成长宽基）。
from .allocation_engine import _is_growth_wide_basis

logger = logging.getLogger(__name__)


@dataclass
class RiskSettings:
    """Configurable risk constraints.

    All values are decimal fractions (0.30 = 30%).
    """
    max_single_weight: float = 0.30
    max_sector_concentration: float = 0.40
    min_weight: float = 0.01
    # Reserve for future constraints (e.g., correlation, turnover)
    max_correlation: float = 0.95
    max_turnover_rate: float = 0.50


# Global settings singleton — importers can modify as needed
RISK_SETTINGS = RiskSettings()


# round15 9-F1: 市态归一化（与 market_data_hub._normalize_regime 同口径，
# 供 apply_core_bear_growth_trim 判定熊市/回调/恐慌）
_BEARISH_REGIMES = {"bear", "correction", "panic"}


def apply_core_bear_growth_trim(
    allocations: list[dict[str, Any]],
    layer_budget: dict[str, float],
    regime: str = "neutral",
) -> list[dict[str, Any]]:
    """round15 9-F1（docs §10.1）: core 层市态绝对防线。

    熊市/回调/恐慌时，core 层负分成长宽基（科创50/创业板等，非强制锚）权重
    压到 RISK_SETTINGS.min_weight（1%），释放额按权重比例回流 defense 层。

    与 F6 互补（顺序不可反）：F6 先压成长宽基合计 ≤ core×40%，本函数再压
    负分单只到 1%；层预算校验在后——defense 吸收释放额后若超预算会被压回
    budget（L307-313），超限部分隐式转现金，行为可预期。

    三个 factor_score 非 composite 特例必须排除：
    - 强制标的（MANDATORY_CODES）直接跳过（其 factor_score 是 technical 单因子值）；
    - U11 去重回补的新宽基（_cscore 四因子等权和）与 C2 引入标的（satellite 层）
      不落 core_alloc 主路径——core 层只处理正常 composite 分标的。
    """
    from .allocation_engine import MANDATORY_CODES

    if regime not in _BEARISH_REGIMES:
        return allocations
    released = 0.0
    for a in allocations:
        if a.get("layer") != "core":
            continue
        if a.get("symbol") in MANDATORY_CODES:  # 强制保底锚（510300/159338）豁免
            continue
        if _is_growth_wide_basis(a) and float(a.get("factor_score", 0) or 0) < 0:
            _old_w = float(a.get("weight", 0.0) or 0)
            released += _old_w - RISK_SETTINGS.min_weight
            a["weight"] = RISK_SETTINGS.min_weight
            logger.info(
                "[risk] 9-F1 %s core growth-wide-basis %s trimmed to %.0f%% (bear regime, factor_score<0)",
                regime, a.get("symbol"), RISK_SETTINGS.min_weight * 100,
            )
    # 回流：释放额按防御权重比例加到 defense（保持 Σ=1，防预算静默丢弃）
    if released > 0:
        defense = [a for a in allocations if a.get("layer") == "defense"]
        defense_sum = sum(float(a.get("weight", 0.0) or 0) for a in defense)
        if defense and defense_sum > 0:
            for d in defense:
                _d_w = float(d.get("weight", 0.0) or 0)
                d["weight"] = round(_d_w + released * (_d_w / defense_sum), 4)
    return allocations


def _get_constraints() -> dict[str, float]:
    """Read current constraint values from RISK_SETTINGS."""
    return {
        "max_single_weight": RISK_SETTINGS.max_single_weight,
        "max_sector_concentration": RISK_SETTINGS.max_sector_concentration,
        "min_weight": RISK_SETTINGS.min_weight,
    }


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
            # P1-4: 明确括号避免运算符优先级歧义
            risk_note = f"| 【风控：近1月跌{ret_1m*100:.1f}%，月跌幅阈值风控通过】" if ret_1m is not None and ret_1m < -0.20 else ""
            etf["selection_rationale"] = (etf.get("selection_rationale", "") or "") + risk_note
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
            # Factor keys are namespaced: check both bare and prefixed keys
            has_price = fs.get("price", 0) > 0 or abs(fs.get("etf.price", 0)) > 0.0001
            has_return = abs(fs.get("return_1m", 0)) > 0.0001 or abs(fs.get("etf.return_1m", 0)) > 0.0001
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


def _is_dividend_etf(a: dict[str, Any]) -> bool:
    """M1 (R5-0-4): 红利类 ETF 判定（防守型核心：红利低波 512890 / 中证红利 515080 / 红利低波 563020 等）。"""
    sym = a.get("symbol", "")
    if sym in ("512890", "515080", "563020"):
        return True
    name = a.get("name", "") or ""
    tidx = a.get("tracked_index", "") or ""
    return "红利" in name or "红利" in tidx


def _consolidate_minnows(
    strategies: list[dict[str, Any]],
    min_weight: float = 0.02,
) -> list[dict[str, Any]]:
    """B5: 防御层最小权重门槛——合并权重低于 min_weight 的小仓位。

    将 defense 层中权重 < min_weight 的所有小仓位合并到该层最大的标的中，
    避免"羽毛级配置"（如每只 1% 的港股权益）。
    """
    for strategy in strategies:
        allocs = strategy.get("allocations", [])
        defense_items = [a for a in allocs if a.get("layer") == "defense" and a.get("symbol") != "CASH"]
        if len(defense_items) < 2:
            continue

        minnows = [a for a in defense_items if a.get("weight", 0) < min_weight]
        if not minnows:
            continue

        # 找出 defense 层权重最大的标的作为吸收者
        big_fish = max(defense_items, key=lambda a: a.get("weight", 0))
        if big_fish in minnows:
            # 所有 defense 都 < min_weight，合并到最大的那个
            big_fish = max(defense_items, key=lambda a: a.get("weight", 0))

        total_minnow_weight = sum(a.get("weight", 0) for a in minnows)
        # 从 minnows 中移除 big_fish 自身
        for m in list(minnows):
            if m["symbol"] == big_fish["symbol"]:
                minnows.remove(m)
                total_minnow_weight -= m.get("weight", 0)
                break

        if not minnows or total_minnow_weight <= 0:
            continue

        # 将小仓位权重加到 big_fish 上
        big_fish["weight"] = round(big_fish.get("weight", 0) + total_minnow_weight, 4)
        big_fish["selection_rationale"] = (big_fish.get("selection_rationale", "")
                                           + f" | 【合并防御小仓位{len(minnows)}只, 共{total_minnow_weight*100:.1f}%】")

        # 从 allocations 中移除已被合并的 minnows
        minnow_symbols = {m["symbol"] for m in minnows}
        strategy["allocations"] = [a for a in allocs if a["symbol"] not in minnow_symbols]

        logger.info("[risk] _consolidate_minnows: merged %d minnows (%.1f%%) into %s",
                    len(minnows), total_minnow_weight * 100, big_fish["symbol"])

    return strategies


def apply_risk_controls(
    strategies: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]] | None = None,
    regime: str = "neutral",
) -> list[dict[str, Any]]:
    """
    对生成的方案应用风控约束（含质量检查管线）。

    Checks:
    - 单只权重 <= RISK_SETTINGS.max_single_weight
    - 行业集中度 < RISK_SETTINGS.max_sector_concentration
    - 层预算不超标
    - 极端下跌过滤 #2
    - 防御有效性检查 #3
    - 候选池 Freshness 检查 #4
    - round15 9-F1: 熊市 core 层成长宽基绝对防线（regime 参数）
    """
    factor_matrix = factor_matrix or {}

    # Pipeline: fresh check first, then drawdown, then defense
    strategies = remove_stale_candidates(strategies, factor_matrix)
    strategies = filter_extreme_drawdown(strategies, factor_matrix)
    strategies = check_defense_effectiveness(strategies, factor_matrix)
    # B5: 防御层小仓位合并
    strategies = _consolidate_minnows(strategies)

    for strategy in strategies:
        allocations = strategy.get("allocations", [])
        if not allocations:
            continue

        layer_budget: dict[str, float] = strategy.get("layer_budget", {})

        # 1. 单只权重上限
        for a in allocations:
            w = a.get("weight", 0.0)
            if w > RISK_SETTINGS.max_single_weight:
                a["weight"] = RISK_SETTINGS.max_single_weight

        # M1 (R5-0-4): 红利类合计权重上限 15%——全方案校验（用户决策 2026-08-01 D1，
        # 2026-08-03 扩展：balanced/aggressive 卫星层红利同样收 15%，不再仅限 defensive）。
        dividend_weight = sum(a.get("weight", 0.0) for a in allocations if _is_dividend_etf(a))
        if dividend_weight > 0.15:
            _scale = 0.15 / dividend_weight
            for a in allocations:
                if _is_dividend_etf(a):
                    a["weight"] = round(a.get("weight", 0.0) * _scale, 4)
            logger.info("[risk] %s dividend capped: %.1f%% -> 15%%",
                        strategy.get("id", "?"), dividend_weight * 100)

        # F5 (round6 §14.3): 红利层归属约束——红利不得落 satellite 层（层级错配）。
        # core 有容量（< 4 只）时移至 core，否则剔除（防核心层超配）。
        # R5-0-4 校验扩展为"权重 + 层归属"双条件。
        core_count = sum(1 for a in allocations if a.get("layer") == "core")
        kept: list[dict[str, Any]] = []
        for a in allocations:
            if _is_dividend_etf(a) and a.get("layer") == "satellite":
                if core_count < 4:
                    a["layer"] = "core"
                    core_count += 1
                    logger.info("[risk] %s dividend %s moved satellite -> core (layer constraint)",
                                strategy.get("id", "?"), a.get("symbol"))
                else:
                    logger.info("[risk] %s dividend %s removed from satellite (core full, layer constraint)",
                                strategy.get("id", "?"), a.get("symbol"))
                    continue  # 剔除（核心已满时防层级错配）
            kept.append(a)
        allocations = kept
        strategy["allocations"] = allocations

        # F6 (round6 §14.4): 核心层成长风格集中度——高 beta 成长宽基
        # （科创50/创业板/科创100 等）合计 ≤ 核心层预算 40%，超限按比例压缩，
        # 防止进攻方案"科创50+创业板双重暴露 + 卫星科创主题三重叠加"。
        growth_core = [
            a for a in allocations
            if a.get("layer") == "core" and _is_growth_wide_basis(a)
        ]
        if growth_core:
            core_budget = layer_budget.get("core", 0.4)
            growth_cap = core_budget * 0.4
            growth_sum = sum(a.get("weight", 0.0) for a in growth_core)
            if growth_sum > growth_cap + 1e-9:
                _scale = growth_cap / growth_sum
                for a in growth_core:
                    a["weight"] = round(a.get("weight", 0.0) * _scale, 4)
                logger.info(
                    "[risk] %s core growth-wide-basis capped: %.1f%% -> %.1f%% (core_budget=%.2f)",
                    strategy.get("id", "?"), growth_sum * 100, growth_cap * 100, core_budget,
                )

        # round15 9-F1: core 层市态绝对防线——F6（合计 40% 压缩）之后、层预算
        # 校验之前插入；defense 吸收释放额后若超预算由下方层预算校验压回。
        allocations = apply_core_bear_growth_trim(allocations, layer_budget, regime)
        strategy["allocations"] = allocations

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

        # 3. 行业集中度 (HHI) — B4: 使用真实行业字段而非层名
        sector_weights: dict[str, float] = {}
        for a in allocations:
            sec = a.get("industry") or a.get("layer", "其他")
            sector_weights[sec] = sector_weights.get(sec, 0.0) + a.get("weight", 0.0)

        hhi = sum(w ** 2 for w in sector_weights.values())
        if hhi >= RISK_SETTINGS.max_sector_concentration and sector_weights:
            max_sector = max(sector_weights, key=lambda k: sector_weights.get(k, 0))
            target_weight = RISK_SETTINGS.max_sector_concentration ** 0.5
            if sector_weights[max_sector] > target_weight:
                scale = target_weight / sector_weights[max_sector]
                for a in allocations:
                    if (a.get("industry") or a.get("layer", "其他")) == max_sector:
                        a["weight"] = round(a.get("weight", 0.0) * scale, 4)

        # 4. 归一化
        total_weight = sum(a.get("weight", 0.0) for a in allocations)
        if total_weight > 1.0:
            scale_back = 1.0 / total_weight
            for a in allocations:
                a["weight"] = round(a.get("weight", 0.0) * scale_back, 4)

        # 5. 风险度量 — B4: 使用真实行业字段
        sector_w_final: dict[str, float] = {}
        for a in allocations:
            sec = a.get("industry") or a.get("layer", "其他")
            sector_w_final[sec] = sector_w_final.get(sec, 0.0) + a.get("weight", 0.0)
        hhi_final = sum(w ** 2 for w in sector_w_final.values())

        strategy["risk_metrics"] = {
            "sector_concentration": round(hhi_final, 4),
            "sector_breakdown": {k: round(v, 4) for k, v in sector_w_final.items()},
        }

    return strategies
