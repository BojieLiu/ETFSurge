"""因子状态判定单源（round35 B1-C3，docs/round35-architecture-review.md §13.5-C3）。

此前 MIN_TRADING_DAYS/STATIC_FACTOR_CODES/MARKET_LEVEL_FACTOR_CODES/_status_of 等
权威口径定义在 routers/factors.py（表现层），services/strategy_design 反向 import
routers 常量——层级倒置（C3：services→routers 常量倒置）。本模块把「因子状态判定」
这一纯领域逻辑下沉到 factors 包；routers/factors.py 头部 re-export 保持既有调用点
（含外部 `from app.routers.factors import ...`）零改动。

纯常量 + 纯判定函数，无 I/O；registry 仅读内存属性（_data_source_gaps /
_constant_factor_codes），不触发计算。
"""

from __future__ import annotations

from .factor_registry import ET_SPECIFIC_GAP_CODES, registry

# F25② (round23 §8): IC 显著性判据业内对齐——替换旧 `MIN_IC_SAMPLES=30`（刷新次数
# 冒充交易日，开机 1h 即跨过 →「有效 16」无统计含义）。
# - MIN_OBSERVABLE_DAYS=60: 可观察下限（UI 标「积累中（可观察）」）
# - MIN_TRADING_DAYS=250: 有效门槛（约 1 年交易日，对齐业内 t≥2 所需样本量）
# - 且必须 t≥2（95% 置信）AND |IR|≥0.5 才标 valid（文档 F25 设计要点②）
MIN_OBSERVABLE_DAYS = 60
MIN_TRADING_DAYS = 250

# Z03: 静态政策标识因子（不计算 IC，status='static'）
STATIC_FACTOR_CODES = {
    "china.policy.five_year_plan",
    "china.policy.strategic_emerging",
    "china.policy.dual_circulation",
}

# P1-10 (round9 §6.5.1-C): 市场级因子——注入的是全市场单一值（sentiment_index/涨跌家数比/
# 全市场新闻）→ 截面恒等（std=0 → IC 不可计算）→ 旧实现标 no_data 误导。
# 设计缺陷：宏观/市场级数据不能作为「每只 ETF 打分」的截面因子。
# 处置：移出截面因子池——不参与截面 IC 判定（参照 static 政策因子），仅作 regime/
# 组合层输入；因子页 reason 明示「市场级因子不参与截面 IC」；待 ETF 级舆情/板块级
# 情绪数据源接入后恢复截面计算。
MARKET_LEVEL_FACTOR_CODES = {
    "sentiment.panic_greed_diff",
    "sentiment.stock_divergence",
    "sentiment.news_direction",
    # round13 §3.1 P2: 宏观环境因子——全市场单一值（M2/PMI/LPR/GDP/两融），截面恒等，
    # 不参与截面 IC，仅作市态/组合层输入（与 sentiment 市场级因子同处置）
    "macro.m2_trend",
    "macro.pmi_level",
    "macro.lpr_direction",
    "macro.gdp_trend",
    "macro.margin_leverage_trend",
}

# F19 R70: code → 缺失字段名映射（泛化：ln_mcap 等非 etf_specific 因子也有缺口标注）
GAP_FIELD_MAP = {
    "style.size.ln_mcap": "fund_scale/total_mv",
    "style.size.ln_float_mcap": "float_mv",
}


def status_of(
    code: str,
    samples: int,
    t_stat: float | None,
    ir: float | None,
    ic_val: float | None = None,
) -> tuple[str, str]:
    """Z03: 权威状态 + 原因说明（/active 与 /model 与设计 fdq 共用）。

    F25② (round23 §8): 显著性判据业内对齐——由「|IC|≥threshold 且 samples≥30」改为
    「交易日数 + t/IR」三档：
    - samples < 60            → no_data（积累中）
    - 60 ≤ samples < 250      → no_data（积累中（可观察））
    - samples ≥ 250 且 t≥2 且 |IR|≥0.5 → valid（统计显著）
    - samples ≥ 250 但 t<2 或 |IR|<0.5 → warn（有样本但统计不显著）

    旧 `MIN_IC_SAMPLES=30`（刷新次数冒充交易日）已废弃——18 天自相关刷新数据
    连 t≥2 的零头都不够，按任何标准都不可能有「有效因子」（文档 §2.5 结论）。
    """
    if code in STATIC_FACTOR_CODES:
        return "static", "静态政策标识因子，不计算 IC"
    if code in MARKET_LEVEL_FACTOR_CODES:
        # P1-10: 市场级因子（全市场单一值/市态级降级）——截面恒等，移出截面 IC 池
        return "static", "市场级因子（全市场单一值），不参与截面 IC，仅作市态/组合层输入"
    if samples <= 0:
        # F3-4 步骤D + F19 R70: 区分「数据源未接入（缺字段）」与「IC 未累积（样本不足）」
        gaps = getattr(registry, "_data_source_gaps", {}) or {}
        missing = gaps.get(code, [])
        if missing:
            field = GAP_FIELD_MAP.get(code, ET_SPECIFIC_GAP_CODES.get(code, "必要字段"))
            return "no_data", f"数据源未接入（{len(missing)} 只样本缺 {field}）"
        # O20: 常量因子独立标注——截面输出全 0/常量 → 无区分度，非样本不足
        constant_gaps: set[str] = set(getattr(registry, "_constant_factor_codes", set()) or set())
        if code in constant_gaps:
            return "no_data", "截面无差异（常量输出），检查底层数据"
        return "no_data", "IC 未累积（0 个交易日）"
    if samples < MIN_OBSERVABLE_DAYS:
        return "no_data", f"IC 积累中（{samples}/{MIN_TRADING_DAYS} 交易日，未达可观察下限 {MIN_OBSERVABLE_DAYS}）"
    if samples < MIN_TRADING_DAYS:
        return "no_data", f"IC 积累中（{samples}/{MIN_TRADING_DAYS} 交易日，可观察）"
    # samples ≥ 250：显著性判定（t≥2 且 |IR|≥0.5）
    if t_stat is None or ir is None:
        return "no_data", f"IC 序列不可用（{samples} 交易日但无 t/IR 统计）"
    if abs(ir) >= 0.5 and t_stat >= 2.0:
        return "valid", f"统计显著：t={t_stat:.2f}，IR={ir:.2f}，样本 {samples} 交易日（≥{MIN_TRADING_DAYS}）"
    return "warn", (
        f"有样本但统计不显著：t={t_stat:.2f}，|IR|={abs(ir):.2f}"
    )


# 向下兼容别名（历史调用点 `_status_of`；strategy_design 已改用公开名 status_of）
_status_of = status_of
