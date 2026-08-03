"""
rationale.py — 基于因子分的入选理由生成（纯函数，P2 改进 #5：模板多样化）
"""
from __future__ import annotations

import hashlib
from typing import Any

# ── 层角色短语池（P2 改进 #5：模板多样化） ────────────────────────────
# F1-8/§9.7 R3: 短语池按标的风格（_style_probe）选择，不再按 layer 固定套用。
# 「压舱石/低波动」措辞只属于低波宽基池；科创类指数强制归入高波成长池。
_CORE_PHRASES = [
    lambda n: f"作为组合压舱石，低波动宽基{n}",
    lambda n: f"核心层选择——{n}，兼具流动性与分散性",
    lambda n: f"作为核心宽基{n}，提供市场β收益",
    lambda n: f"{n}核心层配置，大盘价值代表性",
    lambda n: f"以{n}作为组合压舱石，低波动宽基",
]

_HIGH_GROWTH_PHRASES = [
    lambda n: f"高弹性成长指数{n}，波动较大但进攻性强",
    lambda n: f"成长风格{n}，高 Beta 品种适合进攻配置",
    lambda n: f"主题弹性{n}，波动与收益空间同步放大",
    lambda n: f"高波动成长{n}，博取景气赛道超额收益",
    lambda n: f"科创成长{n}，弹性充足、适合卫星仓位",
]

_THEME_SATELLITE_PHRASES = [
    lambda n: f"主题卫星{n}，参与赛道轮动机会",
    lambda n: f"行业{n}作为弹性卫星，博取超额收益",
    lambda n: f"{n}卫星仓位，高弹性品种",
    lambda n: f"{n}作为卫星增强，聚焦高景气方向",
]

_DEFENSE_PHRASES = [
    lambda n: f"防御层{n}提供下行保护",
    lambda n: f"{n}与权益低相关，分散尾部风险",
    lambda n: f"避险资产{n}，降低组合波动",
    lambda n: f"{n}防御配置，对冲市场下行风险",
    lambda n: f"低相关性{n}，有效平衡组合波动",
]

# F1-8/§9.7 R3: 标的风格 → 短语池映射
_STYLE_TO_POOL = {
    "low_vol_wide": _CORE_PHRASES,
    "high_growth": _HIGH_GROWTH_PHRASES,
    "theme_satellite": _THEME_SATELLITE_PHRASES,
    "defensive": _DEFENSE_PHRASES,
}


def _style_probe(meta: dict | None = None) -> str:
    """F1-8/§9.7 R3: 标的风格探测（纯函数，无 I/O）。

    按 tracked_index / 名称归入 {low_vol_wide 低波宽基 / high_growth 高波成长 /
    theme_satellite 主题卫星 / defensive 防御资产} 四类。
    科创/半导体/芯片 类指数**强制**归入 high_growth——绝不落「压舱石/低波动」池。
    """
    meta = meta or {}
    name = meta.get("name", "") or ""
    tidx = meta.get("tracked_index", "") or ""
    combo = f"{tidx} {name}"
    if any(t in combo for t in ("科创", "半导体", "芯片", "人工智能", "AI")):
        return "high_growth"
    if any(t in combo for t in ("黄金", "白银", "国债", "债券", "货币", "商品",
                                "原油", "豆粕", "标普", "纳指", "日经")):
        return "defensive"
    if any(t in combo for t in ("红利", "低波", "价值", "上证50", "沪深300",
                                "中证A", "中证500", "中证800", "创业板")):
        return "low_vol_wide"
    return "theme_satellite"


def _layer_phrase(layer: str, asset_name: str, sym: str = "", style: str = "") -> str:
    """从风格短语池中选择一条完整描述，用 symbol hash 保证稳定性。

    F1-8: 短语生成完整句式（不再以「在方案中」开头），调用方统一以
    「在{label}方案中{layer_desc}」拼装，杜绝「在方案中在方案中」重复。
    """
    pool = _STYLE_TO_POOL.get(style) or {
        "core": _CORE_PHRASES, "satellite": _THEME_SATELLITE_PHRASES,
        "defense": _DEFENSE_PHRASES,
    }.get(layer, _CORE_PHRASES)
    idx = int(hashlib.md5(sym.encode()).hexdigest(), 16) % len(pool) if sym else 0
    return pool[idx](asset_name)


def build_rationale(
    code: str,
    layer: str,
    strategy: str,
    meta: dict | None = None,
    factor_scores: dict[str, float] | None = None,
    regime: str | None = None,
    industry: str | None = None,
) -> str:
    """
    为指定层级的 ETF 生成数据驱动的入选理由（纯函数）。

    使用 factor_scores 中实际存在的因子键，无占位符引用。

    Args:
        code: ETF 代码
        layer: core / satellite / defense
        strategy: defensive / balanced / aggressive
        meta: ETF 元数据（name, reason, industry 等）
        factor_scores: {factor_name: score} 因子分
        regime: 市场状态
        industry: 行业分类

    Returns:
        str: 中文入选理由
    """
    parts: list[str] = []
    meta = meta or {}
    factor_scores = factor_scores or {}
    asset_name = meta.get("name", code)

    # 1. 资产介绍与行业（使用实际存在的字段）
    if "沪深300" in asset_name:
        parts.append(f"{asset_name} — A股核心宽基，覆盖沪深两市龙头")
    elif "红利" in asset_name:
        parts.append(f"{asset_name} — 高股息低波动，适合底仓配置")
    elif "黄金" in asset_name:
        parts.append(f"{asset_name} — 贵金属避险资产，与权益低相关")
        # B1: 使用动量因子作为近期跌幅的代理指标
        momentum_val = factor_scores.get("momentum")
        if momentum_val is not None and momentum_val < -0.5:
            parts.append("近月承压（动量偏弱），短期避险功能受限但长期配置价值仍在")
        else:
            parts.append("用于对冲权益极端系统性风险和地缘政治风险")
    elif "国债" in asset_name:
        parts.append(f"{asset_name} — 利率债，货币宽松周期受益")
        # B2: 增加久期风险提示
        parts.append("久期较长，若稳增长政策加码利率反弹则承压")
    else:
        ind = industry or meta.get("industry") or "行业"
        parts.append(f"{asset_name} — {ind}方向")

    # 2. 技术面（使用 factor_scores 中实际存在的 RSI / MACD / KDJ 因子）
    # R6-F4 (round6 §十 R6-05 + §十八-7): rsi_14 自 F1-5 起保留 raw 0-100 值——
    # 按 0-100 真实值域做 30/70 阈值判断；兼容旧数据 _raw 键。MACD 用 _raw 保留的
    # 真实 DIF（zscore 值尺度失真）。
    rsi = factor_scores.get("technical.rsi.rsi_14_raw") or factor_scores.get("technical.rsi.rsi_14")
    if rsi is not None and 0 < rsi <= 100:
        if rsi < 30:
            parts.append(f"RSI {rsi:.1f} 超卖区域")
        elif rsi > 70:
            parts.append(f"RSI {rsi:.1f} 超买区域")
        else:
            parts.append(f"RSI {rsi:.1f} 中性区间")
    elif rsi is not None and rsi > 0:
        # 异常值域（不应出现）：仅展示数值
        parts.append(f"RSI {rsi:.1f}")

    macd_raw = factor_scores.get("technical.macd.macd_raw")
    macd = macd_raw if macd_raw is not None else factor_scores.get("technical.macd.macd")
    if macd is not None and macd >= 0.001:
        parts.append(f"MACD 为正 {macd:.4f}，多头趋势")
    elif macd is not None and macd <= -0.001:
        parts.append(f"MACD 为负，空头趋势")

    # 3. 复合因子分
    tech_score = factor_scores.get("technical")
    if tech_score is not None and tech_score != 0:
        parts.append(f"技术面综合评分 {tech_score:+.3f}")
    momentum = factor_scores.get("momentum")
    if momentum is not None and momentum != 0:
        parts.append(f"动量因子 {momentum:+.3f}")
    valuation = factor_scores.get("valuation")
    if valuation is not None and valuation != 0:
        parts.append(f"估值因子 {valuation:+.3f}")

    # 4. 综合信号 — F1-8/§9.7 R5: 改用三因子加权聚合（0.4技术+0.4估值+0.2动量），
    # 含「双弱不判多」硬约束与单因子极端值封顶（纯函数，无 I/O）。
    try:
        from ..analysis.signal import composite_signal
        _t = factor_scores.get("technical", 0.0) or 0.0
        _v = factor_scores.get("valuation", 0.0) or 0.0
        _m = factor_scores.get("momentum", 0.0) or 0.0
        if any((_t, _v, _m)):
            cs = composite_signal(_t, _v, _m)
            if cs["signal"] == "buy":
                parts.append(f"综合信号偏多（{cs['score']:+.2f}）")
            elif cs["signal"] == "sell":
                parts.append(f"综合信号偏空（{cs['score']:+.2f}）")
            else:
                parts.append(f"综合信号中性（{cs['score']:+.2f}）")
    except Exception:
        # 极端兜底：退回基于技术信号 overall 的旧判断
        signal = factor_scores.get("technical.signal.overall")
        if signal is not None:
            if signal > 0.2:
                parts.append("综合信号偏多")
            elif signal < -0.2:
                parts.append("综合信号偏空")
            else:
                parts.append("综合信号中性")

    # 5. 市场状态
    regime_desc = {
        "bull_strong": "当前市场强势",
        "bull_weakening": "牛市趋弱",
        "range_bound": "市场震荡",
        "correction": "市场回调中",
        "bear": "熊市环境",
        "defensive_rotate": "防御轮动阶段",
        "panic": "市场恐慌",
    }
    if regime and regime in regime_desc:
        parts.append(regime_desc[regime])

    # 6. 层角色（F1-8/§9.7 R3: 按标的风格选池，完整句式一次生成，杜绝重复拼接）
    sl = {"defensive": "防御型", "balanced": "平衡型", "aggressive": "进攻型"}
    label = sl.get(strategy, strategy)
    style = _style_probe(meta)
    layer_desc = _layer_phrase(layer, asset_name, code, style)
    parts.append(f"在{label}方案中{layer_desc}")

    return "；".join(parts) if parts else f"{asset_name} — 基于因子评分入选"
