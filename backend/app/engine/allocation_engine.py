"""
ETF Surge — Core allocation engine (pure function).

Uses factor scores to rank and select symbols for core / satellite / defense layers,
then constructs three strategies (defensive / balanced / aggressive).

Pure function — no I/O, no database, no HTTP.
"""

from __future__ import annotations

import math
from typing import Any

from .budgets import STRATEGY_META, dynamic_layer_budget
from .rationale import build_rationale

# ── Global single-position constraints ──────────────────────────
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.30

# P1-3: 强制保留标的（权重不低于 5%，确保进入分配）
MANDATORY_CODES = {"510300", "560600", "518880", "511090"}
MANDATORY_MIN_WEIGHT = 0.05

# ── Default candidate pool (fallback if candidates list is empty) ──
_DEFAULT_CANDIDATES: list[dict[str, Any]] = [
    # Core
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core"},
    {"symbol": "560600", "name": "中证A500ETF", "layer": "core"},
    {"symbol": "512890", "name": "红利低波ETF", "layer": "core"},
    # Satellite
    {"symbol": "512480", "name": "半导体ETF", "layer": "satellite"},
    {"symbol": "515030", "name": "新能源ETF", "layer": "satellite"},
    {"symbol": "512010", "name": "医药ETF", "layer": "satellite"},
    {"symbol": "515080", "name": "中证红利ETF", "layer": "satellite"},
    {"symbol": "561300", "name": "AI人工智能ETF", "layer": "satellite"},
    # Defense
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense"},
    {"symbol": "511090", "name": "30年国债ETF", "layer": "defense"},
    {"symbol": "513500", "name": "标普500ETF", "layer": "defense"},
]


def _power_law_weights(scores: list[float], budget: float) -> list[float]:
    """Distribute *budget* among items according to a power law of *scores*."""
    if not scores:
        return []
    max_s = max(scores)
    exps = [math.exp((s - max_s) * 0.08) for s in scores]
    total_exp = sum(exps)
    if total_exp <= 0:
        return []
    result = [(e / total_exp) * budget for e in exps]
    result = [max(w, MIN_WEIGHT) for w in result]
    total_r = sum(result)
    if total_r > 0:
        result = [w * budget / total_r for w in result]
    result = [min(w, MAX_WEIGHT) for w in result]
    return result


def _select_and_weight(
    candidates: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]],
    budget: float,
    layer: str,
    regime: str,
    strategy: str = "balanced",
    max_count: int = 5,
    exclude_tracked_indices: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Internal helper: score candidates, keep top *max_count*,
    distribute *budget* via power-law, attach rationale.

    Each returned dict has symbol, name, layer, weight, selection_rationale,
    factor_score, and factor_breakdown.

    B3: exclude_tracked_indices — 跳过已选指数的标的，防止同指数多头持仓。
    """
    exclude_indices = exclude_tracked_indices or set()
    if not candidates or budget <= 0:
        return []

    # P1-3: 强制标的从候选池中注入（确保进入分配结果）
    mandatory_assignments = []
    remaining_candidates = []
    for c in candidates:
        sym = c.get("symbol", "")
        if sym in MANDATORY_CODES:
            mandatory_assignments.append({
                "symbol": sym,
                "name": c.get("name", sym),
                "layer": layer,
                "weight": MANDATORY_MIN_WEIGHT,
                "selection_rationale": f"强制保留：{c.get('name', sym)} 作为{layer}层核心配置",
                "factor_score": factor_matrix.get(sym, {}).get("technical", 0),
                "factor_breakdown": factor_matrix.get(sym, {}),
            })
            budget -= MANDATORY_MIN_WEIGHT
        else:
            remaining_candidates.append(c)

    # 如果预算被强制标的耗尽，直接返回
    if budget <= 0:
        return mandatory_assignments
    candidates = remaining_candidates

    # B3: 过滤已选指数的候选
    filtered = []
    for c in candidates:
        tidx = c.get("tracked_index", "") or ""
        if tidx and tidx in exclude_indices:
            continue
        filtered.append(c)
    candidates = filtered

    if not candidates:
        return mandatory_assignments

    # Build (composite_score, candidate, factor_scores) triples
    scored: list[tuple[float, dict[str, Any], dict[str, float]]] = []
    for cand in candidates:
        sym = cand.get("symbol", "")
        factor_scores = factor_matrix.get(sym, {})
        composite = (
            factor_scores.get("technical", 0.0) * 0.3
            + factor_scores.get("momentum", 0.0) * 0.3
            + factor_scores.get("valuation", 0.0) * 0.2
            + factor_scores.get("sentiment", 0.0) * 0.2
        )
        scored.append((composite, cand, factor_scores))

    # Sort descending by composite score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Keep top *max_count*
    selected = scored[:max_count]
    if not selected:
        return mandatory_assignments

    scores = [s[0] for s in selected]
    weights = _power_law_weights(scores, budget)

    results: list[dict[str, Any]] = []
    for (composite, cand, factor_scores), w in zip(selected, weights):
        sym = cand.get("symbol", "")
        name = cand.get("name", sym)
        rationale = build_rationale(
            code=sym,
            layer=layer,
            strategy=strategy,
            factor_scores=factor_scores,
            regime=regime,
        )
        tidx = cand.get("tracked_index", "") or ""
        results.append({
            "symbol": sym,
            "name": name,
            "layer": layer,
            "weight": round(w, 4),
            "tracked_index": tidx,
            "selection_rationale": rationale,
            "factor_score": round(composite, 3),
            "factor_breakdown": {
                k: round(v, 3)
                for k, v in factor_scores.items()
                if isinstance(v, (int, float))
            },
        })

    # P1-3: 合并强制标的到返回结果
    results = mandatory_assignments + results
    return results


def _filter_satellite_by_profile(
    candidates: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]],
    profile_key: str,
) -> list[dict[str, Any]]:
    """C1: 按风险偏好过滤卫星层候选列表，使三方案差异化。

    - defensive: 偏好低波动/防御性行业，剔除高 beta 卫星候选
    - aggressive: 偏好高动量/成长性行业
    - balanced: 全量候选，不做特殊过滤
    """
    if not candidates or profile_key == "balanced":
        return list(candidates)

    scored: list[tuple[float, dict[str, Any]]] = []
    for c in candidates:
        sym = c.get("symbol", "")
        fs = factor_matrix.get(sym, {})
        technical = fs.get("technical", 0.0) or 0.0
        momentum = fs.get("momentum", 0.0) or 0.0
        valuation = fs.get("valuation", 0.0) or 0.0

        if profile_key == "defensive":
            # 防御型：偏好低 technical（低波动）+ 低 momentum（非追涨）的标的
            # 得分越高越适合防御：负面技术信号（technical < 0）+ 低 momentum
            suitability = -technical + (valuation * 0.3) - abs(momentum) * 0.3
        else:
            # 积极型：偏好高 momentum + 高 technical 的标的
            suitability = momentum * 0.5 + technical * 0.3 + valuation * 0.2

        scored.append((suitability, c))

    # 排序并按风偏裁剪候选数量（P1-1: 非仅排序）
    scored.sort(key=lambda x: x[0], reverse=True)
    KEEP_RATIO = {
        "defensive": 0.5,
        "aggressive": 0.6,
        "balanced": 0.8,
    }
    keep_count = max(1, int(len(scored) * KEEP_RATIO.get(profile_key, 1.0)))
    return [item for _, item in scored[:keep_count]]


def allocate(
    risk_profile: str,
    regime: str,
    factor_matrix: dict[str, dict[str, float]],
    candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Build three investment strategies (defensive / balanced / aggressive) using
    factor-based scoring and dynamic layer budgets.

    Args:
        risk_profile:  One of "defensive", "balanced", "aggressive".
        regime:        Current market regime label.
        factor_matrix: Mapping {symbol -> {technical, momentum, valuation, sentiment}}.
        candidates:    List of candidate dicts, each with at least
                       {"symbol": str, "name": str, "layer": str}.
                       If empty/None, a built-in default pool is used.

    Returns:
        A list of 3 strategy dicts, one per risk profile:
        [
          {
            "id": "defensive",
            "label": "防御型",
            "portfolio_name": "防御稳健组合",
            "positioning": "...",
            "expected_return": 0.08,
            "expected_return_current": 0.08,
            "max_drawdown": -0.12,
            "sharpe_ratio": 1.2,
            "layer_budget": {"core": 0.50, "satellite": 0.15, "defense": 0.05},
            "allocations": [
              {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
               "weight": 0.20, "selection_rationale": "...", "factor_score": 0.75},
            ],
            "risk_metrics": {"sector_concentration": ...},
          },
          ...
        ]
    """
    if candidates is None or not candidates:
        candidates = _DEFAULT_CANDIDATES

    # Partition candidates by layer
    core_candidates: list[dict[str, Any]] = []
    sat_candidates: list[dict[str, Any]] = []
    def_candidates: list[dict[str, Any]] = []
    for c in candidates:
        layer = c.get("layer", "core")
        if layer == "core":
            core_candidates.append(c)
        elif layer == "satellite":
            sat_candidates.append(c)
        elif layer == "defense":
            def_candidates.append(c)

    # Build each risk-profile strategy
    strategies: list[dict[str, Any]] = []

    for profile_key in ("defensive", "balanced", "aggressive"):
        meta = STRATEGY_META[profile_key]
        budgets = dynamic_layer_budget(profile_key, regime)
        core_budget = budgets.get("core", 0.0)
        sat_budget = budgets.get("satellite", 0.0)
        def_budget = budgets.get("defense", 0.0)

        allocations: list[dict[str, Any]] = []
        # B3: 跨层追踪已选指数，防止同指数多头持仓
        selected_tracked_indices: set[str] = set()

        # P1-1: 核心层 max_count 风偏差异化
        _CORE_MAX = {"defensive": 2, "balanced": 3, "aggressive": 3}
        _DEFENSE_MAX = {"defensive": 2, "balanced": 1, "aggressive": 1}

        # ── Core layer ──
        core_alloc = _select_and_weight(
            core_candidates,
            factor_matrix,
            core_budget,
            layer="core",
            regime=regime,
            strategy=profile_key,
            max_count=_CORE_MAX.get(profile_key, 4),
            exclude_tracked_indices=selected_tracked_indices,
        )
        for a in core_alloc:
            tidx = a.get("tracked_index", "") or ""
            if tidx:
                selected_tracked_indices.add(tidx)
        allocations.extend(core_alloc)

        # ── Satellite layer — C1: 按 profile_key 差异化过滤 ──
        sat_pool = _filter_satellite_by_profile(sat_candidates, factor_matrix, profile_key)
        sat_alloc = _select_and_weight(
            sat_pool,
            factor_matrix,
            sat_budget,
            layer="satellite",
            regime=regime,
            strategy=profile_key,
            max_count=6,
            exclude_tracked_indices=selected_tracked_indices,
        )
        for a in sat_alloc:
            tidx = a.get("tracked_index", "") or ""
            if tidx:
                selected_tracked_indices.add(tidx)
        allocations.extend(sat_alloc)

        # ── Defense layer ──
        def_alloc = _select_and_weight(
            def_candidates,
            factor_matrix,
            def_budget,
            layer="defense",
            regime=regime,
            strategy=profile_key,
            max_count=_DEFENSE_MAX.get(profile_key, 4),
            exclude_tracked_indices=selected_tracked_indices,
        )
        allocations.extend(def_alloc)

        # ── Compute risk metrics (sector concentration as HHI) ──
        sector_weights: dict[str, float] = {}
        for a in allocations:
            sec = a.get("layer", "其他")
            sector_weights[sec] = sector_weights.get(sec, 0.0) + a.get("weight", 0.0)
        hhi = sum(w ** 2 for w in sector_weights.values())

        risk_metrics = {
            "sector_concentration": round(hhi, 4),
            "sector_breakdown": {
                k: round(v, 4) for k, v in sector_weights.items()
            },
        }

        # ── Regime description ──
        regime_desc_map: dict[str, str] = {
            "bull_strong": "当前市场处于强牛市，资金情绪积极",
            "bull_weakening": "当前市场牛市趋弱，短期有回调压力",
            "range_bound": "当前市场处于震荡格局",
            "correction": "当前市场处于回调阶段，建议控制仓位",
            "bear": "当前市场处于熊市，建议以防御为主",
            "defensive_rotate": "当前市场处于防御轮动阶段，资金从高估值流向低估值",
            "panic": "当前市场情绪恐慌，建议保持现金为主",
        }

        from .budgets import adjust_expected_return

        exp_ret_current = adjust_expected_return(profile_key, regime)

        strategy: dict[str, Any] = {
            "id": meta["id"],
            "label": meta["label"],
            "color": meta["color"],
            "portfolio_name": meta["portfolio_name"],
            "positioning": meta["positioning"],
            "expected_return": meta["expected_return"],
            "expected_return_current": exp_ret_current,
            "max_drawdown": meta["max_drawdown"],
            "sharpe_ratio": meta["sharpe_ratio"],
            "expected_characteristics": meta["expected_characteristics"],
            "market_regime_note": regime_desc_map.get(regime, ""),
            "layer_budget": budgets,
            "allocations": allocations,
            "risk_metrics": risk_metrics,
        }
        strategies.append(strategy)

    return strategies
