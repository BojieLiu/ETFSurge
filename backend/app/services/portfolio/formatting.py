"""Factor formatting helpers — split from portfolio_service (Batch 1)."""

import logging

logger = logging.getLogger(__name__)

FACTOR_LABELS: dict[str, str] = {
    # 规模/风格
    "style.size.ln_mcap": "对数市值",
    "style.size.ln_float_mcap": "对数流通市值",
    # 技术面
    "technical.ma.sma_5": "MA5",
    "technical.ma.sma_10": "MA10",
    "technical.ma.sma_20": "MA20",
    "technical.ma.sma_60": "MA60",
    "technical.rsi.rsi_14": "RSI(14)",
    "technical.macd.macd": "MACD",
    "technical.bollinger.bandwidth": "布林带宽",
    "technical.volume.vol_ratio": "量比",
    "technical.volume.vwap": "VWAP",
    "technical.atr.atr_14": "ATR(14)",
    "technical.kdj.k_value": "KDJ.K",
    "technical.kdj.d_value": "KDJ.D",
    "technical.kdj.j_value": "KDJ.J",
    "technical.signal.overall": "综合信号",
    # ETF 基本面
    "etf.amount_stability": "成交额稳定性",
    "etf.change_pct": "涨跌幅",
    "etf.return_1m": "近1月收益",
    "etf.return_3m": "近3月收益",
    "etf.price": "价格",
    "etf.premium_discount": "溢价率",
    "etf.tracking_error": "跟踪误差",
    "etf.shares_change": "份额变化",
    "etf.industry_diversification": "行业分散度",
    "etf.institutional_holdings_change": "机构持仓变化",
    # 情绪
    "sentiment.panic_greed_diff": "恐慌贪婪差",
    "sentiment.stock_divergence": "个股背离",
    "sentiment.news_heat": "新闻热度",
    "sentiment.news_direction": "新闻方向",
    # 政策
    "china.policy.five_year_plan": "十五五规划",
    "china.policy.strategic_emerging": "战略性新兴",
    "china.policy.dual_circulation": "双循环",
}

_RSI_HINT = (
    ("超买", lambda v: v >= 70),
    ("超卖", lambda v: v <= 30),
)

_KDJ_HINT = (
    ("超买区", lambda v: v >= 80),
    ("超卖区", lambda v: v <= 20),
)

_CONFIDENCE_ZH = {"high": "高", "medium": "中", "low": "低"}


def _factor_hint(code: str, value: float) -> str:
    """按因子键与值域给方向/含义解读；无规则返回空串。"""
    if code == "technical.rsi.rsi_14":
        for label, cond in _RSI_HINT:
            if cond(value):
                return f"（{label}）"
        return "（中性）"
    if code.startswith("technical.kdj."):
        # round18 P0-3: 值域按原始 0-100（>80 超买 / <20 超卖）；
        # 负值（历史归一化兜底）仍判超卖区，但正常路径已不产出归一化负值。
        for label, cond in _KDJ_HINT:
            if cond(value):
                return f"（{label}）"
        return ""
    if code == "technical.signal.overall":
        if value > 0:
            return "（偏多）"
        if value < 0:
            return "（偏空）"
    if code.startswith("sentiment."):
        return "（情绪因子，正值偏多）" if value > 0 else "（情绪因子，负值偏空）" if value < 0 else ""
    return ""


def _factor_strength_band(value: float) -> str:
    """R21 (round24): 通用因子分无量纲 → 强度分档，投资者可解读（偏强/偏弱 等）。

    原始因子分（如「政策规划因子 +8.97」「战略新兴 +8.14」）量纲不统一、裸数值
    不可解读。多数因子分为方向性标准化值，按符号+量级分档给出相对强弱提示
    （非精确百分位）。
    """
    a = abs(value)
    if value > 0:
        if a >= 3:
            return "强"
        if a >= 0.5:
            return "偏强"
        return "中性偏强"
    if value < 0:
        if a >= 3:
            return "弱"
        if a >= 0.5:
            return "偏弱"
        return "中性偏弱"
    return "中性"


def format_factor_summary(real_fs: dict[str, float], top_n: int = 3, tech_ind: dict | None = None) -> str:
    """F11: 因子分 → 中文解读字符串（保持 factor_summary 字符串契约不变）。

    round10 P2-I: 渲染前过滤中性兜底默认值（RSI/KDJ=50、vol_ratio=1、|v|≈0）——
    无任何真实因子的标的渲染为空串（调用方显示「数据不可用」），不再把 50.00
    「（中性）」伪装成真实计算结果。

    round18 P0-3 (2026-08-12): KDJ 显示对齐指标源原始值——factor_scores 里的
    technical.kdj.* 是归一化 zscore（可负/异常，如 -3.46），而 /market/indicators
    返回原始 KDJ（0-100）。传入 tech_ind（compute_all_indicators 产物，含
    kdj.{k,d,j} 原始值）时 KDJ 显示原始值；无原始值（或未传）时排除 KDJ 键，
    **禁止把归一化负值冒充原始 KDJ 展示**（负向：KDJ 负数 → 不出现在输出）。

    示例输入: {"technical.rsi.rsi_14": 39.53, "technical.kdj.d_value": -3.46}
    示例输出(tech_ind={"kdj":{"d": 84.77}}): "RSI(14) 39.53（中性）；KDJ.D 84.77"
    示例输出(无 tech_ind): "RSI(14) 39.53（中性）"
    """
    if not real_fs:
        return ""

    def _resolve(k: str, v):
        """round18 P0-3: KDJ 归一化键 → tech_ind 原始值；无原始值返回 None（排除）。"""
        if k.startswith("technical.kdj."):
            if isinstance(tech_ind, dict):
                kdj_raw = tech_ind.get("kdj") or {}
                part = k.rsplit(".", 1)[-1]  # 'k_value'/'d_value'/'j_value'
                raw = kdj_raw.get(part[0].replace("_value", "")) if part else None
                if isinstance(raw, (int, float)):
                    return float(raw)
            return None  # 无原始 KDJ → 排除该键，不显示归一化假值
        return v

    real_items = []
    for k, v in real_fs.items():
        if not isinstance(v, (int, float)):
            continue
        resolved = _resolve(k, v)
        if resolved is None:
            continue  # KDJ 无原始值 → 排除
        if not _factor_value_real(k, resolved):
            continue
        real_items.append((k, resolved))
    if not real_items:
        # P2-I: 全为兜底默认值 → 空串（调用方已 fallback「数据不可用」文案）
        return ""
    items = sorted(real_items, key=lambda x: -abs(x[1]))[:top_n]
    parts = []
    for k, v in items:
        label = FACTOR_LABELS.get(k, k)
        hint = _factor_hint(k, float(v))
        if hint:
            # 已有因子专属语义（RSI/KDJ/情绪等）→ 保留原样
            parts.append(f"{label} {v:.2f}{hint}")
        else:
            # R21: 无量纲通用因子 → 强度分档，避免裸数值（如 +8.97）不可解读
            band = _factor_strength_band(float(v))
            parts.append(f"{label} {v:.2f}（{band}）")
    return "；".join(parts)


def _normalize_confidence(value) -> str:
    """round24 R4: confidence 表示法统一为语义标签 high/medium/low。

    问题：规则路径输出裸数值（0.5/0.7）、LLM 路径输出 high/medium 标签，**同屏两种
    表示法混排**——前端 `confidenceLabel()` 对 0.7 回落显示「0.7」、class 变
    `conf-0.7` 无样式，且 0.7 实为「中等」却易被读作「高置信」（round24 §2.2 残留 1）。

    映射（契约 api-contracts/portfolio/strategy-check-v2.md §3.1-3）：
      数值 ≥0.8 → high、≥0.5 → medium、<0.5 → low；
      字符串 high/medium/low（不区分大小写）、中文 高/中/低（含「高置信」等前缀）同映射；
      数字字符串（"0.85"）按数值处理；无法识别（None/空/乱值）→ medium（不冒充 high）。
    """
    if isinstance(value, bool):
        return "medium"
    if isinstance(value, (int, float)):
        if value >= 0.8:
            return "high"
        return "medium" if value >= 0.5 else "low"
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return "medium"
        try:
            return _normalize_confidence(float(s))
        except ValueError:
            pass
        low = s.lower()
        for label in ("high", "medium", "low"):
            if low.startswith(label):
                return label
        if s.startswith("高"):
            return "high"
        if s.startswith("中"):
            return "medium"
        if s.startswith("低"):
            return "low"
    return "medium"


def _compute_confidence(filled_count: int, total_count: int) -> str:
    """FIX-10: 基于因子数据覆盖率计算置信度（不依赖 LLM source_confidence）。"""
    if total_count <= 0:
        return "low"
    ratio = filled_count / total_count
    if ratio > 0.8:
        return "high"
    elif ratio >= 0.5:
        return "medium"
    return "low"


def _factor_value_real(key: str, value: float) -> bool:
    """P1-15 (round9 §4.4-3): 判断因子值是否为真实值（非中性兑底默认值）。

    缺数据兑底默认值（factor_registry 对无历史/无数据的标的返回中性值）：
      - RSI / KDJ 恰为 50（技术指标中性）
      - vol_ratio 恰为 1（量比中性）
      - 其他因子恰为 0（ATR/MACD 等缺数据）
    这些值计入 filled 会造「因子数据 N/M 正常」假正常（#345: RSI(14)=50/KDJ=50 全兑底仍报 10/10）。
    """
    if not isinstance(value, (int, float)):
        return False
    key_l = (key or "").lower()
    if ("rsi" in key_l or "kdj" in key_l) and abs(value - 50.0) < 1e-9:
        return False
    if "vol_ratio" in key_l and abs(value - 1.0) < 1e-9:
        return False
    if abs(value) < 1e-9:
        return False
    return True


def _has_real_factor_values(fs: dict) -> bool:
    """P1-15/P0-F: 是否存在『足够』非中性兑底默认值的因子值。

    round10 P0-F：filled 判定不再用「任一真实因子」（size 静态因子会撑起
    “完整”），改为**技术因子覆盖率 ≥60%**（realtime 类 factor 有 ≥60% 真实
    值时该标才视为 filled）。技术因子的 key 以 `technical.` 前缀区分；
    纯静态因子（style.size.* 等）不再计入“已填充”。
    """
    if not isinstance(fs, dict) or not fs:
        return False
    tech = {k: v for k, v in fs.items() if str(k).startswith("technical.")}
    if not tech:
        # 没有任何技术因子（冷启动纯静态场景）→ 视为缺失
        return False
    real = sum(1 for k, v in tech.items() if _factor_value_real(k, v))
    return real / len(tech) >= 0.6
