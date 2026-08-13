"""
ETF Surge — Core allocation engine (pure function).

Uses factor scores to rank and select symbols for core / satellite / defense layers,
then constructs three strategies (defensive / balanced / aggressive).

Pure function — no I/O, no database, no HTTP.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .budgets import STRATEGY_META, dynamic_layer_budget
from .rationale import build_rationale

logger = logging.getLogger(__name__)

# ── Global single-position constraints ──────────────────────────
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.30

# B3b: ETF 名称 → 指数概念兜底提取（当 external tracked_index 为空时）
# 去除基金公司名 + ETF/联接 后缀 → 余下字符串即为指数概念
# 示例："科创100ETF汇添富" → "科创100"，"沪深300ETF华夏" → "沪深300"
_COMPANY_NAMES = [
    # round19 P1-②: 长公司名优先（先剥「华泰柏瑞」整体，避免子串「华泰」误剥成
    # 「A500ETF柏瑞」→ 指数概念提取失败 → 同指数双持有漏判）
    "华泰柏瑞", "柏瑞", "天弘基金", "广发基金",
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


# M5 (P1-1 子步骤 3): A 股宽基语义关键词——卫星 backup 补足时排除，
# 防止 core 属性宽基混入卫星层。industry 字段缺失/为 unknown 时按名称与
# tracked_index 语义补判（A100 562000 industry=unknown 曾漏网，R4-15 验收4 FAIL）。
_A_WIDE_BASIS_KEYWORDS = (
    "中证A100", "A100", "中证A500", "中证A50", "中证500", "中证800",
    "沪深300", "上证50", "上证180", "上证综指", "科创50", "创业板",
    "中证100", "深证100", "MSCI中国",
    # round19 P1-②: 裸 A500/A50——「A500ETF华泰柏瑞」等无「中证」前缀漏判
    "A500", "A50",
)


def _is_wide_basis(c: dict[str, Any]) -> bool:
    """M5: 判断候选是否为 A 股宽基（core 属性）——industry 字段优先，名称/指数语义补判。"""
    ind = (c.get("industry") or "").strip()
    if ind == "宽基指数" or "宽基" in ind:
        return True
    text = f"{c.get('name', '') or ''}{c.get('tracked_index', '') or ''}"
    return any(k in text for k in _A_WIDE_BASIS_KEYWORDS)


# F6 (round6 §14.4): 高 beta 成长宽基识别——核心层风格集中度约束用。
# 科创50/创业板/科创100 等同受成长/科技风格驱动、相关性高，核心层合计
# 不得超过核心预算 40%（与 F4 科技裁剪口径一致：budget × 40%）。
# 注意与 _is_wide_basis 的区别：宽基指全部 A 股宽基，成长宽基仅指高 beta
# 成长风格子集（沪深300/中证A500 等价值/均衡宽基不在此列）。
_GROWTH_WIDE_BASIS_KEYWORDS = (
    "科创50", "科创100", "科创200", "创业板50", "创业板",
    "双创50", "双创", "科创创业",
)


def _is_growth_wide_basis(c: dict[str, Any]) -> bool:
    """F6: 判断候选是否为高 beta 成长宽基（科创50/创业板/科创100 等）。

    industry 字段能区分时（如"半导体"）直接判否——科创芯片 ETF 是主题 ETF
    非宽基；名称/指数语义匹配关键词。
    """
    ind = (c.get("industry") or "").strip()
    if ind and ind != "宽基指数" and "宽基" not in ind:
        # 明确非宽基行业（半导体/医药等主题行业）→ 不是宽基
        return False
    text = f"{c.get('name', '') or ''}{c.get('tracked_index', '') or ''}"
    return any(k in text for k in _GROWTH_WIDE_BASIS_KEYWORDS)


# O16 (round7 §7 P18): 大盘/超大盘宽基识别——核心层「大盘宽基族互斥」约束用。
# 沪深300/中证A500/中证A50/中证A100/上证50/上证180/深证100/中证100/中证800/MSCI中国
# 相关性 ~0.95+，核心层同时押注多只 = 同一「大盘 beta」，分散失效。
# 与 _is_wide_basis 的区别：_is_wide_basis 含中盘（中证500）与成长（科创50/创业板），
# 大盘宽基族仅限大盘/超大盘市值风格（中证500 属中盘、科创50 属成长，均不在此列）。
_LARGE_CAP_WIDE_BASIS_KEYWORDS = (
    "沪深300", "中证A500", "中证A50", "中证A100",
    "上证50", "上证180", "深证100", "中证100", "中证800", "MSCI中国",
    # round19 P1-②: 裸 A500/A50——「A500ETF华泰柏瑞」无「中证」前缀漏判 → 不触发互斥
    "A500", "A50",
)

# 大盘宽基排除词——「中证1000」（中盘小盘指数）含 "中证100" 子串会被误判，
# 先检查排除词（长度优先），命中则不算大盘宽基
_LARGE_CAP_EXCLUDE_KEYWORDS = (
    "中证1000", "中证1000增强", "国证2000", "中证2000",
)


def _is_large_cap_wide_basis(c: dict[str, Any]) -> bool:
    """O16: 判断候选是否属于大盘/超大盘宽基族。

    名称/指数文本匹配关键词（子串语义与 _is_wide_basis 同模式）——
    「中证A500」不子串命中「中证500」（中盘），「科创50/创业板」不命中（成长）。
    排除词优先：中证1000/中证2000 含「中证100」子串但属中盘/小盘，不算大盘。
    """
    text = f"{c.get('name', '') or ''}{c.get('tracked_index', '') or ''}"
    if any(k in text for k in _LARGE_CAP_EXCLUDE_KEYWORDS):
        return False
    return any(k in text for k in _LARGE_CAP_WIDE_BASIS_KEYWORDS)


# O24 (round7 §7 P24): 主驱动因子——composite 中加权贡献最大的因子类别。
# rationale 归因段「主驱动因子 X」据此输出（momentum/valuation/technical/sentiment）。
_FACTOR_LABELS = {"technical": "技术面", "momentum": "动量", "valuation": "估值", "sentiment": "情绪"}


def _dominant_factor(factor_scores: dict[str, float], profile_weights: dict[str, float]) -> str | None:
    """O24: 返回对 composite 加权贡献最大的因子类别（中文标签），全 0 时 None。"""
    contribs = {
        name: factor_scores.get(name, 0.0) * profile_weights.get(name, 0.0)
        for name in ("technical", "momentum", "valuation", "sentiment")
    }
    if not any(abs(v) > 0.001 for v in contribs.values()):
        return None
    top = max(contribs, key=lambda k: abs(contribs[k]))
    return _FACTOR_LABELS.get(top, top)

# P1-3: 强制保留标的（权重不低于 3%，确保进入分配）# 5% ×4=20% 占用过多预算导致总持仓不足 8 只，调整为 3% ×4=12%
# round9 P0-8: 560600（历史写错的中证A500锚：实际为医药白酒ETF/零成交/全源无此证券）
# → 159338（真实中证A500ETF，行情可用），并补 159338 归核心层的定层分支（market_data_hub）
# P2-10 (round9 §4.3-B): 候选池身份校验——强制锚在池层/设计层双防线：
#   ①池层：etf_scanner filter 依赖真实行情成交额/规模（MIN_AVG_AMOUNT），幽灵锚（零成交/
#     无此证券）过不了 filter 进不了候选池；静态兜底 WIDE_BASIS_STATIC 条目经 P0-8 清点后
#     均为真实可成交标的；
#   ②设计层：P1-5 gate——三源（pool/快照/K线）全拿不到涨跌的核心标的权重清零 + 标注；
#   ③验收层：verify_e2e P0-8 断言（方案无幽灵锚 560600）。
MANDATORY_CODES = {"510300", "159338", "518880", "511090"}
# R5-0-2: 公共底仓「宽基锚」——跨方案核心层重叠豁免仅限这些标的 + 强制标的
#（与 verify_e2e M7/P1-1 口径一致：510300/159338 为沪深300/中证A500 锚）。
_COMMON_ANCHOR_SYMBOLS = {"510300", "159338"}
MANDATORY_MIN_WEIGHT = 0.03

# ── Default candidate pool (fallback if candidates list is empty) ──
_DEFAULT_CANDIDATES: list[dict[str, Any]] = [
    # Core
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core"},
    {"symbol": "159338", "name": "中证A500ETF", "layer": "core"},
    {"symbol": "512890", "name": "红利低波ETF", "layer": "core"},
    # Satellite
    {"symbol": "512480", "name": "半导体ETF", "layer": "satellite"},
    {"symbol": "515030", "name": "新能源ETF", "layer": "satellite"},
    {"symbol": "512010", "name": "医药ETF", "layer": "satellite"},
    # F5 (round6 §14.3/§14.6): 中证红利 515080 层归属修正——红利低波是低波防御
    # 资产（R5-0-4 明确列为"防守型核心"），默认 layer 从 satellite 改 core，
    # 配合 risk_controls 层归属校验，杜绝红利进卫星的层级错配。
    {"symbol": "515080", "name": "中证红利ETF", "layer": "core"},
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
        from app.factors.factor_registry import FactorRegistry as _FR, registry as _fr_registry
        # round15 方案一/三: 传 definitions（yaml 方向单一来源）+ IC 序列缓存（聚合前方向化 + IC 加权）
        factor_scores = _FR.aggregate_factor_scores(
            factor_scores,
            definitions=_fr_registry._factors,
            ic_series=getattr(_fr_registry, "_ic_series_cache", None),
        )
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

    # P1-D (round10 §3.1-3/§10): 卫星层负 factor_score 不给权——因子分 ≤ -0.3
    # （约当 |score| 显著为负区间）的标的不入卫星层，防负分标的侵占有限权重。
    # round12 修正: 若过滤后不足布局下限（2 只），从过滤前最高分回补——
    # 三套策略顺序生成时，aggressive 阶段卫星候选常因「重叠惩罚 -1.5」全负
    # （test_satellite_min_count aggressive 曾整层清空）；负分仅作排序降级，
    # 不绝对清空，保卫星层下限。
    if layer == "satellite":
        _before = scored  # item = (composite_score, candidate_dict, factor_scores)
        scored = [item for item in scored if item[0] > -0.3]
        if len(scored) < 2 and _before:
            _backfill = [
                item for item in sorted(_before, key=lambda x: x[0], reverse=True)
                if item[0] <= -0.3
            ]
            scored = scored + _backfill[: 2 - len(scored)]

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
    # O17 (round7 §7 P19): 增加数量维度——科创系标的数量 ≤ 2 只，与权重配额
    # 取更严（先权重裁剪、再数量裁剪），防止「权重不超配额但 4 只科创同现」。
    if layer == "satellite" and budget > 0:
        tech_cap_ratio = 0.4 if strategy == "defensive" else 0.5
        tech_cap = budget * tech_cap_ratio
        TECH_MAX_COUNT = 2  # O17: 科创系数量上限（与 F7「卫星 ≥4 且 ≥2 非科技」呼应）
        tech_items = [
            (item, w) for (item, w) in zip(selected, weights)
            if _is_tech_theme(item[1].get("name", ""))
        ]
        tech_alloc_total = sum(w for _, w in tech_items)
        non_tech_items = [
            (item, w) for (item, w) in zip(selected, weights)
            if not _is_tech_theme(item[1].get("name", ""))
        ]
        if tech_alloc_total > tech_cap + 1e-9 or len(tech_items) > TECH_MAX_COUNT:
            # F4-前置 (round6 §14.6): 裁剪日志——触发/裁剪量/回补结果，
            # 供验收复核「科创合计 ≤ budget×40%/50%」与 task 158 版本差异定位。
            logger.info(
                "[allocation] satellite tech trim triggered: tech_alloc=%.3f > cap=%.3f "
                "or tech_count=%d > %d (budget=%.3f, ratio=%.2f, strategy=%s)",
                tech_alloc_total, tech_cap, len(tech_items), TECH_MAX_COUNT,
                budget, tech_cap_ratio, strategy,
            )
            # 科技候选按 composite 降序，同时受权重配额 + 数量上限约束
            kept: list[tuple] = []
            dropped: list[tuple] = []
            acc = 0.0
            for item, w in sorted(tech_items, key=lambda x: x[0][0], reverse=True):
                if len(kept) >= TECH_MAX_COUNT:
                    dropped.append((item, w))
                    continue
                if acc + w <= tech_cap:
                    kept.append((item, w))
                    acc += w
                else:
                    room = tech_cap - acc
                    if room > 1e-9:
                        kept.append((item, room))
                        acc = tech_cap
                    dropped.append((item, w - room if room > 1e-9 else w))
            kept = non_tech_items + kept
            # 回收被裁剪的权重，按 composite 降序回补其余卫星（不引入 CASH 膨胀）
            reclaimed = sum(w for _, w in dropped)
            logger.info(
                "[allocation] satellite tech trim dropped %.3f weight across %d tech "
                "candidates (kept tech=%.3f, count=%d)",
                reclaimed, len(dropped), acc, len([i for i, _ in kept if _is_tech_theme(i[1].get("name", ""))]),
            )
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
                logger.info(
                    "[allocation] satellite tech trim reclaimed %.3f redistributed across "
                    "%d non-tech candidates",
                    reclaimed, len(non_tech_kept),
                )
            else:
                logger.warning(
                    "[allocation] satellite tech trim: no non-tech candidates to reclaim "
                    "%.3f trimmed weight — weight converts to CASH (satellite budget "
                    "underfill, %.3f of %.3f used)",
                    reclaimed, sum(w for _, w in kept), budget,
                )
            selected = [i for i, _ in kept]
            weights = [w for _, w in kept]

    results: list[dict[str, Any]] = []
    for (composite, cand, factor_scores), w in zip(selected, weights):
        sym = cand.get("symbol", "")
        name = cand.get("name", sym)
        # O24 (round7 §7 P24): 归因链——层内候选池排名 + 主驱动因子
        # （scored 为裁剪前参与评分的候选总数，selected 按 composite 降序）
        rank_info = {
            "rank": selected.index((composite, cand, factor_scores)) + 1,
            "total_candidates": len(scored),
            "dominant_factor": _dominant_factor(factor_scores, _PROFILE_WEIGHTS.get(strategy, _PROFILE_WEIGHTS["balanced"])),
        }
        rationale = build_rationale(
            code=sym,
            layer=layer,
            strategy=strategy,
            factor_scores=factor_scores,
            regime=regime,
            rank_info=rank_info,
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


def _dedup_same_index(allocations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """round19 P1-② (2026-08-12): 同指数双持有硬约束（堵 563360 漏判）。

    判定: tracked_index 相同 或 _extract_index_concept(name) 归一化后相同——
    名称先剥公司名/后缀（_extract_index_concept）再去「中证」前缀，归一到裸指数名
    （"中证A500ETF国泰" → "A500" == "A500ETF华泰柏瑞" → "A500"）。
    处理: 同指数仅保留 factor_score 高者；剔除方权重按同层其余标的权重比例回补；
    强制锚（MANDATORY_CODES）豁免剔除（如 510300+159338 双锚，保留并进报告提示）。
    """
    def _norm(name: str) -> str:
        n = str(name or "").strip()
        if n.startswith("中证"):
            n = n[2:]
        return n

    groups: dict[str, list] = {}
    for a in allocations:
        if a.get("symbol") == "CASH":
            continue
        tidx = _norm(a.get("tracked_index") or "")
        concept = _norm(_extract_index_concept(a.get("name") or ""))
        key = tidx or concept or str(a.get("symbol", ""))
        groups.setdefault(key, []).append(a)

    removed_syms: set[str] = set()
    for key, members in groups.items():
        if len(members) < 2:
            continue
        anchors = [m for m in members if m.get("symbol") in MANDATORY_CODES]
        others = [m for m in members if m.get("symbol") not in MANDATORY_CODES]
        if not others:
            continue  # 全是强制锚（如 510300+159338）→ 豁免剔除，进报告提示
        if anchors:
            # 有锚：强制锚已代表该指数 → 非锚全部剔除（文档：强制锚豁免剔除，
            # 但指数不重复覆盖——159338+563360 场景剔 563360，锚进报告提示）
            removed_syms.update(m.get("symbol") for m in others)
        else:
            keep = max(members, key=lambda m: m.get("factor_score", 0.0) or 0.0)
            removed_syms.update(
                m.get("symbol") for m in members if m.get("symbol") != keep.get("symbol")
            )

    if not removed_syms:
        return allocations

    kept = [a for a in allocations if a.get("symbol") not in removed_syms]
    # 剔除权重按同层其余标的权重比例回补
    for r in allocations:
        if r.get("symbol") not in removed_syms:
            continue
        _w = r.get("weight", 0.0) or 0.0
        if _w <= 1e-9:
            continue
        _layer = r.get("layer", "satellite")
        same_layer = [
            a for a in kept
            if a.get("layer") == _layer and a.get("symbol") not in (None, "CASH")
        ]
        _total = sum((a.get("weight", 0.0) or 0.0) for a in same_layer)
        if _total > 1e-9:
            for a in same_layer:
                a["weight"] = round(
                    (a.get("weight", 0.0) or 0.0)
                    + _w * ((a.get("weight", 0.0) or 0.0) / _total),
                    4,
                )
    logger.info(
        "[allocation] P1-② same-index dedup removed %s (weights reclaimed in-layer)",
        sorted(removed_syms),
    )
    return kept


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
    # Track per-layer symbol usage across profiles to reduce overlap (P2-6 plan A):
    # per-layer penalty (aggressive satellite no longer penalized by prior core/defense
    # picks) fixes the satellite-underfill / cash-inflation bug where non-tech backup
    # candidates were wiped by a cross-layer -1.5 penalty (round20 D-A6).
    _used_core: set[str] = set()
    _used_satellite: set[str] = set()
    _used_defense: set[str] = set()
    # P1-2 (R4-14): 前序方案核心层已占用的「非强制」标的——每方案核心层选取时
    # 排除它们，保证任意两方案核心层重叠（剔除公共底仓 510300 与强制标的）≤1。
    # 强制标的（MANDATORY_CODES）各司其职允许跨方案重复，不计入重叠上限。
    _prev_core_used: set[str] = set()

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
        # P2-6 plan A: penalize only PRIOR CORE-layer symbols (per-layer overlap),
        # not all layers. The old cross-layer penalty applied every prior profile's
        # core/defense picks to the satellite layer too, wiping non-tech backups.
        _penalize_core = _used_core.copy() if _used_core else set()
        # M4: 核心层实际数量 = layer_count - 该层强制标的数（强制 510300/159338 在
        # _select_and_weight 内额外叠加，导致核心层 5-6 只、单只权重被摊薄）。
        mandatory_in_core = sum(1 for c in core_candidates if c.get("symbol") in MANDATORY_CODES)
        core_max_count = max(int(meta.get("layer_count", {}).get("core", 4)) - mandatory_in_core, 1)
        # P1-2: 核心层候选排除前序方案已占用的非强制标的（公共底仓/强制标的保留）
        _core_pool = [c for c in core_candidates if _dedup_segment(c)]
        if _prev_core_used:
            _deduped_pool = [
                c for c in _core_pool
                if c.get("symbol") in MANDATORY_CODES or c.get("symbol") not in _prev_core_used
            ]
            # 兜底：去重后非强制候选 ≥2 才收紧（否则放宽去重，保证核心层数量下限
            # [3,5]——高分宽基候选不足时宁可重叠也不空核心）。
            _deduped_non_mandatory = [
                c for c in _deduped_pool if c.get("symbol") not in MANDATORY_CODES
            ]
            if len(_deduped_non_mandatory) >= 2:
                _core_pool = _deduped_pool
            else:
                # R5-0-2: 兜底放宽——豁免范围仅限「公共底仓 + 强制标的」，不能整体放开。
                # 旧逻辑整体放开导致 balanced/aggressive 核心层重叠 3 只
                #（159915/562000/588000）→ P1-2 门禁 FAIL。修复：去重后非强制候选 <2
                # 时，只回补「宽基锚」（510300/159338）作为公共底仓 + 至多 1 只
                # 高分非锚标的（保证核心层数量下限 [3,5]，重叠仍 ≤1）；其余已用标的一律不回补。
                _deduped_syms = {c.get("symbol") for c in _deduped_pool}
                _anchor_backfill = [
                    c for c in _core_pool
                    if c.get("symbol") in _COMMON_ANCHOR_SYMBOLS
                    and c.get("symbol") not in _deduped_syms
                ]
                _pool_after_anchor = _deduped_pool + _anchor_backfill
                # 高分非锚回补（至多 1 只）：保证核心层数量下限，重叠不超 1
                _unused_non_anchor = [
                    c for c in _core_pool
                    if c.get("symbol") not in {x.get("symbol") for x in _pool_after_anchor}
                ]
                if _unused_non_anchor:
                    def _cscore(c):
                        _fs = factor_matrix.get(c.get("symbol", ""), {}) or {}
                        return sum(_fs.get(k, 0.0) or 0.0
                                   for k in ("technical", "momentum", "valuation", "sentiment"))
                    _top = max(_unused_non_anchor, key=_cscore)
                    _pool_after_anchor = _pool_after_anchor + [_top]
                _core_pool = _pool_after_anchor
        core_alloc = _select_and_weight(
            _core_pool,
            factor_matrix,
            budgets.get("core", 0.0),
            layer="core",
            regime=regime,
            strategy=profile_key,
            max_count=core_max_count,
            penalize_symbols=_penalize_core,
        )
        # O16 (round7 §7 P18): 核心层大盘宽基族互斥——非强制大盘宽基数量 ≤1
        # （强制锚 510300/159338 已占 2 个名额；balanced/aggressive 建议 ≤0，
        # defensive 允许 ≤1 上证50 场景）。超出按 factor_score 降序剔除低分者，
        # 权重按其余核心权重占比回补；剔除后核心层 <3 只时放宽保留 ≤1 只。
        _core_non_anchor_large = [
            a for a in core_alloc
            if a.get("symbol") not in MANDATORY_CODES and _is_large_cap_wide_basis(a)
        ]
        _large_cap_limit = 1 if profile_key == "defensive" else 0
        if len(_core_non_anchor_large) > _large_cap_limit:
            _excess = sorted(
                _core_non_anchor_large,
                key=lambda a: a.get("factor_score", 0.0) or 0.0,
                reverse=True,
            )[_large_cap_limit:]
            _excess_syms = {a.get("symbol", "") for a in _excess}
            _excess_w = sum(a.get("weight", 0.0) or 0.0 for a in _excess)
            _kept_core = [a for a in core_alloc if a.get("symbol") not in _excess_syms]
            # 兜底：剔除后核心层 <3 只 → 回补最高分 1 只（保证数量下限 [3,5]）
            if len(_kept_core) < 3 and _excess:
                _top = sorted(
                    _excess, key=lambda a: a.get("factor_score", 0.0) or 0.0,
                    reverse=True,
                )[0]
                _kept_core.append(_top)
                _excess_w -= _top.get("weight", 0.0) or 0.0
                _excess = [a for a in _excess if a.get("symbol") != _top.get("symbol")]
            if _excess_w > 1e-9 and _kept_core:
                _kept_w_total = sum(a.get("weight", 0.0) or 0.0 for a in _kept_core)
                if _kept_w_total > 0:
                    for a in _kept_core:
                        a["weight"] = round(
                            (a.get("weight", 0.0) or 0.0)
                            + _excess_w * (a.get("weight", 0.0) or 0.0) / _kept_w_total,
                            4,
                        )
            logger.info(
                "[allocation] O16 core large-cap wide-basis exclusion: removed %s "
                "(limit=%d, weight %.3f reclaimed across %d core holdings, strategy=%s)",
                sorted(_excess_syms), _large_cap_limit, _excess_w, len(_kept_core), profile_key,
            )
            core_alloc = _kept_core
        # O16 补充: 预算补足——剔除/兜底后 MAX_WEIGHT(0.30) 钳制可能使核心层权重
        # < core budget（U6 R1「预算用满现金收敛」断言回归：aggressive 核心候选
        # 不足时兜底回补 1 只被钳制 0.3 → 核心预算缺口丢失）。缺口按剩余容量
        # （MAX_WEIGHT - 当前权重）占比补足，单只不超 30%。
        _core_budget = budgets.get("core", 0.0)
        _core_w_now = sum(a.get("weight", 0.0) or 0.0 for a in core_alloc)
        if 0 < _core_w_now < _core_budget - 1e-9:
            _gap = _core_budget - _core_w_now
            _guard = 0
            while _gap > 1e-9 and _guard < 50:
                _guard += 1
                _capacity = [
                    (a, max(0.0, MAX_WEIGHT - (a.get("weight", 0.0) or 0.0)))
                    for a in core_alloc
                ]
                _total_cap = sum(cap for _, cap in _capacity)
                if _total_cap <= 1e-9:
                    break
                _add = min(_gap, _total_cap)
                for a, cap in _capacity:
                    a["weight"] = round(
                        (a.get("weight", 0.0) or 0.0) + _add * (cap / _total_cap), 4,
                    )
                _gap -= _add
            logger.info(
                "[allocation] O16 core budget top-up: filled %.3f of %.3f gap "
                "(strategy=%s, core holdings=%d)",
                _core_budget - _core_w_now - _gap, _core_budget - _core_w_now, profile_key,
                len(core_alloc),
            )
        allocations.extend(core_alloc)
        # P1-2: 记录本方案核心层非强制标的（供后续方案去重）
        _prev_core_used |= {
            a.get("symbol", "") for a in core_alloc
            if a.get("symbol") not in MANDATORY_CODES and a.get("symbol") != "CASH"
        }

        # U11 R1: 后续方案 core 与已用标的重叠过多（全部 ⊂ 前序已用）时，
        # 从 core_candidates 未用者强制引入 ≥1 只新宽基（高分宽基只有 4-5 只，
        # 纯靠 -1.5 惩罚无法避免三方案 core 重复）
        if _used_core and core_alloc:
            _core_syms = {a.get("symbol") for a in core_alloc if a.get("symbol") != "CASH"}
            if _core_syms and _core_syms.issubset(_used_core):
                _unused_core = [
                    c for c in core_candidates
                    if c.get("symbol") not in _used_core
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
        # P1-1 验收4 (R4-15): 卫星层原始候选也排除宽基——M5 只覆盖 backup 补足路径，
        # 原始卫星候选混入宽基（588000 科创50 / 562000 A100 曾入选）导致层属性混乱、
        # 行业集中度约束失真（verify_e2e design-quality 门禁同口径断言）。
        sat_pool = [c for c in sat_pool if not _is_wide_basis(c)]
        # P2-6 plan A: satellite overlap penalty uses ONLY prior SATELLITE-layer symbols
        # (not cross-layer), so non-tech backup candidates aren't wiped by a prior
        # core/defense pick's -1.5 penalty (round20 D-A6 satellite-underfill fix).
        _penalize_sat = _used_satellite.copy() if _used_satellite else set()
        sat_alloc = _select_and_weight(
            [c for c in sat_pool if _dedup_segment(c)],
            factor_matrix,
            budgets.get("satellite", 0.0),
            layer="satellite",
            regime=regime,
            strategy=profile_key,
            max_count=meta.get("layer_count", {}).get("satellite", 8),
            penalize_symbols=_penalize_sat,
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
                # M5: 卫星 backup 排除宽基（industry=宽基指数 + 名称/指数语义补判）——
                # 宽基是 core 属性，混入卫星层使层属性混乱、行业集中度约束失真；
                # 宁可卫星 <4 也不引入（R4-15 验收4：A100 562000 industry=unknown 漏网修复）
                if _is_wide_basis(c):
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
                    penalize_symbols=_penalize_sat,
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
        # P2-6 plan A: defense overlap penalty uses ONLY prior DEFENSE-layer symbols.
        _penalize_def = _used_defense.copy() if _used_defense else set()
        def_alloc = _select_and_weight(
            [c for c in def_candidates if _dedup_segment(c)],
            factor_matrix,
            budgets.get("defense", 0.0),
            layer="defense",
            regime=regime,
            strategy=profile_key,
            max_count=meta.get("layer_count", {}).get("defense", 2),
            penalize_symbols=_penalize_def,
        )
        allocations.extend(def_alloc)

        # round19 P1-②: 同指数双持有硬约束——合并后跨层去重
        # （aggressive 159338 中证A500 core + 563360 A500 satellite = 同一指数；
        # 强制锚豁免，非锚低分者剔除、权重按同层比例回补）
        allocations = _dedup_same_index(allocations)

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
                _lay = alloc.get("layer")
                if _lay == "core":
                    _used_core.add(sym)
                elif _lay == "satellite":
                    _used_satellite.add(sym)
                elif _lay == "defense":
                    _used_defense.add(sym)

    return strategies


def enforce_max_correlation(
    strategies: list[dict[str, Any]],
    correlation_matrix: dict[tuple[str, str], float | None],
    threshold: float = 0.9,
    max_combined_weight: float = 0.25,
) -> list[dict[str, Any]]:
    """P1-1 (round20): 方案内高相关对（r >= threshold）合计权重不得超 max_combined_weight。

    纯函数，无 I/O。数据源为 engine/correlation.py 的 correlation_matrix（由 strategy_design
    用真实 K 线闭源计算，不在此处获取）。对每套方案的两两非 CASH 持仓：若 r >= threshold 且
    合计权重超标，则削减低 factor_score 一方（降到「合计 = 阈值」，下限 MIN_WEIGHT），被削减
    权重按其余标的比例回补（保持 Σ=1），并在 risk_metrics.correlation_warnings 标注。

    验收：高相关对合计权重从 >阈值 降到 <=阈值；被削减标的为低因子分一方；报告含关联度提示。
    """
    for s in strategies:
        allocs = [a for a in s.get("allocations", []) if a.get("symbol") != "CASH"]
        if len(allocs) < 2:
            continue
        reduced_syms: set[str] = set()
        reduced_total = 0.0
        warnings: list[dict[str, Any]] = []
        for i in range(len(allocs)):
            for j in range(i + 1, len(allocs)):
                a, b = allocs[i], allocs[j]
                sa, sb = a.get("symbol"), b.get("symbol")
                r = correlation_matrix.get((sa, sb))
                if r is None:
                    r = correlation_matrix.get((sb, sa))
                if r is None or r < threshold:
                    continue
                wa, wb = a.get("weight", 0.0), b.get("weight", 0.0)
                if wa + wb <= max_combined_weight:
                    continue
                fa = a.get("factor_score", 0.0) or 0.0
                fb = b.get("factor_score", 0.0) or 0.0
                low, high = (a, b) if fa <= fb else (b, a)
                # 削减低因子分一方：目标使「合计 = 阈值」。若 low 被削到 MIN_WEIGHT 下限后
                # 合计仍超标（high 本身已 >= 阈值），则继续削 high 补足差额。
                target_low = max(MIN_WEIGHT, max_combined_weight - high.get("weight", 0.0))
                cut = max(0.0, low.get("weight", 0.0) - target_low)
                if cut <= 1e-9:
                    continue
                low["weight"] = round(target_low, 4)
                reduced_total += cut
                reduced_syms.add(low.get("symbol"))
                # low 触底后仍超标 → 削 high（差额进 reduced_total，同样回补）
                if target_low == MIN_WEIGHT:
                    over = (low.get("weight", 0.0) + high.get("weight", 0.0)) - max_combined_weight
                    if over > 1e-9:
                        high["weight"] = round(max(MIN_WEIGHT, high.get("weight", 0.0) - over), 4)
                        reduced_total += over
                        reduced_syms.add(high.get("symbol"))
                warnings.append({
                    "pair": [sa, sb],
                    "correlation": round(float(r), 3),
                    "combined_weight": round(wa + wb, 4),
                    "reduced_symbol": low.get("symbol"),
                    "note": "高相关对合计权重超阈值，已削减低因子分标的（关联度提示）",
                })
                logger.info(
                    "[allocation] P1-1 high-correlation pair %s (r=%.2f) combined %.3f > %.3f, "
                    "reduced %s", [sa, sb], r, wa + wb, max_combined_weight, low.get("symbol"),
                )
        if reduced_total > 1e-9:
            # 被削减权重按其余（非被削减、非高相关对另一方）标的比例回补，保持 Σ=1。
            # 关键：不得回补给 high 一方——否则该对合计又涨回超阈值。
            pair_high: set[str] = set()
            for i in range(len(allocs)):
                for j in range(i + 1, len(allocs)):
                    a, b = allocs[i], allocs[j]
                    sa, sb = a.get("symbol"), b.get("symbol")
                    r = correlation_matrix.get((sa, sb))
                    if r is None:
                        r = correlation_matrix.get((sb, sa))
                    if r is None or r < threshold:
                        continue
                    if a.get("symbol") in reduced_syms:
                        pair_high.add(b.get("symbol"))
                    elif b.get("symbol") in reduced_syms:
                        pair_high.add(a.get("symbol"))
            others = [
                x for x in allocs
                if x.get("symbol") not in reduced_syms
                and x.get("symbol") not in pair_high
                and x.get("weight", 0.0) > 1e-9
            ]
            total_w = sum(x.get("weight", 0.0) for x in others)
            if total_w > 1e-9:
                for x in others:
                    x["weight"] = round(
                        x.get("weight", 0.0) + reduced_total * (x.get("weight", 0.0) / total_w), 4,
                    )
        if warnings:
            s.setdefault("risk_metrics", {})
            s["risk_metrics"]["correlation_warnings"] = warnings
    return strategies


def check_structure_reasonableness(
    strategies: list[dict[str, Any]],
    correlation_medians: dict[str, float | None] | None = None,
) -> list[dict[str, Any]]:
    """P2-5 (round20): 方案结构合理性检查（防御层归属 / 现金 / 关联度一致性）。

    纯函数，无 I/O。对每套方案：
      - 防御层含综合信号明显负面（factor_score <= -0.5）的标的 → 在 rationale 追加
        「负信号防御标的」提示（验收：负信号防御层 rationale 必含说明，不再静默）；
      - 防御层标的 median_r >= 0.35 却在 rationale 称「避险/低相关」→ 追加高相关提示
        （覆盖 D-A7 跨市场成长误当低相关对冲）；
      - 进攻型现金 > 20% → 记录 structure_warning（aggressive cash 自洽校验）。

    返回原策略列表（就地修正 rationale / 写入 risk_metrics.structure_warnings）。
    """
    correlation_medians = correlation_medians or {}
    for s in strategies:
        sid = s.get("id") or s.get("risk_profile")
        allocs = s.get("allocations", [])
        warnings: list[dict[str, Any]] = []
        for a in allocs:
            if a.get("symbol") == "CASH":
                continue
            sym = a.get("symbol")
            lay = a.get("layer")
            fs = a.get("factor_score", 0.0) or 0.0
            # P2-5-A: 负信号标的不得静默作防御层
            if lay == "defense" and fs <= -0.5:
                note = f"【结构提示：综合信号 {fs:+.2f} 为负，作防御层配置需谨慎——负信号防御标的】"
                a["selection_rationale"] = (a.get("selection_rationale") or "") + note
                warnings.append({"type": "negative_signal_in_defense", "symbol": sym, "factor_score": fs})
            # P2-5-B: 防御层跨市场高相关成长（median_r>=0.35）不得称「避险/低相关」
            if lay == "defense":
                med = correlation_medians.get(sym)
                rat = a.get("selection_rationale") or ""
                if med is not None and med >= 0.35 and ("避险" in rat or "低相关" in rat):
                    note = f"【结构提示：该防御层标的与组合 median r={med:.2f} 偏高，非低相关对冲资产】"
                    a["selection_rationale"] = rat + note
                    warnings.append({"type": "defense_high_median_r", "symbol": sym, "median_r": med})
        # P2-5-C: 进攻型现金 <= 20%
        if sid == "aggressive":
            non_cash = sum(a.get("weight", 0.0) for a in allocs if a.get("symbol") != "CASH")
            cash = round(1.0 - non_cash, 4)
            if cash > 0.20 + 1e-9:
                warnings.append({"type": "aggressive_cash_over_20pct", "cash": cash})
        if warnings:
            s.setdefault("risk_metrics", {})
            s["risk_metrics"]["structure_warnings"] = warnings
    return strategies

