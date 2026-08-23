"""
rationale.py — 基于因子分的入选理由生成（纯函数，P2 改进 #5：模板多样化）
"""
from __future__ import annotations

import hashlib

# ── 层角色短语池（P2 改进 #5：模板多样化） ────────────────────────────
# F1-8/§9.7 R3: 短语池按标的风格（_style_probe）选择，不再按 layer 固定套用。
# 「压舱石/低波动」措辞只属于低波宽基池；科创类指数强制归入高波成长池。
_CORE_PHRASES = [
    lambda n: f"作为组合压舱石，低波动宽基{n}",
    lambda n: f"核心层选择——{n}，兼具流动性与分散性",
    lambda n: f"作为核心宽基{n}，提供市场β收益",
    # O16 (round8 §7 §5.1B): 「大盘价值代表性」删除——中证500（中盘）等宽基被
    # 套"大盘价值"语义错误；改中性「宽基底仓」描述。
    lambda n: f"{n}核心层配置，作为宽基底仓",
    lambda n: f"以{n}作为组合压舱石，低波动宽基",
]

_HIGH_GROWTH_PHRASES = [
    lambda n: f"高弹性成长指数{n}，波动较大但进攻性强",
    lambda n: f"成长风格{n}，高 Beta 品种适合进攻配置",
    # O16 (round8): 文案含「高弹性」——core 层过滤"卫星"句后此句仍体现高波成长
    # 属性（round7 验收: 科创类 core 文案必须含 高弹性/高Beta/进攻 等关键词）。
    lambda n: f"高弹性主题{n}，波动与收益空间同步放大",
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
    if any(t in combo for t in ("红利", "低波", "价值", "上证50", "上证180", "沪深300",
                                "中证A", "中证500", "中证800", "深证100", "深证50",
                                "创业板", "MSCI", "A50", "A100", "A500")):
        return "low_vol_wide"
    return "theme_satellite"


def _layer_phrase(layer: str, asset_name: str, sym: str = "", style: str = "",
                  correlation_median: float | None = None) -> str:
    """从风格短语池中选择一条完整描述，用 symbol hash 保证稳定性。

    F1-8: 短语生成完整句式（不再以「在方案中」开头），调用方统一以
    「在{label}方案中{layer_desc}」拼装，杜绝「在方案中在方案中」重复。
    O16 (round8 §7 §5.1B): core/defense 层禁用「卫星仓位/高弹性」语义短语——
    短语池中过滤含"卫星"句，避免 core 宽基被误配卫星语义（562000 曾命中）。
    round19 P1-③ (2026-08-12): 「低相关性」措辞条件化——防御层短语池中
    「N与权益低相关」「低相关性N」两句仅在 correlation_median < 0.3 时允许；
    None（相关矩阵不可用）或中位数 ≥0.3 时回退中性防御文案（杜绝无数据
    冒充低相关——对照反假完成 §2）。
    """
    pool = _STYLE_TO_POOL.get(style) or {
        "core": _CORE_PHRASES, "satellite": _THEME_SATELLITE_PHRASES,
        "defense": _DEFENSE_PHRASES,
    }.get(layer, _CORE_PHRASES)
    if layer in ("core", "defense", "defence"):
        # core/defense 是底仓角色：过滤掉"卫星"语义句（含高弹性偏卫星表述）
        filtered = [fn for fn in pool if "卫星" not in fn(asset_name)]
        if filtered:
            pool = filtered
        else:
            pool = _CORE_PHRASES if layer != "defense" else _DEFENSE_PHRASES
    # round19 P1-③: 低相关措辞守卫——仅真实低相关（中位数 < 0.3）才保留
    if correlation_median is None or correlation_median >= 0.3:
        pool = [fn for fn in pool if "低相关" not in fn(asset_name)]
        if not pool:
            pool = _DEFENSE_PHRASES
    else:
        # P1-2 (round20): median<0.3 → 强制从低相关措辞池中选（覆盖 md5 随机选取），
        # 保证低相关标的的 rationale 必含「低相关」措辞（确定性，非概率性出现）。
        _low_pool = [fn for fn in pool if "低相关" in fn(asset_name)]
        if _low_pool:
            pool = _low_pool
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
    industry_confidence: float = 0.85,
    rank_info: dict | None = None,
    correlation_median: float | None = None,
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
        industry_confidence: 行业分类置信度（O23: <0.7 时保守描述，
            不输出可能误导的具体行业语义）
        rank_info: O24 归因链——{rank, total_candidates, dominant_factor}：
            层内候选池排名 N/M + 主驱动因子，回答「为什么选中它而非同类」
        correlation_median: round19 P1-③ 该标的与组合其它标的中位数 r
            （None = 相关矩阵不可用 → 「低相关性」措辞禁用，回退中性文案）

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
        # round19 P1-③: 黄金「与权益低相关」不再硬编码声称——低相关措辞统一交给
        # _layer_phrase 条件逻辑（该标的中位数 r < 0.3 才允许出现）
        parts.append(f"{asset_name} — 贵金属避险资产")
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
        # O23 (round7 §7 P23): 行业标签可信度校验——
        # ① 名称/指数交叉校验：名称命中宽基语义关键词而 industry 被误标具体行业
        #   （或 unknown）时，以「宽基指数」为准（562950 类误归不进入文案）；
        # ② 分类置信度 <0.7 时保守描述（不输出可能误导的具体行业语义）。
        _WIDE_BASIS_HINTS = (
            "沪深300", "中证A500", "中证A50", "中证A100", "上证50", "上证180",
            "深证100", "中证100", "中证800", "中证500", "科创50", "创业板",
            "MSCI", "A50", "A100", "A500",
        )
        name_and_index = f"{asset_name}{meta.get('tracked_index') or meta.get('trackedIndex') or ''}"
        if any(k in name_and_index for k in _WIDE_BASIS_HINTS):
            parts.append(f"{asset_name} — 宽基指数方向")
        elif industry_confidence < 0.7:
            parts.append(f"{asset_name} — 主题方向（分类置信度低，标签待校准）")
        else:
            parts.append(f"{asset_name} — {ind}方向")

    # 2. 技术面（使用 factor_scores 中实际存在的 RSI / MACD / KDJ 因子）
    # R6-F4 (round6 §十 R6-05 + §十八-7): rsi_14 自 F1-5 起保留 raw 0-100 值——
    # 按 0-100 真实值域做 30/70 阈值判断；兼容旧数据 _raw 键。MACD 用 _raw 保留的
    # 真实 DIF（zscore 值尺度失真）。
    # round14 P2-X: RSI+MACD 合并为一句（删低信息量的「技术面综合评分」绝对值句）
    rsi = factor_scores.get("technical.rsi.rsi_14_raw") or factor_scores.get("technical.rsi.rsi_14")
    rsi_desc = None
    if rsi is not None and 0 < rsi <= 100:
        if rsi < 30:
            rsi_desc = f"RSI {rsi:.1f} 超卖"
        elif rsi > 70:
            rsi_desc = f"RSI {rsi:.1f} 超买"
        else:
            rsi_desc = f"RSI {rsi:.1f} 中性"
    elif rsi is not None and rsi > 0:
        # 异常值域（不应出现）：仅展示数值
        rsi_desc = f"RSI {rsi:.1f}"

    macd_raw = factor_scores.get("technical.macd.macd_raw")
    macd = macd_raw if macd_raw is not None else factor_scores.get("technical.macd.macd")
    macd_desc = None
    if macd is not None and macd >= 0.001:
        macd_desc = "MACD 多头"
    elif macd is not None and macd <= -0.001:
        macd_desc = "MACD 空头"

    tech_bits = [x for x in (rsi_desc, macd_desc) if x]
    if tech_bits:
        parts.append("、".join(tech_bits))

    # 3. 复合因子分——round14 P2-X: 删「技术面综合评分 X.XXX」（低信息量绝对值），
    # 保留动量/估值核心驱动因子
    momentum = factor_scores.get("momentum")
    if momentum is not None and momentum != 0:
        parts.append(f"动量因子 {momentum:+.3f}")
    valuation = factor_scores.get("valuation")
    if valuation is not None and valuation != 0:
        parts.append(f"估值因子 {valuation:+.3f}")

    # 4. 综合信号 — F1-8/§9.7 R5: 改用三因子加权聚合（0.4技术+0.4估值+0.2动量），
    # 含「双弱不判多」硬约束与单因子极端值封顶（纯函数，无 I/O）。
    try:
        from .signal import composite_signal  # round35 B1-F1b: 下沉后同包引用
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

    # 5. 市场状态 —— round14 P2-X: 删除「市场震荡」等重复市态句（市态已在报告层级
    # 与方案 header 体现，单条理由内重复冗余；保留层角色与归因链回答「为什么选它」）

    # 6. 层角色（F1-8/§9.7 R3: 按标的风格选池，完整句式一次生成，杜绝重复拼接）
    sl = {"defensive": "防御型", "balanced": "平衡型", "aggressive": "进攻型"}
    label = sl.get(strategy, strategy)
    style = _style_probe(meta)
    # round19 P1-③: 低相关措辞条件化（真实中位数 < 0.3 才允许「低相关性」）
    layer_desc = _layer_phrase(layer, asset_name, code, style, correlation_median)
    parts.append(f"在{label}方案中{layer_desc}")

    # 7. 归因链（O24, round7 §7 P24）——「为什么选中它而非同类」：
    # 层内候选池排名 N/M + 主驱动因子。回答因子分在候选池的位次与主导因子。
    if rank_info:
        rank = rank_info.get("rank")
        total = rank_info.get("total_candidates")
        dom = rank_info.get("dominant_factor")
        if rank is not None and total:
            parts.append(f"同类候选池排名 {rank}/{total}")
        if dom:
            parts.append(f"主驱动因子：{dom}")

    return "；".join(parts) if parts else f"{asset_name} — 基于因子评分入选"
