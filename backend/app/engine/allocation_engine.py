"""
ETF Surge — Core allocation engine (pure function).

Uses factor scores to rank and select symbols for core / satellite / defense layers,
then constructs three strategies (defensive / balanced / aggressive).

Pure function — no I/O, no database, no HTTP.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from .budgets import (
    CORE_ANCHORS,  # noqa: F401  round35 B1-F2: re-export（真相源 budgets）
    DEFENSE_ANCHORS,  # noqa: F401
    ENGINE_CONFIG,  # round35 B3-F6: S4 魔法数字单一真相源
    MANDATORY_CODES,  # noqa: F401
    MANDATORY_FLOOR,
    MANDATORY_MIN_WEIGHT,
    STRATEGY_META,
    dynamic_layer_budget,
)
from .taxonomy import (  # round35 B3-F7: 分类语义单点（§6.3）
    COMPANY_NAMES as _COMPANY_NAMES,  # noqa: F401  re-export（pool_balancing 兼容）
    classify_etf,
    extract_index_concept as _extract_index_concept,
    normalize_segment as _normalize_segment,
)
from .rationale import build_rationale

logger = logging.getLogger(__name__)

# ── Global single-position constraints ──────────────────────────
MIN_WEIGHT = 0.01
MAX_WEIGHT = 0.30

# round35 B3-F7 (§6.3): ETF 名称语义（公司名名单/概念提取/归一化）与分类
# 关键词表已迁 engine/taxonomy.py 单点维护；本模块经顶部导入保留原函数名。



# FM3 (round35 §15.5): 风偏差异化因子权重表（原为打分函数内局部变量，提升模块级
# 供单测断言）。etf_quality 第五顶层键接入：权重全部从**结构性恒零的 valuation 槽**
# 划出（FM4 实证：38 因子集下 valuation 顶层键永不产出，0.2 名义槽位空转）——
# technical/sentiment/momentum 三键逐字不动，保证存量 composite 行为不变
# （黄金 s1-s5 可回归）。
_PROFILE_WEIGHTS = {
    "defensive": {"technical": 0.40, "sentiment": 0.25, "momentum": 0.15, "valuation": 0.05, "etf_quality": 0.15},
    "balanced":  {"technical": 0.30, "sentiment": 0.20, "momentum": 0.30, "valuation": 0.05, "etf_quality": 0.15},
    "aggressive":{"technical": 0.20, "sentiment": 0.15, "momentum": 0.45, "valuation": 0.05, "etf_quality": 0.15},
}


def _is_tech_theme(name: str) -> bool:
    """F0-5 步骤 C: 科创系主题判定（关键词表单点 taxonomy.TECH_THEMES）。"""
    return classify_etf({"name": name}).tech_theme



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


def _is_wide_basis(c: dict[str, Any]) -> bool:
    """M5: 是否 A 股宽基——薄包装，语义单点 engine/taxonomy（B3-F7）。"""
    return classify_etf(c).wide_basis


def _is_growth_wide_basis(c: dict[str, Any]) -> bool:
    """F6: 是否高 beta 成长宽基——薄包装（taxonomy.growth_style_of）。"""
    return classify_etf(c).growth_style


def _is_large_cap_wide_basis(c: dict[str, Any]) -> bool:
    """O16 + R101: 是否大盘宽基族（含中证500、排除词优先）——薄包装。"""
    return classify_etf(c).large_cap_family



# R101 (round32): 核心层宽基 >0.95 高相关配对 → correlation_warnings 提示（软约束，
# 非硬剔除）。替代旧 O16「一刀切互斥剔除」：不同宽基指数可并存（用户决策），但高相关
# 配对显式提示「分散有限」，不静默。纯函数，无 I/O。
WIDE_BASIS_HIGH_CORR_THRESHOLD = ENGINE_CONFIG.wide_basis_warn


def wide_basis_high_corr_warnings(
    allocs: list[dict[str, Any]],
    correlation_matrix: dict[tuple[str, str], float | None],
    threshold: float = WIDE_BASIS_HIGH_CORR_THRESHOLD,
) -> list[dict[str, Any]]:
    """round32 R101: 核心层宽基 >0.95 高相关配对 → 提示告警（不剔除）。

    仅对同属核心层、且双方均命中 `_is_large_cap_wide_basis` 的配对生成提示；
    相关性缺失（r=None / 矩阵空）跳过（诚实：无数据不误报）。返回告警条目列表，
    由调用方（strategy_design）并入 risk_metrics.correlation_warnings。
    """
    warnings: list[dict[str, Any]] = []
    non_cash = [
        a for a in allocs
        if a.get("symbol") not in (None, "CASH") and a.get("layer") == "core"
    ]
    if len(non_cash) < 2:
        return warnings
    seen: set[tuple[str, str]] = set()
    for i in range(len(non_cash)):
        for j in range(i + 1, len(non_cash)):
            a, b = non_cash[i], non_cash[j]
            if not (_is_large_cap_wide_basis(a) and _is_large_cap_wide_basis(b)):
                continue
            sa, sb = str(a.get("symbol")), str(b.get("symbol"))
            r = correlation_matrix.get((sa, sb))
            if r is None:
                r = correlation_matrix.get((sb, sa))
            if r is None or r <= threshold:
                continue
            key: tuple[str, str] = (sa, sb) if sa < sb else (sb, sa)
            if key in seen:
                continue
            seen.add(key)
            warnings.append({
                "type": "wide_basis_high_corr",
                "pair": [sa, sb],
                "correlation": round(float(r), 3),
                "note": (
                    f"核心层宽基高相关（r={float(r):.3f}）："
                    f"{a.get('name') or sa} × {b.get('name') or sb} "
                    "不同宽基指数分散有限，注意组合整体市场 beta（软提示，不强制互斥）"
                ),
            })
    return warnings


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
# round22 (#13): 强制标的拆分为「核心锚」与「防御锚」——防御锚受 layer_count.defense 门控，
# 杜绝进攻型防御层被债/金撑爆（round21 #13 实证 进攻防御 19%）。
# round35 B1-F2 (§4.2 D2): CORE_ANCHORS / DEFENSE_ANCHORS / MANDATORY_CODES /
# MANDATORY_MIN_WEIGHT / MANDATORY_FLOOR 单一真相源上移 budgets.py，本模块经
# from-import re-export（上方）——历史双份字面量（此处 vs pool_balancing:25）
# 在锚点增删时必然漂移。_COMMON_ANCHOR_SYMBOLS 为宽基锚子集（语义不同，保留本处）。
_COMMON_ANCHOR_SYMBOLS = {"510300", "159338"}


def _defense_anchors_for(profile_key: str) -> set[str]:
    """round22 (#13): 防御锚注入受 layer_count.defense 门控。

    defense_count>=1 → 注入黄金 518880；defense_count>=2 → 再注入 30年国债 511090。
    进攻/平衡 defense_count=1 → 仅黄金（511090 不进进攻防御层）。防御层按
    defense_count 目标组成（资产递减：进攻仅黄金，防御可含债/金）。
    """
    dc = STRATEGY_META.get(profile_key, {}).get("layer_count", {}).get("defense", 1)
    anchors: set[str] = set()
    if dc >= 1:
        anchors.add("518880")
    if dc >= 2:
        anchors.add("511090")
    return anchors

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
    exps = [math.exp((s - max_s) * ENGINE_CONFIG.softmax_temperature) for s in scores]
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


@dataclass
class SelectionDraft:
    """round36 B5-S1: select 段产物——打分（聚合+pw+C2）/概念去重/初选完成，**未定权重**。

    五段管道（docs/round36-B5-allocate-pipeline.md）第一段的输出结构：
    后续 size()（幂律+钳制）/ constrain() / reconcile() 以此为输入，
    段间不再共享可变 dict 就地改。
    """

    layer: str
    strategy: str
    regime: str
    # 强制标的注入结果（MANDATORY_MIN_WEIGHT 占用预算后单独携带）
    mandatory_assignments: list[dict[str, Any]] = field(default_factory=list)
    # 初选结果：(composite, cand, factor_scores) 三元组，按 composite 降序
    selected: list[tuple[float, dict[str, Any], dict[str, float]]] = field(default_factory=list)
    # 去重+地板过滤后的候选总数（O24 rank_info.total_candidates 口径）
    total_scored: int = 0
    # 强制标的扣减后的可分配预算
    budget_after_mandatory: float = 0.0


def _select_draft(
    candidates: list[dict[str, Any]],
    factor_matrix: dict[str, dict[str, float]],
    budget: float,
    layer: str,
    regime: str,
    strategy: str = "balanced",
    max_count: int = 5,
    exclude_tracked_indices: set[str] | None = None,
    penalize_symbols: set[str] | None = None,
    sector_momentum: list[dict] | None = None,
    mandatory_codes: set[str] | None = None,
    # A1 (round23 §10.1): 引擎纯度参数（allocate 透传，None = 跳过分类聚合）
    factor_definitions: dict | None = None,
    ic_series: dict | None = None,
) -> SelectionDraft | None:
    """B5-S1: select 段纯函数——打分/概念去重/初选，不改权重。

    返回 None 表示「无候选或预算 ≤0」（调用方应返回空列表）；
    ``draft.selected`` 为空且 ``mandatory_assignments`` 非空表示仅强制标的中选。
    """
    exclude_indices = exclude_tracked_indices or set()
    if not candidates or budget <= 0:
        return None

    # P1-3: 强制标的从候选池中注入（确保进入分配结果）
    # round22 (#13): mandatory_codes 由调用方按层传入（核心锚 / 防御锚），
    # 默认回退 MANDATORY_CODES（向后兼容）。
    _mandatory = mandatory_codes if mandatory_codes is not None else MANDATORY_CODES
    mandatory_assignments = []
    remaining_candidates = []
    for c in candidates:
        sym = c.get("symbol", "")
        if sym in _mandatory:
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

    def _only_mandatory() -> SelectionDraft:
        return SelectionDraft(
            layer=layer, strategy=strategy, regime=regime,
            mandatory_assignments=mandatory_assignments,
            selected=[], total_scored=0,
            budget_after_mandatory=budget,
        )

    # 如果预算被强制标的耗尽，直接返回
    if budget <= 0:
        return _only_mandatory()
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
        return _only_mandatory()

    # Build (composite_score, candidate, factor_scores) triples
    scored: list[tuple[float, dict[str, Any], dict[str, float]]] = []
    for cand in candidates:
        sym = cand.get("symbol", "")
        factor_scores = factor_matrix.get(sym, {})
        # ROOT CAUSE FIX: aggregate_factor_scores converts flat keys
        # (e.g. "technical.ma.sma_5") into category-level scores
        # (e.g. "technical", "momentum") before the composite calculation.
        # A1 (round23 §10.1 P1-A): definitions/ic_series 由调用方注入（strategy_design 从
        # registry 读一次传入）；聚合逻辑已下沉 core/factor_aggregate——engine 不再
        # import factor_registry 私有态（纯函数可重放/可测）。
        if factor_definitions is not None:
            from app.core.factor_aggregate import aggregate_factor_scores
            # round15 方案一/三: 传 definitions（yaml 方向单一来源）+ IC 序列缓存（聚合前方向化 + IC 加权）
            factor_scores = aggregate_factor_scores(
                factor_scores,
                definitions=factor_definitions,
                ic_series=ic_series,
            )
        # B: 风偏差异化因子权重 — 按策略调整（表已提升模块级 _PROFILE_WEIGHTS，
        # FM3 etf_quality 接入说明见该处注释）
        pw = _PROFILE_WEIGHTS.get(strategy, _PROFILE_WEIGHTS["balanced"])
        composite = (
            factor_scores.get("technical", 0.0) * pw["technical"]
            + factor_scores.get("momentum", 0.0) * pw["momentum"]
            + factor_scores.get("valuation", 0.0) * pw["valuation"]
            + factor_scores.get("sentiment", 0.0) * pw["sentiment"]
            + factor_scores.get("etf_quality", 0.0) * pw["etf_quality"]
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
                    c2_bonus = ENGINE_CONFIG.c2_defensive_safe_bonus
                elif any(t in name for t in _RISKY_THEMES):
                    c2_bonus = ENGINE_CONFIG.c2_defensive_risky_penalty
            elif strategy == "aggressive":
                # P1-7 (round20): 当日强势板块动态奖励——涨幅前 3 板块对应 ETF +1.5
                # （医药/CRO 等非科技板块当日 +7% 也获奖励；替代 _RISKY_THEMES 静态列表
                # 的「只奖科技」盲区，与 P2-6 方案 A 层内惩罚配套）。
                _strong_bonus = 0.0
                if sector_momentum:
                    _top = sorted(
                        [s for s in sector_momentum
                         if isinstance(s.get("change_pct"), (int, float))],
                        key=lambda s: -s["change_pct"],
                    )[:3]
                    _strong_names = [
                        str(s.get("sector_name") or s.get("name") or "")
                        for s in _top if (s.get("sector_name") or s.get("name"))
                    ]
                    _cand_text = f"{name} {cand.get('industry', '')} {cand.get('tracked_index', '')}"
                    # 双向宽松匹配：板块名与 ETF 文本（名称/行业/跟踪指数）存在 ≥2 字
                    # 公共子串即命中——「医疗服务」vs「医疗ETF」公共子串「医疗」；
                    # 严格包含会漏（板块名带后缀，ETF 名带 ETF 字样）。
                    if _strong_names and _cand_text.strip():
                        def _has_shared_ngram(sec: str, text: str, n: int = 2) -> bool:
                            sec_ng = {sec[i:i + n] for i in range(max(1, len(sec) - n + 1))}
                            txt_ng = {text[i:i + n] for i in range(max(1, len(text) - n + 1))}
                            return bool(sec_ng & txt_ng)
                        if any(
                            _sn and _has_shared_ngram(_sn, _cand_text)
                            for _sn in _strong_names
                        ):
                            _strong_bonus = ENGINE_CONFIG.c2_strong_sector_bonus
                            logger.debug(
                                "[allocation] P1-7 %s %s 命中当日强势板块 %s → %+.2f",
                                strategy, sym, _strong_names[:3], _strong_bonus,
                            )
                if _strong_bonus:
                    c2_bonus = _strong_bonus
                elif any(t in name for t in _RISKY_THEMES):
                    c2_bonus = ENGINE_CONFIG.c2_aggressive_risky_bonus
                elif any(t in name for t in _SAFE_THEMES):
                    c2_bonus = ENGINE_CONFIG.c2_aggressive_safe_penalty
        # P1: Penalize symbols already used in prior strategies
        if penalize_symbols and sym in penalize_symbols:
            composite += ENGINE_CONFIG.overlap_penalty  # round35 B3-F6: 数值入配置
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

    # round22 (#11): 废除卫星层负分绝对排除（原 P1-D score>-0.3 过滤）。该过滤在
    # 跨方案重叠惩罚 -1.5 下把 aggressive 卫星候选全判负 → 整层清空 → 卫星数倒挂
    # （2/6/2）。卫星数量完全由 max_count=layer_count.satellite（单调 4/6/8）门控，
    # 负分仅作排序降级、不绝对清空（与防御/平衡同机制）。回退阶梯质量地板（factor_score
    # 显著为负）在候选池不足时由 _select_and_weight 的 max_count 自然约束，不引入劣质标的。
    if layer == "satellite":
        scored = [item for item in scored if item[0] > ENGINE_CONFIG.satellite_score_floor]

    # Keep top *max_count*
    selected = scored[:max_count]

    return SelectionDraft(
        layer=layer, strategy=strategy, regime=regime,
        mandatory_assignments=mandatory_assignments,
        selected=selected,
        total_scored=len(scored),
        budget_after_mandatory=budget,
    )


def _size_allocations(
    draft: SelectionDraft,
) -> tuple[list[tuple[float, dict[str, Any], dict[str, float]]], list[float]]:
    """round36 B5-S2: size 段纯函数——幂律配权 + 权重钳制一次性完成。

    ``_power_law_weights`` 内部即完整 size 语义（softmax 温度幂律 →
    MIN_WEIGHT 地板 → 预算归一 → MAX_WEIGHT 0.30 帽），本函数将其定名为
    五段管道的第二段：输入 select 段产物，输出 (selected, weights) 平行结构。
    行为直通、无新增判定；S3 起 constrain 段以独立数据结构接续。
    """
    scores = [s[0] for s in draft.selected]
    weights = _power_law_weights(scores, draft.budget_after_mandatory)
    return draft.selected, weights


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
    sector_momentum: list[dict] | None = None,
    mandatory_codes: set[str] | None = None,
    # A1 (round23 §10.1): 引擎纯度参数（allocate 透传，None = 跳过分类聚合）
    factor_definitions: dict | None = None,
    ic_series: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Internal helper: score candidates, keep top *max_count*,
    distribute *budget* via power-law, attach rationale.

    Each returned dict has symbol, name, layer, weight, selection_rationale,
    factor_score, and factor_breakdown.

    B3: exclude_tracked_indices — 跳过已选指数的标的，防止同指数多头持仓.
    P1-7 (round20): sector_momentum — 当日板块涨幅榜；aggressive 对强势板块
    对应 ETF 给动态 c2_bonus（替代 _RISKY_THEMES 静态科技关键词判定）。

    round36 B5-S1: select 段已提取为 :func:`_select_draft`（SelectionDraft 纯函数）；
    本函数保留 size 及其后段（幂律配权 → 科创配额裁剪 → 组装 → 合并强制标的），
    行为等价搬迁、外壳签名不变。
    """
    draft = _select_draft(
        candidates, factor_matrix, budget, layer, regime,
        strategy=strategy, max_count=max_count,
        exclude_tracked_indices=exclude_tracked_indices,
        penalize_symbols=penalize_symbols,
        sector_momentum=sector_momentum,
        mandatory_codes=mandatory_codes,
        factor_definitions=factor_definitions,
        ic_series=ic_series,
    )
    if draft is None:
        return []
    mandatory_assignments = draft.mandatory_assignments
    # B5-S2: size 段（幂律 + MIN/MAX 钳制一次性完成）
    selected, weights = _size_allocations(draft)
    if not selected:
        return mandatory_assignments
    # 卫星科创配额段（F0-5/O17）仍以「强制标的扣减后预算」为基准
    budget = draft.budget_after_mandatory

    # F0-5 步骤 C: 卫星层科创系配额 — 名称含 科创/半导体/芯片/AI 的候选
    # 合计权重 ≤ 卫星预算的配额比例（防御型 40% 收紧至验收线 10% 以内，
    # 平衡/进攻 50%），超出部分按 composite 降序裁剪、权重回补其余卫星，
    # 防止科创系包场（同主题不同概念名绕过去重）。
    # O17 (round7 §7 P19): 增加数量维度——科创系标的数量 ≤ 2 只，与权重配额
    # 取更严（先权重裁剪、再数量裁剪），防止「权重不超配额但 4 只科创同现」。
    if layer == "satellite" and budget > 0:
        tech_cap_ratio = (
            ENGINE_CONFIG.tech_quota_defensive if strategy == "defensive"
            else ENGINE_CONFIG.tech_quota_default
        )
        tech_cap = budget * tech_cap_ratio
        TECH_MAX_COUNT = ENGINE_CONFIG.tech_max_count  # O17: 科创系数量上限（与 F7「卫星 ≥4 且 ≥2 非科技」呼应）
        tech_items = [
            (item, w) for (item, w) in zip(selected, weights, strict=False)
            if _is_tech_theme(item[1].get("name", ""))
        ]
        tech_alloc_total = sum(w for _, w in tech_items)
        non_tech_items = [
            (item, w) for (item, w) in zip(selected, weights, strict=False)
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
    # O24 (round7 §7 P24) / round35 B1-F5 (§4.5 D5): 归因链——层内候选池排名 +
    # 主驱动因子。enumerate 直取下标（消 selected.index(...) 的 O(n²) 与元组相等
    # 匹配脆弱性）；rank_info 存入内部键 "_rank_info"，由编排层 strategy_design
    # 转发进生产 rationale（此前双写覆盖导致排名归因在生产输出中丢失）。
    for _idx, ((composite, cand, factor_scores), w) in enumerate(
        zip(selected, weights, strict=False)
    ):
        sym = cand.get("symbol", "")
        name = cand.get("name", sym)
        rank_info = {
            "rank": _idx + 1,
            "total_candidates": draft.total_scored,
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
            "_rank_info": rank_info,
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
    sector_momentum: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """C1: 按风险偏好过滤卫星层候选列表，使三方案差异化。

    - defensive: 偏好低波动/防御性行业（由 _select_and_weight 的 c2_bonus 实现差异化）
    - aggressive: 偏好高动量/成长性行业
    - 三方案统一返回全量候选，数量由 _select_and_weight 的 max_count=layer_count.satellite
      门控（单调 4/6/8），不再做 KEEP_RATIO 不对称裁剪（round22 #11 倒挂根因）。

    P1-7 (round20): aggressive 下当日强势板块（涨幅前 3）对应 ETF 保底保留——
    动态奖励在 c2_bonus 阶段才 +1.5，若在此先被 KEEP_RATIO 裁掉则奖励无意义
    （医药 +7% 当日最强主线曾因同分排序落选，见 round20 D-A3）。
    """
    if not candidates:
        return list(candidates)

    scored: list[tuple[float, dict[str, Any], bool]] = []
    # P1-7: 强势板块名集合（供 aggressive 保底判定，复用 _select_and_weight 的
    # 公共子串匹配，避免重复实现——此处仅做「是否强势」布尔判定）
    strong_hits: set[str] = set()
    if profile_key == "aggressive" and sector_momentum:
        _top = sorted(
            [s for s in sector_momentum
             if isinstance(s.get("change_pct"), (int, float))],
            key=lambda s: -s["change_pct"],
        )[:3]
        strong_hits = {
            str(s.get("sector_name") or s.get("name") or "")
            for s in _top if (s.get("sector_name") or s.get("name"))
        }

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

        # P1-7: aggressive 强势板块命中标记（供排序后保底）
        _is_strong = False
        if strong_hits:
            _text = f"{c.get('name', '')} {c.get('industry', '')} {c.get('tracked_index', '')}"
            if _text.strip():
                def _shared(sn: str, txt: str, n: int = 2) -> bool:
                    sn_ng = {sn[i:i + n] for i in range(max(1, len(sn) - n + 1))}
                    tx_ng = {txt[i:i + n] for i in range(max(1, len(txt) - n + 1))}
                    return bool(sn_ng & tx_ng)
                _is_strong = any(_shared(h, _text) for h in strong_hits)
        scored.append((suitability, c, _is_strong))

    # 排序（保留评分，便于后续日志/扩展）
    scored.sort(key=lambda x: x[0], reverse=True)
    # round22 (#11): 废除 KEEP_RATIO 不对称裁剪——三方案统一返回全量候选，
    # 卫星数量由 _select_and_weight 的 max_count=layer_count.satellite（单调 4/6/8）门控，
    # 风偏差异化由 c2_bonus 实现。此举消除「balanced 全量 / def-agg 裁剪」倒挂（2/6/2）。
    kept = [item for _, item, _ in scored]
    # P1-7: 强势板块命中保底补入（全量时恒为 no-op，保留兼容）
    _kept_syms = {c.get("symbol") for c in kept}
    for _, item, is_strong in scored:
        if is_strong and item.get("symbol") not in _kept_syms:
            kept.append(item)
            _kept_syms.add(item.get("symbol"))
            logger.debug("[allocation] P1-7 强势板块候选 %s 保底入卫星层", item.get("symbol"))
    return kept


def _substitute_family(c: dict[str, Any]) -> str | None:
    """round24 R24②: 近替代品族判定——薄包装（族表 taxonomy.SUBSTITUTE_FAMILIES）。"""
    return classify_etf(c).substitute_family



def near_substitute_pairs(allocs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """round24 R24②: 近替代品双路检测——同主题不同发行商（纯函数，无 I/O）。

    背景（R24 实证）：设计 570 漏抓主题级冗余——588170/588200（科创半导体）、
    513120/159570（港股药）、512880/513090（券商 A/H）。旧控制仅依赖 K 线相关系数，
    降级盲（r=None）时静默跳过；近替代品即便 r 略<0.9 或价格缺失也应约束/合并。

    实现：对非 CASH 两两，若属于同一主题族（_substitute_family）→ 返回告警条目，
    含族名与合计权重。与 enforce_max_correlation 的高相关削减正交（独立一层），
    r 缺失/偏低不影响判定。
    """
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    non_cash = [a for a in allocs if a.get("symbol") not in (None, "CASH")]
    for i in range(len(non_cash)):
        for j in range(i + 1, len(non_cash)):
            a, b = non_cash[i], non_cash[j]
            sa, sb = a.get("symbol"), b.get("symbol")
            if sa == sb:
                continue
            fam_a = _substitute_family(a)
            if not fam_a:
                continue
            fam_b = _substitute_family(b)
            if fam_b != fam_a:
                continue
            # 符号恒为字符串（non_cash 已过滤 None/CASH），str() 兜底防 None 比较
            sa_s, sb_s = (str(sa), str(sb))
            key: tuple[str, str] = (sa_s, sb_s) if sa_s < sb_s else (sb_s, sa_s)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({
                "type": "near_substitute",
                "pair": [sa, sb],
                "family": fam_a,
                "combined_weight": round((a.get("weight", 0.0) or 0.0) + (b.get("weight", 0.0) or 0.0), 4),
                "note": f"同主题近替代品（{fam_a}族）：不同发行商同一板块，关联度约束不依赖 K 线相关系数",
            })
    return pairs


def _merge_substitute_family(allocs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """R48 (R41-c): 同族近替代品合并留一（无 I/O；**就地修改入参 allocs**）。

    背景（round27 R48 / R41-c）：R41-a/b 只告警不合并，方案仍双持同主题标的
    （「芯片+半导体设备」「港股创新药+港股通创新药」）。用户决策：追求集中应优先
    重仓单只而非分多个同主题标的，故防御/平衡/进攻三型均不豁免。

    副作用（调用方须知）：本函数直接修改传入的 allocs 列表——把被合并标的从列表中
    `remove`（留一），并把并入权重写回保留标的 `keep["weight"]`、打 `keep["merged_from"]`
    标记。因此**不要传入与其它结构共享 dict 对象的列表**（否则会污染共享引用）。
    生产调用点 `strategy_design.generate_enhanced_design` 传入的是每次方案 `s.pop`
    出的独立 allocs，无别名问题。返回值为合并标注列表（供告警升级为「已合并」）。

    实现：对 _SUBSTITUTE_FAMILIES 同族 ≥2 只，保留流动性更好/更宽基者
    （market_cap 大 → 原始权重高 → 出现序），其余标的权重并入保留者并从 allocs
    移除（留一），给保留者打 `merged_from` 标记，并返回合并标注列表
    （供 apply_near_substitute_warnings 把对应 near_substitute 告警升级为「已合并」）。
    """
    non_cash = [a for a in allocs if a.get("symbol") not in (None, "CASH")]
    by_family: dict[str, list[dict[str, Any]]] = {}
    for a in non_cash:
        fam = _substitute_family(a)
        if not fam:
            continue
        by_family.setdefault(fam, []).append(a)
    merges: list[dict[str, Any]] = []
    for fam, group in by_family.items():
        if len(group) < 2:
            continue
        # R105 (round34 §4.3 实施轮发现): 强制锚豁免同族合并——本函数曾把
        # {510300, 159338, 510050}（大盘宽基族）合并留一、保留最高权重的
        # 510050 并将双锚**从列表移除** → 防御型方案核心层缺锚，M7/P1-1 四连
        # FAIL（remove_stale/P1-5 修复后的第三层剥除源）。对齐 MANDATORY_FLOOR
        # 「强制锚永不被削减」哲学与 _dedup_same_index 锚豁免先例：
        #   · 锚永不进入 removed；
        #   · 全锚同族（如 510300+159338 双锚）→ 整组豁免（R101 用户决策：
        #     不同宽基指数可并存），冗余提示由 near_substitute_pairs 告警承担。
        anchor_members = [a for a in group if a.get("symbol") in MANDATORY_CODES]
        if anchor_members and len(anchor_members) == len(group):
            continue
        # 保留方：流动性(规模)优先 → 原始权重优先 → 出现序（max 稳定）
        keep = max(
            group,
            key=lambda a: (a.get("market_cap") or 0.0, a.get("weight") or 0.0),
        )
        removed = [
            a for a in group
            if a is not keep and a.get("symbol") not in MANDATORY_CODES
        ]
        merged_symbols: list[str] = []
        for a in removed:
            sym = a.get("symbol")
            if sym is None:
                continue
            merged_symbols.append(str(sym))
            keep["weight"] = round(
                (keep.get("weight", 0.0) or 0.0) + (a.get("weight", 0.0) or 0.0), 4
            )
            # 从真实 allocs 移除被合并标的（留一）
            if a in allocs:
                allocs.remove(a)
        if merged_symbols:
            keep.setdefault("merged_from", [])
            for m in merged_symbols:
                if m not in keep["merged_from"]:
                    keep["merged_from"].append(m)
            keep["merged"] = True
            merges.append({
                "type": "near_substitute_merged",
                "family": fam,
                "kept_symbol": keep.get("symbol"),
                "kept_name": keep.get("name"),
                "merged_symbols": merged_symbols,
                "combined_weight": keep.get("weight"),
                "note": (
                    f"同主题近替代品（{fam}族）已合并留一：保留 "
                    f"{keep.get('name') or keep.get('symbol')}"
                    f"（权重并入至 {keep.get('weight'):.4f}），"
                    f"移除 {', '.join(merged_symbols)}"
                ),
            })
    return merges


def portfolio_concentration_check(
    allocs: list[dict[str, Any]],
    correlation_matrix: dict[tuple[str, str], float | None],
    avg_threshold: float = ENGINE_CONFIG.concentration_avg,
    min_symbols: int = 3,
) -> dict[str, Any] | None:
    """round24 R24⑥: 组合级分散约束——平均 pairwise r 过高且标的够多 → concentration。

    背景（R24 实证）：仅 pairwise 0.9 封顶 25% 时，「3 只大盘各自受限仍集体冗余」可过
    （510300+159338+510050 ≈31%，两两 r≥0.91 却无告警）。本检查补组合级视角：
    非 CASH 标的 ≥ min_symbols 且有效对平均 r > avg_threshold → 返回告警。
    有效对不足 / 平均不超标 → None（不误报）。
    """
    non_cash = [a for a in allocs if a.get("symbol") not in (None, "CASH")]
    if len(non_cash) < min_symbols:
        return None
    syms = {a.get("symbol") for a in non_cash}
    vals: list[float] = []
    for (a, b), r in correlation_matrix.items():
        if r is None or a not in syms or b not in syms:
            continue
        vals.append(float(r))
    if len(vals) < min_symbols:
        return None
    avg_r = sum(vals) / len(vals)
    if avg_r <= avg_threshold:
        return None
    return {
        "type": "concentration",
        "symbols": sorted(syms),
        "avg_correlation": round(avg_r, 4),
        "pair_count": len(vals),
        "note": (
            f"组合级分散不足：{len(syms)} 只标的两两平均相关 {avg_r:.2f} > {avg_threshold:.1f}，"
            "集体冗余（即使单对相关系数未超阈值）"
        ),
    }


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
    for _key, members in groups.items():
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


def _cap_core_growth_wide_basis(
    core_alloc: list[dict[str, Any]],
    cap: float,
) -> list[dict[str, Any]]:
    """round22 (#10 INV-4): 核心层高 beta 成长宽基（创业板/科创50/科创100 等）合计
    权重不得超过 核心预算 × cap（core_growth_cap）。

    用 `_is_growth_wide_basis` 关键词分类器作 beta 代理（round21 #10 探针 P1 确认
    无 raw β 数据源，不造假）。超出 cap 时按 factor_score 降序逐个移除最低分成长
    宽基，被移除权重按其余核心占比回补（保持核心预算闭合，不归现金虚胀）。
    返回修正后的核心层分配（就地修改权重，返回同一 list）。
    """
    core_non_cash = [a for a in core_alloc if a.get("symbol") != "CASH"]
    if not core_non_cash:
        return core_alloc
    core_w = sum(a.get("weight", 0.0) or 0.0 for a in core_non_cash)
    if core_w <= 0:
        return core_alloc
    cap_w = core_w * cap
    growth = [a for a in core_non_cash if _is_growth_wide_basis(a)]
    growth_w = sum(a.get("weight", 0.0) or 0.0 for a in growth)
    # 核心层数量下限 [3,5]（M7 联动 / O16）：成长宽基占比 cap 是「软偏好」，
    # 不得为压 cap 把核心层削到 <3 只（否则单层集中 + 现金虚胀）。核心仅剩 3 只时
    # 停止移除——cap 让位于数量下限（真实候选池充足时 cap 仍生效）。
    _core_count = len(core_non_cash)
    while growth and growth_w > cap_w + 1e-9 and _core_count > 3:
        # 移除最低 factor_score 的成长宽基（保留高分成长宽基，压低占比至 ≤ cap）
        low = min(growth, key=lambda a: a.get("factor_score", 0.0) or 0.0)
        reclaim = low.get("weight", 0.0) or 0.0
        core_alloc = [a for a in core_alloc if a.get("symbol") != low.get("symbol")]
        growth.remove(low)
        growth_w -= reclaim
        _core_count -= 1
        # 回补必须「预算守恒」：被移除权重按其余核心剩余容量（MAX_WEIGHT - 当前权重）
        # 做水填充（water-filling），单只不超 MAX_WEIGHT。容量不足无法吸收的部分才落
        # 现金（罕见）——避免「单只承接全部回补 → 超 30% 被钳制 → 权重凭空消失 → 现金虚胀」
        # （round22 回归：defensive 现金 28% 根因）。
        _reclaim = reclaim
        _guard = 0
        while _reclaim > 1e-9 and _guard < 50:
            _guard += 1
            _remain = [a for a in core_alloc if a.get("symbol") != "CASH"]
            _cap_left = [
                (a, max(0.0, MAX_WEIGHT - (a.get("weight", 0.0) or 0.0)))
                for a in _remain
            ]
            _total_cap = sum(c for _, c in _cap_left)
            if _total_cap <= 1e-9:
                break  # 其余核心均封顶，残余权重无法吸收（极小概率落现金）
            _add = min(_reclaim, _total_cap)
            for a, c in _cap_left:
                a["weight"] = round(
                    (a.get("weight", 0.0) or 0.0) + _add * (c / _total_cap), 4,
                )
            _reclaim -= _add
        logger.info(
            "[allocation] #10 core growth-wide-basis cap: removed %s (reclaim %.3f, "
            "growth_w now %.3f / cap %.3f)", low.get("symbol"), reclaim, growth_w, cap_w,
        )
    return core_alloc


def allocate(
    risk_profile: str,
    regime: str,
    factor_matrix: dict[str, dict[str, float]],
    candidates: list[dict[str, Any]] | None = None,
    sector_momentum: list[dict] | None = None,
    # A1 (round23 §10.1 P1-A): 引擎纯度参数化——definitions/ic_series 由调用方
    # （strategy_design）从 factor_registry 读取一次注入，engine 内不再 import
    # factor_registry 读私有全局态（纯函数可重放/可测）。
    factor_definitions: dict | None = None,
    ic_series: dict | None = None,
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
        sector_momentum: P1-7 (round20) 当日板块涨幅榜 [{sector_name, change_pct}];
                       aggressive 对强势板块（前 3）对应 ETF 动态 +1.5 c2_bonus.

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
            # B023 安全性：selected_segments 在每个 profile 迭代内重建，
            # 本函数仅在同轮迭代内定义并调用，不存在跨轮晚绑定（round36 审计注记）
            if seg in selected_segments:  # noqa: B023
                return False
            selected_segments.add(seg)  # noqa: B023
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
            sector_momentum=sector_momentum,
            mandatory_codes=CORE_ANCHORS,
            # A1: 透传引擎纯度参数（definitions/ic_series 由 allocate 注入）
            factor_definitions=factor_definitions,
            ic_series=ic_series,
        )
        # O16 (round7 §7 P18) + R101 (round32): 核心层宽基数量上限——互斥剔除 → 软约束。
        # R101 用户决策（2026-08-20）：不同宽基指数可并存（「同一指数才合并（M3 归一化
        # 该留），不同宽基指数没必要合并」）——旧 O16「非强制大盘宽基 ≤1」与强制锚
        # CORE_ANCHORS={510300,159338}（2 只不同宽基被强制并存）自相矛盾，且把核心层
        # 候选剔到只剩强制锚 → M7 core=2 长期失败。改为**数量上限 ≤4（含强制锚）**：
        #   · 中证500 已纳入宽基识别（R101 边界漏洞：实测中证500×沪深300=0.857、
        #     中证500×中证A500=0.935，中盘高相关组合进入上限计数）；
        #   · 超出按 factor_score 降序剔除低分非锚者（强制锚永不剔除），权重按其余
        #     核心标的比例回补；>0.95 配对的高相关提示由 strategy_design 的
        #     wide_basis_high_corr_warnings 层给出（不静默）。
        _core_large = [a for a in core_alloc if _is_large_cap_wide_basis(a)]
        _LARGE_CAP_WIDE_BASIS_LIMIT = ENGINE_CONFIG.large_cap_wide_basis_limit  # 含强制锚（510300/159338 占 2 名额）
        if len(_core_large) > _LARGE_CAP_WIDE_BASIS_LIMIT:
            _anchor_in_core = {a.get("symbol") for a in _core_large} & MANDATORY_CODES
            _keep_non_anchor = _LARGE_CAP_WIDE_BASIS_LIMIT - len(_anchor_in_core)
            _excess = sorted(
                [a for a in _core_large if a.get("symbol") not in MANDATORY_CODES],
                key=lambda a: a.get("factor_score", 0.0) or 0.0,
                reverse=True,
            )[max(_keep_non_anchor, 0):]
            _excess_syms = {a.get("symbol", "") for a in _excess}
            _excess_w = sum(a.get("weight", 0.0) or 0.0 for a in _excess)
            _kept_core = [a for a in core_alloc if a.get("symbol") not in _excess_syms]
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
                "[allocation] R101 core wide-basis cap: removed %s "
                "(limit=%d incl. anchors, weight %.3f reclaimed across %d core holdings, strategy=%s)",
                sorted(_excess_syms), _LARGE_CAP_WIDE_BASIS_LIMIT, _excess_w,
                len(_kept_core), profile_key,
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
        # round22 (#10 INV-4): 核心层高 beta 成长宽基占比上限——核心选完后校验，
        # 超出 core_growth_cap 按 factor_score 逐个移除最低分成长宽基并回补权重。
        # 平衡型核心成长占比压到 ≤40%（round21 #10 实证 67% → ≤40%）。
        _core_growth_cap = STRATEGY_META.get(profile_key, {}).get(
            "core_growth_cap", ENGINE_CONFIG.core_growth_cap_fallback
        )
        core_alloc = _cap_core_growth_wide_basis(core_alloc, _core_growth_cap)
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
        sat_pool = _filter_satellite_by_profile(
            sat_candidates, factor_matrix, profile_key, sector_momentum=sector_momentum,
        )
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
            sector_momentum=sector_momentum,
            mandatory_codes=set(),
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
                    sector_momentum=sector_momentum,
                    mandatory_codes=set(),
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
        # round22 (#13): 防御锚按 layer_count.defense 门控——defense_count=1 → 仅黄金 518880；
        # =2 → 黄金+30年国债。max_count 取剩余名额（defense_count - 锚数），保证防御层
        # 实际数量 = defense_count（资产递减：进攻仅黄金，防御含债/金）。
        _def_anchors = _defense_anchors_for(profile_key)
        _defense_count = meta.get("layer_count", {}).get("defense", 1)
        _def_max = max(0, _defense_count - len(_def_anchors))
        def_alloc = _select_and_weight(
            [c for c in def_candidates if _dedup_segment(c)],
            factor_matrix,
            budgets.get("defense", 0.0),
            layer="defense",
            regime=regime,
            strategy=profile_key,
            max_count=_def_max,
            penalize_symbols=_penalize_def,
            sector_momentum=sector_momentum,
            mandatory_codes=_def_anchors,
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

        # round35 B1-F4 (§4.4 D4): 删除基于 layer 名的 HHI 死计算——以 layer 名当
        # 「行业」算出的集中度恒为「层预算平方和」（同一 profile+regime 下近似常量），
        # 对持仓内容完全不敏感；编排层紧随其后的 apply_risk_controls 用真实 industry
        # 字段重算并整体覆盖 strategy["risk_metrics"]（risk_controls.py 行业 HHI 段），
        # 本侧数值从未被生产输出消费。sector_concentration 单点产出 =
        # apply_risk_controls（industry 缺失时才 fallback layer 名，有且仅有一处）。

        # U6 R1: 预算用满——层内分配不满（候选不足/配额裁剪）时剩余预算按
        # factor_score 回补已选标的（旧逻辑：权重和 < 层预算和 → 剩余转 CASH，
        # 实测 balanced 现金 19% > 理论 15%）
        _total_budget = sum(budgets.values())
        _alloc_total = sum(a.get("weight", 0.0) for a in allocations if a.get("symbol") != "CASH")
        _shortfall = max(0.0, _total_budget - _alloc_total)
        if _shortfall > 0.001:
            # round22 (#13): 强制锚（黄金/国债等）已按后处理抬到 5% 目标，不必再参与
            # 预算回补——否则会被 top-up 推过 0.05（如进攻黄金 0.052 > INV-6 钳制）。
            _topup = sorted(
                [a for a in allocations
                 if a.get("symbol") != "CASH" and a.get("symbol") not in MANDATORY_CODES],
                key=lambda a: -float(a.get("factor_score", 0) or 0),
            )
            if _topup:
                _per = _shortfall / len(_topup)
                for _a in _topup:
                    # 单只 ≤30% 风控（RISK_SETTINGS.max_single_weight 会在 apply_risk_controls 兜底）
                    _a["weight"] = round(min(_a.get("weight", 0.0) + _per, 0.30), 4)

        # round35 B1-F4: 不再写入 sector_concentration/sector_breakdown（见上）；
        # risk_metrics 键保留空 dict 以兼容直接消费 allocate 返回值的调用点，
        # apply_risk_controls 后由风控层整体覆盖为真实行业口径。
        risk_metrics: dict[str, Any] = {}

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


def apply_near_substitute_warnings(
    strategies: list[dict[str, Any]],
    correlation_matrix: dict[tuple[str, str], float | None],
) -> list[dict[str, Any]]:
    """round25 R41-a: 近替代品冗余控制——独立冗余控制层，**无条件执行**。

    背景（R25 §2.4 实证）：`near_substitute_pairs` 原嵌套在 `enforce_max_correlation`
    内部，而后者只在 `if corr_matrix:` 时调用（strategy_design）→ 盘后/非交易窗口
    corr_matrix 为空 → 近替代品检测整体跳过（「芯片+半导体设备」「港股创新药+港股通
    创新药」同主题双入选无告警）。设计意图是「独立于 K 线相关系数、降级盲（r=None）
    也能识别」，却被门控在「必须有 corr_matrix」的调用里——最该在盘后工作的控制恰好
    在盘后被关掉。

    本函数：对每套方案的 non-CASH 两两跑文本/主题族检测（无 I/O，r 缺失
    （无价格序列/降级）→ 标 `unevaluated`；r 可算 → 标 `near_substitute` + correlation。
    结果并入 `risk_metrics.correlation_warnings`。调用方（strategy_design）**始终**调用。

    副作用（调用方须知）：R48 起本函数会**就地修改每套方案的 `s["allocations"]`**——
    通过 `_merge_substitute_family` 把同族近替代品合并留一（移除被合并标的、权重并入保留方）。
    因为结果是排序后的最终持仓（直接流向 API `etfs`），就地改入参是设计意图；
    测试构造共享 dict 引用的分配列表时须 `copy.deepcopy` 隔离，避免污染外部引用。
    """
    for s in strategies:
        allocs = [a for a in s.get("allocations", []) if a.get("symbol") not in (None, "CASH")]
        if len(allocs) < 2:
            continue
        warnings: list[dict[str, Any]] = []
        for np in near_substitute_pairs(allocs):
            sa, sb = np["pair"]
            r = correlation_matrix.get((sa, sb))
            if r is None:
                r = correlation_matrix.get((sb, sa))
            entry = dict(np)
            if r is None:
                entry["correlation"] = None
                entry["type"] = "unevaluated"
                entry["note"] = (
                    f"同主题近替代品（{np['family']}族）但相关系数缺失（无价格序列/降级），"
                    "冗余风险未量化——待交易时段复算"
                )
            else:
                entry["correlation"] = round(float(r), 3)
            warnings.append(entry)
        if warnings:
            s.setdefault("risk_metrics", {})
            s["risk_metrics"]["correlation_warnings"] = (
                s["risk_metrics"].get("correlation_warnings", []) + warnings
            )
        # round27 R48 (R41-c): 同族近替代品合并留一——在告警检测之后执行（三型统一，
        # 进攻型不豁免）。合并后把对应 near_substitute 告警升级为「已合并」标注。
        merges = _merge_substitute_family(s.get("allocations", []))
        _merged_families = {m["family"] for m in merges}
        for w in warnings:
            if w.get("family") in _merged_families:
                w["status"] = "merged"
                w["note"] = (w.get("note") or "") + "（已合并留一）"
        if merges:
            s.setdefault("risk_metrics", {})
            s["risk_metrics"]["merged_substitutes"] = (
                s["risk_metrics"].get("merged_substitutes", []) + merges
            )
    return strategies


def enforce_max_correlation(
    strategies: list[dict[str, Any]],
    correlation_matrix: dict[tuple[str, str], float | None],
    threshold: float = ENGINE_CONFIG.corr_cap,
    max_combined_weight: float = ENGINE_CONFIG.corr_combined_weight_cap,
) -> list[dict[str, Any]]:
    """P1-1 (round20) + round24 R2/R24⑤: 方案内高相关对（r >= threshold）合计权重不得超 max_combined_weight。

    纯函数，无 I/O。数据源为 engine/correlation.py 的 correlation_matrix（由 strategy_design
    用真实 K 线闭源计算，不在此处获取）。对每套方案的两两非 CASH 持仓：若 r >= threshold 且
    合计权重超标，则削减低因子分一方（降到「合计 = 阈值」，下限 MIN_WEIGHT），被削减
    权重按其余标的比例回补（保持 Σ=1），并在 risk_metrics.correlation_warnings 标注。

    round24 R2/R24⑤ 修正：强制锚（MANDATORY_CODES，沪深300/中证A500/黄金/国债）永不被关联度
    削减击穿 ≥5% 地板——allocate 内已有的 ≥5% 后处理地板会被本函数（后于 allocate 运行）击穿，
    故此处必须继承豁免：
      · 双方强制锚 → 仅标注，不削减（避免 A500/300 互削到 1% 违反 M7）；
      · 单方强制锚 → 强制锚永作 keep 方（不被削减），削非强制一方；
      · over-block 中若 keep 为强制锚 → 不进一步削减（仅标注，诚实暴露约束部分未达）。
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
                a_mand = sa in MANDATORY_CODES
                b_mand = sb in MANDATORY_CODES
                if a_mand and b_mand:
                    # 双方强制锚：不可削减任一，仅标注豁免（R2，防止 A500/300 互削击穿 5% 地板）
                    warnings.append({
                        "pair": [sa, sb],
                        "correlation": round(float(r), 3),
                        "combined_weight": round(wa + wb, 4),
                        "reduced_symbol": None,
                        "note": "双方均为强制锚（沪深300/中证A500/黄金/国债），关联度超阈但按豁免不削减",
                    })
                    continue
                # 确定削减方：强制锚永不作削减目标；否则削低因子分一方。
                if a_mand:
                    low, high = b, a          # high=强制锚（keep），削 low
                elif b_mand:
                    low, high = a, b
                else:
                    fa = a.get("factor_score", 0.0) or 0.0
                    fb = b.get("factor_score", 0.0) or 0.0
                    low, high = (a, b) if fa <= fb else (b, a)
                high_mand = high.get("symbol") in MANDATORY_CODES
                # 削 low 使「合计 = 阈值」（low 下限 MIN_WEIGHT；keep 方若为强制锚地板 0.05）
                target_low = max(MIN_WEIGHT, max_combined_weight - high.get("weight", 0.0))
                cut = max(0.0, low.get("weight", 0.0) - target_low)
                if cut <= 1e-9:
                    continue
                low["weight"] = round(target_low, 4)
                reduced_total += cut
                reduced_syms.add(low.get("symbol"))
                # low 触底后仍超标 → 削 high 补足；但 high 为强制锚时不可削，仅标注诚实暴露
                if target_low == MIN_WEIGHT and not high_mand:
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
                    "note": (
                        "高相关对合计权重超阈值，已削减低因子分标的（关联度提示，强制锚豁免不削减）"
                        if not high_mand else
                        "高相关对合计权重超阈，非强制方已削至下限；强制锚方受限未进一步削减"
                    ),
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

        # round25 R41-a: 近替代品检测已从本函数移出为独立层 `apply_near_substitute_warnings`
        #（strategy_design 无条件调用）——本函数仅保留 K 线相关系数相关控制：
        # 高相关削减 + 组合级分散约束（后者依赖 corr_matrix，天然随本函数门控）。
        if allocs:
            # 组合级分散约束（平均 pairwise r 过高且标的够多）
            conc = portfolio_concentration_check(allocs, correlation_matrix)
            if conc:
                warnings.append(conc)
        if warnings:
            s.setdefault("risk_metrics", {})
            s["risk_metrics"]["correlation_warnings"] = warnings
    # round24 R2: 强制锚地板安全网——任一强制锚（沪深300/中证A500/黄金/国债）权重
    # 不得低于 MANDATORY_FLOOR，杜绝关联度控制（或任何上游路径）击穿 M7「核心单只 ≥5%」。
    # allocate 后处理已保证该地板，此处为防御性兜底（正常为 no-op，不改变 Σ）。
    for s in strategies:
        for a in s.get("allocations", []):
            if a.get("symbol") in MANDATORY_CODES and a.get("weight", 0.0) < MANDATORY_FLOOR - 1e-9:
                a["weight"] = MANDATORY_FLOOR
    return strategies


def check_structure_reasonableness(
    strategies: list[dict[str, Any]],
    correlation_medians: dict[str, float | None] | None = None,
    cross_profile_only: bool = False,
) -> list[dict[str, Any]]:
    """P2-5 (round20) + round22 INV-3/4/5/6: 方案结构合理性检查。

    纯函数，无 I/O。

    逐方案（cross_profile_only=False 时）：
      - 防御层含综合信号明显负面（factor_score <= -0.5）的标的 → rationale 追加提示；
      - 防御层标的 median_r >= 0.35 却称「避险/低相关」→ 追加高相关提示；
      - 进攻型现金 > 20% → structure_warning；
      - round22 INV-4: 核心层高 beta 成长宽基占比 > core_growth_cap → structure_warning。

    cross_profile_only=True（或输入含全部三方案）：
      - round22 INV-3: 卫星数单调（防御<平衡<进攻）、防御数反向（防御≥平衡≥进攻）；
      - round22 INV-5: 总标的数单调（防御<平衡<进攻）；
      - round22 INV-6: 进攻型 现金 >0.10（bear >0.15）/ 防御权重 >0.05 → structure_warning。

    返回原策略列表（就地修正 rationale / 写入 risk_metrics.structure_warnings）。
    """
    correlation_medians = correlation_medians or {}
    _profiles = {"defensive", "balanced", "aggressive"}
    _have_all = _profiles <= {s.get("id") or s.get("risk_profile") for s in strategies}

    if not cross_profile_only:
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
                    if med is not None and med >= ENGINE_CONFIG.defensive_wording_median_r and ("避险" in rat or "低相关" in rat):
                        note = f"【结构提示：该防御层标的与组合 median r={med:.2f} 偏高，非低相关对冲资产】"
                        a["selection_rationale"] = rat + note
                        warnings.append({"type": "defense_high_median_r", "symbol": sym, "median_r": med})
            # P2-5-C: 进攻型现金 <= 20%
            if sid == "aggressive":
                non_cash = sum(a.get("weight", 0.0) for a in allocs if a.get("symbol") != "CASH")
                cash = round(1.0 - non_cash, 4)
                if cash > 0.20 + 1e-9:
                    warnings.append({"type": "aggressive_cash_over_20pct", "cash": cash})
            # round22 INV-4: 核心层成长宽基占比上限（占核心预算）
            _cap = (
                STRATEGY_META.get(sid, {}).get("core_growth_cap", ENGINE_CONFIG.core_growth_cap_fallback)
                if sid else ENGINE_CONFIG.core_growth_cap_fallback
            )
            _core = [a for a in allocs if a.get("layer") == "core" and a.get("symbol") != "CASH"]
            _core_w = sum(a.get("weight", 0.0) or 0.0 for a in _core)
            if _core_w > 0:
                _growth_w = sum(
                    a.get("weight", 0.0) or 0.0 for a in _core if _is_growth_wide_basis(a)
                )
                if _growth_w > _core_w * _cap + 1e-9:
                    warnings.append({
                        "type": "core_growth_exceeds_cap",
                        "profile": sid,
                        "growth_weight": round(_growth_w, 4),
                        "core_weight": round(_core_w, 4),
                        "cap": _cap,
                    })
            if warnings:
                s.setdefault("risk_metrics", {})
                s["risk_metrics"].setdefault("structure_warnings", [])
                s["risk_metrics"]["structure_warnings"].extend(warnings)

    # round22 INV-3/5/6 cross-profile（仅当三方案齐全时校验；单方案调用不做跨方案比较）
    if _have_all:
        _by = {s.get("id"): s for s in strategies}
        _d, _b, _a = _by.get("defensive"), _by.get("balanced"), _by.get("aggressive")

        def _layer_count(s, layer):
            return sum(
                1 for a in s.get("allocations", [])
                if a.get("layer") == layer and a.get("symbol") != "CASH"
            )

        def _total_count(s):
            return sum(1 for a in s.get("allocations", []) if a.get("symbol") != "CASH")

        _xwarnings: list[dict[str, Any]] = []
        # INV-3: 卫星数单调 防御<平衡<进攻
        _sat = {p: _layer_count(_by[p], "satellite") for p in ("defensive", "balanced", "aggressive")}
        if not (_sat["defensive"] < _sat["balanced"] < _sat["aggressive"]):
            _xwarnings.append({"type": "inv3_satellite_not_monotonic",
                               "satellite_counts": _sat})
        # INV-3: 防御数反向 防御>=平衡>=进攻
        _def = {p: _layer_count(_by[p], "defense") for p in ("defensive", "balanced", "aggressive")}
        if not (_def["defensive"] >= _def["balanced"] >= _def["aggressive"]):
            _xwarnings.append({"type": "inv3_defense_not_reverse_monotonic",
                               "defense_counts": _def})
        # INV-5: 总标的数单调 防御<平衡<进攻
        _tot = {p: _total_count(_by[p]) for p in ("defensive", "balanced", "aggressive")}
        if not (_tot["defensive"] < _tot["balanced"] < _tot["aggressive"]):
            _xwarnings.append({"type": "inv5_total_not_monotonic",
                               "total_counts": _tot})
        # INV-6: 进攻压舱——现金 <=0.10（bear <=0.15）、防御权重 <=0.05
        if _a is None:
            logger.warning("[allocation] INV-3/5/6: aggressive 方案缺失，跳过 INV-6 校验")
        else:
            _a_allocs = _a.get("allocations", [])
            _a_non_cash = sum(a.get("weight", 0.0) for a in _a_allocs if a.get("symbol") != "CASH")
            _a_cash = round(1.0 - _a_non_cash, 4)
            _a_def_w = sum(a.get("weight", 0.0) for a in _a_allocs if a.get("layer") == "defense")
            if _a_cash > 0.10 + 1e-9:
                _xwarnings.append({"type": "inv6_aggressive_cash_over", "cash": _a_cash,
                                   "clamp": 0.10})
            if _a_def_w > 0.05 + 1e-9:
                _xwarnings.append({"type": "inv6_aggressive_defense_over", "defense_weight": _a_def_w,
                                   "clamp": 0.05})
            if _xwarnings:
                _a.setdefault("risk_metrics", {})
                _a["risk_metrics"].setdefault("structure_warnings", [])
                _a["risk_metrics"]["structure_warnings"].extend(_xwarnings)
                logger.warning(
                    "[allocation] INV-3/5/6 cross-profile violations: %s",
                    [w["type"] for w in _xwarnings],
                )
    return strategies

