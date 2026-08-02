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

# B3b: ETF 名称 → 指数概念兜底提取（当 external tracked_index 为空时）
# 去除基金公司名 + ETF/联接 后缀 → 余下字符串即为指数概念
# 示例："科创100ETF汇添富" → "科创100"，"沪深300ETF华夏" → "沪深300"
_COMPANY_NAMES = [
    "华夏", "易方达", "汇添富", "嘉实", "富国", "招商", "博时", "南方",
    "广发", "华安", "国泰", "鹏华", "天弘", "工银", "建信", "中欧",
    "景顺", "长城", "泰康", "海富通", "光大", "兴全", "东证", "华宝",
    "银华", "大成", "长信", "国联", "申万", "上投", "中信", "华泰",
    "万家", "兴业", "民生", "浦银", "方正", "太平", "前海", "创金",
    "银河", "诺安", "交银", "融通", "泓德", "中加", "永赢", "西部",
    "浙商", "新华", "红土", "安信", "国寿", "英大", "汇丰", "恒生",
    "中银", "国投", "德邦", "华富", "金元", "国金", "九泰", "东方",
    "中泰", "湘财", "国融", "江信", "蜂巢", "东海", "中邮", "华融",
    "金鹰", "长城", "同泰", "红塔", "华润", "格林", "瑞达", "明亚",
    "惠升", "华宸", "富荣", "易米", "长江", "渤海", "爱建", "金元顺安",
]


def _extract_index_concept(name: str) -> str:
    """从 ETF 名称提取指数概念（兜底，仅当外部 tracked_index 不可用时）。

    策略：顺次去除基金公司名 → 去除 ETF/联接/发起 后缀 → 剩余字符串即为指数概念。
    极端兜底：若清理后为空则返回原名的前 6 个字符。

    Examples:
        "科创100ETF汇添富" → "科创100"
        "科创100ETF"      → "科创100"
        "沪深300ETF华夏"  → "沪深300"
        "黄金ETF"          → "黄金"
    """
    clean = name
    for cn in _COMPANY_NAMES:
        clean = clean.replace(cn, "")
    for sfx in ["ETF", "联接", "LOF", "发起式", "发起", "场内", "场外"]:
        clean = clean.replace(sfx, "")
    clean = clean.strip()
    if not clean or len(clean) < 2:
        return name[:6] if len(name) >= 6 else name
    return clean


def _normalize_segment(concept: str) -> str:
    """将指数概念归一化为板块级标识，用于跨层板块集中度控制。

    同一板块内的高度相关指数（科创50/科创100/科创新能源等）被归为同一板块，
    避免分配器在同板块内重复配置造成虚假分散化。

    Examples:
        "科创50" → "科创"
        "科创100" → "科创"
        "科创新能源" → "科创"
        "沪深300" → "沪深300"
        "中证A500" → "中证A500"
        # M3: 同一指数家族归一化（风格/增强切片 → 基准指数）
        "中证500价值" → "中证500"
        "中证500成长" → "中证500"
        "中证500增强" → "中证500"
        "沪深300增强" → "沪深300"
    """
    for prefix in ["科创", "半导体", "芯片", "军工", "新能源"]:
        if concept.startswith(prefix):
            return prefix
    # M3: 中证500/沪深300 家族归一化——同指数不同风格切片视为同一板块，
    # 否则 _balance_by_industry 按 segment 分组无法合并 → 家族霸榜/伪分散
    for base in ("中证500", "沪深300"):
        if concept.startswith(base) and concept != base:
            return base
    return concept


# F0-5 步骤 C: 科创系主题词（名称含这些词的候选合计权重受卫星预算 50% 配额约束）
_TECH_THEMES = ("科创", "半导体", "芯片", "AI", "人工智能")


def _is_tech_theme(name: str) -> bool:
    """判断 ETF 名称是否属于科创系主题（用于卫星层配额裁剪）。"""
    return any(t in (name or "") for t in _TECH_THEMES)


# F0-5 步骤 E: 无估值概念的资产类别（黄金/债券/商品/跨境固收等）。
# 这些资产没有 PE/PB 估值含义，价格因子产生的「估值分」是字段错位假信号，
# 应视为估值缺失，使防御型 C2 惩罚分支（科创 -1.5）正常触发。
_NO_VALUATION_ASSETS = (
    "黄金", "白银", "原油", "商品", "豆粕", "有色", "煤炭", "钢铁",
    "国债", "国开", "进出口", "地方债", "城投债", "可转债", "信用债",
    "货币", "短融", "同业存单", "标普", "纳指", "纳斯达克", "道琼斯",
    "日经", "德国", "法国", "欧洲", "恒生", "中概", "东南亚", "全球",
)


def _valuation_is_meaningful(factor_scores: dict[str, float], name: str = "") -> bool:
    """F0-5 步骤 E: 估值信号是否「有意义」。

    - 无估值概念资产（黄金/债券等）→ 恒 False（估值字段错位值不算数）
    - 有概念但 |valuation| < 0.001 → False（无数据）
    - 其余 → True
    """
    if any(t in (name or "") for t in _NO_VALUATION_ASSETS):
        return False
    return abs(factor_scores.get("valuation", 0.0)) > 0.001

# P1-3: 强制保留标的（权重不低于 3%，确保进入分配）
# 5% ×4=20% 占用过多预算导致总持仓不足 8 只，调整为 3% ×4=12%
MANDATORY_CODES = {"510300", "560600", "518880", "511090"}
MANDATORY_MIN_WEIGHT = 0.03

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
    penalize_symbols: set[str] | None = None,
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

    # B3: 过滤已选指数的候选（归一化到板块级后再比较）
    filtered = []
    for c in candidates:
        tidx = c.get("tracked_index", "") or ""
        if not tidx:
            tidx = _extract_index_concept(c.get("name", ""))
        seg = _normalize_segment(tidx) if tidx else ""
        if seg and seg in exclude_indices:
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
        # ROOT CAUSE FIX: aggregate_factor_scores converts flat keys
        # (e.g. "technical.ma.sma_5") into category-level scores
        # (e.g. "technical", "momentum") before the composite calculation.
        from app.factors.factor_registry import FactorRegistry as _FR
        factor_scores = _FR.aggregate_factor_scores(factor_scores)
        # B: 风偏差异化因子权重 — 按策略调整
        _PROFILE_WEIGHTS = {
            "defensive": {"technical": 0.4, "sentiment": 0.25, "momentum": 0.15, "valuation": 0.2},
            "balanced":  {"technical": 0.3, "sentiment": 0.2,  "momentum": 0.3,  "valuation": 0.2},
            "aggressive":{"technical": 0.2, "sentiment": 0.15, "momentum": 0.45, "valuation": 0.2},
        }
        pw = _PROFILE_WEIGHTS.get(strategy, _PROFILE_WEIGHTS["balanced"])
        composite = (
            factor_scores.get("technical", 0.0) * pw["technical"]
            + factor_scores.get("momentum", 0.0) * pw["momentum"]
            + factor_scores.get("valuation", 0.0) * pw["valuation"]
            + factor_scores.get("sentiment", 0.0) * pw["sentiment"]
        )
        # C2: 风偏差异化修正 — 当 valuation/sentiment 缺乏有效区分度时，
        # 根据 ETF 名称关键字对 composite 做 +/- 调整，使防御/进攻方案真正差异化。
        # 修正值随因子数据质量自动衰减（当 valuation 非零时减弱）。
        _RISKY_THEMES = ["科创", "半导体", "新能源", "军工", "芯片", "AI",
                         "人工智能", "机器人", "云计算", "大数据", "软件"]
        _SAFE_THEMES = ["沪深300", "中证A500", "上证50", "红利", "黄金",
                        "国债", "标普500", "纳指", "MSCI"]
        name = cand.get("name", "")
        c2_bonus = 0.0
        # F0-5 步骤 E: 估值信号需「有意义的非零」才视为可用——
        # 排除字段错位值（黄金等无估值概念标的的 +3.9 类假信号）与
        # ln_mcap/ln_float_mcap；否则判定 valuation_missing=True →
        # 防御型科创惩罚分支（c2_bonus=-1.5）正常触发。
        valuation_missing = not _valuation_is_meaningful(factor_scores, name)
        # 排除 ln_mcap / ln_float_mcap——它们只是市值对数，不是真实估值信号，
        # 且对所有大市值 ETF 值都约 25.33，毫无区分度
        has_meaningful_style = any(
            k.startswith("style.") and abs(v) > 0.001
                and "ln_mcap" not in k and "ln_float" not in k
                for k, v in factor_scores.items()
                if isinstance(v, (int, float))
            )
        if valuation_missing and not has_meaningful_style:
            if strategy == "defensive":
                # 防御型：偏好安全主题，惩罚高风险主题
                if any(t in name for t in _SAFE_THEMES):
                    c2_bonus = 0.8
                elif any(t in name for t in _RISKY_THEMES):
                    c2_bonus = -1.5
            elif strategy == "aggressive":
                # 进攻型：偏好高风险主题，惩罚安全主题
                if any(t in name for t in _RISKY_THEMES):
                    c2_bonus = 1.5
                elif any(t in name for t in _SAFE_THEMES):
                    c2_bonus = -0.3
        # P1: Penalize symbols already used in prior strategies
        if penalize_symbols and sym in penalize_symbols:
            composite -= 1.5  # Reduce score to disadvantage overlap
        composite += c2_bonus
        scored.append((composite, cand, factor_scores))

    # B3b: 按板块归一化后的指数概念去重
    # 先归一化（科创50/科创100/科创新能源 → 科创），然后按归一化后的板块分组，
    # 每组仅保留 composite_score 最高者。
    concept_groups: dict[str, list[tuple[float, dict[str, Any], dict[str, float]]]] = {}
    for item in scored:
        cand = item[1]
        tidx = cand.get("tracked_index", "") or ""
        if not tidx:
            tidx = _extract_index_concept(cand.get("name", ""))
        seg = _normalize_segment(tidx) if tidx else tidx
        concept = seg or tidx or "unknown"
        # 如果该概念已存在且当前评分更高则替换
        if concept not in concept_groups or item[0] > concept_groups[concept][0][0]:
            concept_groups[concept] = [item]
    deduped = list(concept_groups.values())
    # 取每组的第一名（即保留的标的），按评分降序重排
    scored = [group[0] for group in deduped]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Keep top *max_count*
    selected = scored[:max_count]
    if not selected:
        return mandatory_assignments

    scores = [s[0] for s in selected]
    weights = _power_law_weights(scores, budget)

    # F0-5 步骤 C: 卫星层科创系配额 — 名称含 科创/半导体/芯片/AI 的候选
    # 合计权重 ≤ 卫星预算的配额比例（防御型 40% 收紧至验收线 10% 以内，
    # 平衡/进攻 50%），超出部分按 composite 降序裁剪、权重回补其余卫星，
    # 防止科创系包场（同主题不同概念名绕过去重）。
    if layer == "satellite" and budget > 0:
        tech_alloc_total = sum(
            w for (_, cand, _), w in zip(selected, weights)
            if _is_tech_theme(cand.get("name", ""))
        )
        tech_cap_ratio = 0.4 if strategy == "defensive" else 0.5
        tech_cap = budget * tech_cap_ratio
        if tech_alloc_total > tech_cap + 1e-9:
            # 科技候选按 composite 降序，保留到预算上限
            kept: list[tuple] = []
            dropped: list[tuple] = []
            acc = 0.0
            for item, w in zip(selected, weights):
                if _is_tech_theme(item[1].get("name", "")):
                    if acc + w <= tech_cap:
                        kept.append((item, w))
                        acc += w
                    else:
                        room = tech_cap - acc
                        if room > 1e-9:
                            kept.append((item, room))
                            acc = tech_cap
                        dropped.append((item, w - room if room > 1e-9 else w))
                else:
                    kept.append((item, w))
            # 回收被裁剪的权重，按 composite 降序回补其余卫星（不引入 CASH 膨胀）
            reclaimed = sum(w for _, w in dropped)
            non_tech_kept = [(i, w) for i, w in kept if not _is_tech_theme(i[1].get("name", ""))]
            if reclaimed > 0 and non_tech_kept:
                total_non_tech = sum(w for _, w in non_tech_kept)
                if total_non_tech > 0:
                    new_kept = []
                    for i, w in kept:
                        if _is_tech_theme(i[1].get("name", "")):
                            new_kept.append((i, w))
                        else:
                            new_kept.append((i, w + reclaimed * w / total_non_tech))
                    kept = new_kept
            selected = [i for i, _ in kept]
            weights = [w for _, w in kept]

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
            "industry": cand.get("industry", ""),
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

    # 排序并按风偏裁剪候选数量（P1-1: 非仅排序，提高比例达 8-15 只总持仓）
    scored.sort(key=lambda x: x[0], reverse=True)
    KEEP_RATIO = {
        "defensive": 0.6,
        "aggressive": 0.7,
        "balanced": 0.8,
    }
    # F0-5 步骤 D: 卫星数量下限 ≥ 4（预算允许时），防止候选池窄时
    # 卫星层被裁剪到只剩 2 只、失去「多赛道分散」意义。
    keep_count = max(4, int(len(scored) * KEEP_RATIO.get(profile_key, 1.0)))
    keep_count = min(keep_count, len(scored))
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
    # Track symbol usage across profiles to reduce overlap (P1)
    _used_symbols_for_overlap: set[str] = set()

    for profile_key in ("defensive", "balanced", "aggressive"):
        meta = STRATEGY_META[profile_key]
        budgets = dynamic_layer_budget(profile_key, regime)

        allocations: list[dict[str, Any]] = []
        # B3: 跨层去重 — 基于 segment 字段（由 market_data_hub 预先注入）
        selected_segments: set[str] = set()

        def _dedup_segment(a: dict) -> bool:
            """如果 segment 已选则跳过，否则加入 selected_segments。"""
            seg = a.get("segment", "") or ""
            if not seg:
                return True
            if seg in selected_segments:
                return False
            selected_segments.add(seg)
            return True

        # ── Core layer ──
        # Penalize symbols already used in prior strategies (P1)
        _penalize = _used_symbols_for_overlap.copy() if _used_symbols_for_overlap else set()
        # M4: 核心层实际数量 = layer_count - 该层强制标的数（强制 510300/560600 在
        # _select_and_weight 内额外叠加，导致核心层 5-6 只、单只权重被摊薄）。
        mandatory_in_core = sum(1 for c in core_candidates if c.get("symbol") in MANDATORY_CODES)
        core_max_count = max(int(meta.get("layer_count", {}).get("core", 4)) - mandatory_in_core, 1)
        core_alloc = _select_and_weight(
            [c for c in core_candidates if _dedup_segment(c)],
            factor_matrix,
            budgets.get("core", 0.0),
            layer="core",
            regime=regime,
            strategy=profile_key,
            max_count=core_max_count,
            penalize_symbols=_penalize,
        )
        allocations.extend(core_alloc)

        # U11 R1: 后续方案 core 与已用标的重叠过多（全部 ⊂ 前序已用）时，
        # 从 core_candidates 未用者强制引入 ≥1 只新宽基（高分宽基只有 4-5 只，
        # 纯靠 -1.5 惩罚无法避免三方案 core 重复）
        if _used_symbols_for_overlap and core_alloc:
            _core_syms = {a.get("symbol") for a in core_alloc if a.get("symbol") != "CASH"}
            if _core_syms and _core_syms.issubset(_used_symbols_for_overlap):
                _unused_core = [
                    c for c in core_candidates
                    if c.get("symbol") not in _used_symbols_for_overlap
                    and not _is_tech_theme(c.get("name", ""))
                ]
                if _unused_core:
                    def _cscore(c):
                        _fs = factor_matrix.get(c.get("symbol", ""), {}) or {}
                        return sum(_fs.get(k, 0.0) or 0.0
                                   for k in ("technical", "momentum", "valuation", "sentiment"))
                    _extra = max(_unused_core, key=_cscore)
                    _core_non_cash = [a for a in core_alloc if a.get("symbol") != "CASH"]
                    if _core_non_cash:
                        _room = 0.0
                        _cut = min(0.05 / len(_core_non_cash), 0.03)
                        for _a in _core_non_cash:
                            _a["weight"] = round(max(_a.get("weight", 0) - _cut, 0.01), 4)
                            _room += _cut
                        core_alloc.append({
                            "symbol": _extra["symbol"],
                            "name": _extra.get("name", _extra["symbol"]),
                            "layer": "core",
                            "weight": round(min(_room, 0.30), 4),
                            "tracked_index": _extra.get("tracked_index", ""),
                            "industry": _extra.get("industry", ""),
                            "selection_rationale": (
                                f"U11: 跨方案核心去重——引入新宽基 {_extra.get('name', '')} 分散核心层"
                            ),
                            "factor_score": round(_cscore(_extra), 3),
                            "factor_breakdown": factor_matrix.get(_extra["symbol"], {}),
                        })

        # ── Satellite layer — C1: 按 profile_key 差异化过滤 ──
        sat_pool = _filter_satellite_by_profile(sat_candidates, factor_matrix, profile_key)
        sat_alloc = _select_and_weight(
            [c for c in sat_pool if _dedup_segment(c)],
            factor_matrix,
            budgets.get("satellite", 0.0),
            layer="satellite",
            regime=regime,
            strategy=profile_key,
            max_count=meta.get("layer_count", {}).get("satellite", 8),
            penalize_symbols=_penalize,
        )
        allocations.extend(sat_alloc)

        # F0-5 步骤 D: 卫星数量下限 ≥4 — 概念组去重/配额裁剪后实际入选
        # 卫星仍 <4 时，从 core 层未入选者按 composite 降序补足（symbol 级
        # 未入选即允许，绕过 segment 去重——否则 510300 等主流宽基因与
        # core 同 segment 被过滤，卫星层只剩 1-2 只）。
        if len(sat_alloc) < 4:
            used_syms = {a.get("symbol") for a in allocations}
            _backup = []
            for c in core_candidates:
                sym = c.get("symbol", "")
                if sym in used_syms:
                    continue
                # M5: 卫星 backup 排除宽基（industry=宽基指数）——宽基是 core 属性，
                # 混入卫星层使层属性混乱、行业集中度约束失真；宁可卫星 <4 也不引入
                if c.get("industry") == "宽基指数":
                    continue
                # 防御型：补足不引入科创系（科创集中度验收 ≤10%）
                if profile_key == "defensive" and _is_tech_theme(c.get("name", "")):
                    continue
                fs = factor_matrix.get(sym, {})
                composite = (
                    fs.get("technical", 0.0) * 0.3
                    + fs.get("momentum", 0.0) * 0.3
                    + fs.get("valuation", 0.0) * 0.2
                    + fs.get("sentiment", 0.0) * 0.2
                )
                _backup.append((composite, c))
            _backup.sort(key=lambda x: -x[0])
            need = 4 - len(sat_alloc)
            backup_cands = [dict(c) for _, c in _backup[:need]]
            for c in backup_cands:
                c.pop("segment", None)
            # 补足用剩余卫星预算（避免与 sat_alloc 重复分配导致总权重超标）
            spent = sum(
                a.get("weight", 0.0) for a in allocations
                if a.get("layer") == "satellite"
            )
            remaining = max(0.0, budgets.get("satellite", 0.0) - spent)
            if backup_cands and remaining > 1e-6:
                backup_alloc = _select_and_weight(
                    backup_cands,
                    factor_matrix,
                    remaining,
                    layer="satellite",
                    regime=regime,
                    strategy=profile_key,
                    max_count=need,
                    penalize_symbols=_penalize,
                )
                allocations.extend(backup_alloc)

        # C2: 如果卫星层科技主题集中度过高，引入科创50作为分散工具
        tech_industries = {"电子", "通信", "计算机", "半导体"}
        tech_weight = 0
        existing_symbols = {a.get("symbol") for a in allocations}
        for a in allocations:
            if a.get("layer") == "satellite" and a.get("industry", "") in tech_industries:
                tech_weight += a.get("weight", 0.0)
        s_budget = budgets.get("satellite", 0.0)
        if tech_weight > s_budget * 0.6 and "588000" not in existing_symbols and s_budget > 0:
            # 从卫星预算中切出4%给科创50ETF
            tech_etf_weight = min(0.04, s_budget * 0.15)
            tech_etf = {
                "symbol": "588000", "name": "科创50ETF", "layer": "satellite",
                "weight": round(tech_etf_weight, 4),
                "tracked_index": "科创50", "industry": "宽基",
                "selection_rationale": "科技集中度过高，引入科创50宽基ETF分散风险",
                "factor_score": 0, "factor_breakdown": {},
            }
            # 等比例削减现有卫星权重
            surviving = [a for a in allocations if a.get("layer") == "satellite" and a.get("symbol") != "CASH"]
            if surviving:
                reduction_per = tech_etf_weight / len(surviving)
                for a in surviving:
                    a["weight"] = round(max(a.get("weight", 0) - reduction_per, 0.01), 4)
            allocations.append(tech_etf)

        # ── Defense layer ──
        def_alloc = _select_and_weight(
            [c for c in def_candidates if _dedup_segment(c)],
            factor_matrix,
            budgets.get("defense", 0.0),
            layer="defense",
            regime=regime,
            strategy=profile_key,
            max_count=meta.get("layer_count", {}).get("defense", 2),
            penalize_symbols=_penalize,
        )
        allocations.extend(def_alloc)

        # C: 强制标的权重下限后处理 — 低于 5% 的强制标的上调到 5%
        # 优先从总现金仓扣减；现金不足则从非强制标的中等比例扣减
        # （M4 联动：现金不足时旧逻辑的 `if cash_weight < 0` 是死代码，强制标的
        #   永远停在 3%，不满足验收「核心层单只权重 ≥5%」）。
        cash_allocs = [a for a in allocations if a.get("symbol") == "CASH"]
        cash_weight = sum(a.get("weight", 0) for a in cash_allocs)
        for a in allocations:
            sym = a.get("symbol", "")
            if sym in MANDATORY_CODES and a.get("weight", 0) < 0.05:
                needed = 0.05 - a["weight"]
                if cash_weight >= needed:
                    a["weight"] = 0.05
                    cash_weight -= needed
                else:
                    if cash_weight > 1e-9:
                        a["weight"] = round(a["weight"] + cash_weight, 4)
                        needed -= cash_weight
                        cash_weight = 0.0
                    if needed > 1e-9:
                        non_mandatory = [
                            x for x in allocations
                            if x.get("symbol") not in MANDATORY_CODES
                            and x.get("symbol") != "CASH"
                            and x.get("weight", 0) > 0.01
                        ]
                        total_non = sum(x.get("weight", 0) for x in non_mandatory)
                        if total_non > 0:
                            for x in non_mandatory:
                                cut = needed * x.get("weight", 0) / total_non
                                x["weight"] = round(x["weight"] - cut, 4)
                            a["weight"] = round(a["weight"] + needed, 4)

        # ── Compute risk metrics (sector concentration as HHI) ──
        sector_weights: dict[str, float] = {}
        for a in allocations:
            sec = a.get("layer", "其他")
            sector_weights[sec] = sector_weights.get(sec, 0.0) + a.get("weight", 0.0)
        hhi = sum(w ** 2 for w in sector_weights.values())

        # U6 R1: 预算用满——层内分配不满（候选不足/配额裁剪）时剩余预算按
        # factor_score 回补已选标的（旧逻辑：权重和 < 层预算和 → 剩余转 CASH，
        # 实测 balanced 现金 19% > 理论 15%）
        _total_budget = sum(budgets.values())
        _alloc_total = sum(a.get("weight", 0.0) for a in allocations if a.get("symbol") != "CASH")
        _shortfall = max(0.0, _total_budget - _alloc_total)
        if _shortfall > 0.001:
            _topup = sorted(
                [a for a in allocations if a.get("symbol") != "CASH"],
                key=lambda a: -float(a.get("factor_score", 0) or 0),
            )
            if _topup:
                _per = _shortfall / len(_topup)
                for _a in _topup:
                    # 单只 ≤30% 风控（RISK_SETTINGS.max_single_weight 会在 apply_risk_controls 兜底）
                    _a["weight"] = round(min(_a.get("weight", 0.0) + _per, 0.30), 4)

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
        # Accumulate symbols for overlap reduction in subsequent strategies (P1)
        for alloc in allocations:
            sym = alloc.get("symbol", "")
            if sym and sym != "CASH":
                _used_symbols_for_overlap.add(sym)

    return strategies
