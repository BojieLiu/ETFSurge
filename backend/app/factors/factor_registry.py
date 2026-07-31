"""
FactorRegistry: YAML-driven factor definitions with async computation engine.

Loads factor_definitions.yaml, manages 167+ factor definitions, and provides
async computation for 30 core factors (S1 scope).
"""
from __future__ import annotations

import math
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar
from pathlib import Path

import yaml
import pandas as pd
import numpy as np
import pandas_ta as ta

from ..factors.ic_tracker import ic_tracker
from ..services.source_registry import registry as _source_registry

logger = logging.getLogger(__name__)

# Z-score clipping bound: cap extreme Z-scores to [-5, 5] to prevent
# values like 16.22σ from distorting downstream allocation.
ZSCORE_CLIP_BOUND = 5.0

# Default YAML path relative to this file
_DEFAULT_YAML = Path(__file__).parent / "factor_definitions.yaml"


@dataclass
class FactorDefinition:
    """Standardized factor definition matching factor_definitions.yaml schema."""

    code: str
    name: str
    category: str
    subcategory: str = ""
    frequency: str = "daily"
    compute_fn: str = ""                     # Name of computation function
    dependencies: list[str] = field(default_factory=list)
    standardization: str = "zscore"          # zscore / rank / minmax / industry_neutral / none
    lookback_window: int = 1
    ic_threshold: float = 0.02
    ic_ir_threshold: float = 0.5
    source: str = "internal"
    version: int = 1
    description: str = ""
    tags: list[str] = field(default_factory=list)


def _standardize(series: pd.Series, method: str) -> pd.Series:
    """Apply standardization to a factor series with winsorization."""
    if method == "none" or len(series) < 2:
        return series
    if method == "zscore":
        std = series.std()
        if std == 0:
            return series * 0
        result = (series - series.mean()) / std
        # Winsorization: clip extreme Z-scores to prevent values like 16.22σ
        extreme_mask = result.abs() > ZSCORE_CLIP_BOUND
        if extreme_mask.any():
            n_extreme = extreme_mask.sum()
            _raw_max = result.abs().max()
            if _raw_max is not None:
                logger.warning(
                    "[_standardize] Z-score winsorization clipped %d values (max raw=%.2f, bound=%.1f)",
                    n_extreme, _raw_max, ZSCORE_CLIP_BOUND,
                )
        return result.clip(lower=-ZSCORE_CLIP_BOUND, upper=ZSCORE_CLIP_BOUND)
    if method == "rank":
        return series.rank(pct=True)
    if method == "minmax":
        rng = series.max() - series.min()
        if rng == 0:
            return series * 0
        return (series - series.min()) / rng
    return series


# ── Built-in computation functions for S1 core factors ──────────────

def _compute_ln_mcap(data: dict[str, Any]) -> float:
    """style.size.ln_mcap: 对数总市值"""
    mv = data.get("total_mv", 0)
    return math.log(mv) if mv > 0 else 0.0


def _compute_sma(data: dict[str, Any], window: int) -> float:
    """Shared SMA computation via pandas-ta."""
    close = data.get("close", [])
    if len(close) < window:
        return 0.0
    result = ta.sma(pd.Series(close), length=window)
    if result is None or result.empty:
        return 0.0
    val = result.iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def _compute_sma_5(data: dict[str, Any]) -> float:
    """technical.ma.sma_5: 5日均线"""
    return _compute_sma(data, 5)


def _compute_sma_10(data: dict[str, Any]) -> float:
    """technical.ma.sma_10: 10日均线"""
    return _compute_sma(data, 10)


def _compute_sma_20(data: dict[str, Any]) -> float:
    """technical.ma.sma_20: 20日均线"""
    return _compute_sma(data, 20)


def _compute_sma_60(data: dict[str, Any]) -> float:
    """technical.ma.sma_60: 60日均线"""
    return _compute_sma(data, 60)


def _compute_rsi_14(data: dict[str, Any]) -> float:
    """technical.rsi.rsi_14: 14日RSI (via pandas-ta)"""
    close = data.get("close", [])
    if len(close) < 15:
        return 50.0
    result = ta.rsi(pd.Series(close), length=14)
    if result is None or result.empty:
        return 50.0
    val = result.iloc[-1]
    return float(val) if not np.isnan(val) else 50.0


def _compute_macd(data: dict[str, Any]) -> float:
    """technical.macd.macd: MACD DIF值 (via pandas-ta)"""
    close = data.get("close", [])
    if len(close) < 26:
        return 0.0
    result = ta.macd(pd.Series(close), fast=12, slow=26, signal=9)
    if result is None or result.empty:
        return 0.0
    dif_col = "MACD_12_26_9"
    val = result[dif_col].iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def _compute_bollinger_bandwidth(data: dict[str, Any]) -> float:
    """technical.bollinger.bandwidth: 布林带宽% (via pandas-ta)"""
    close = data.get("close", [])
    if len(close) < 20:
        return 0.0
    result = ta.bbands(pd.Series(close), length=20, std=2)  # type: ignore[arg-type]
    if result is None or result.empty:
        return 0.0
    bbb_col = "BBB_20_2.0_2.0"
    val = result[bbb_col].iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def _compute_volume_ratio(data: dict[str, Any]) -> float:
    """technical.volume.vol_ratio: 量比 (近5日均量/近20日均量)"""
    volume = data.get("volume", [])
    if len(volume) < 20:
        return 1.0
    vol5 = np.mean(volume[-5:])
    vol20 = np.mean(volume[-20:])
    return float(vol5 / vol20) if vol20 > 0 else 1.0


def _compute_atr_14(data: dict[str, Any]) -> float:
    """technical.atr.atr_14: 14日ATR (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 15:
        return 0.0
    result = ta.atr(
        high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), length=14
    )
    if result is None or result.empty:
        return 0.0
    val = result.iloc[-1]
    return float(val) if not np.isnan(val) else 0.0


def _compute_vwap(data: dict[str, Any]) -> float:
    """technical.volume.vwap: 成交量加权平均价"""
    close = data.get("close", [])
    volume = data.get("volume", [])
    if not close or not volume or len(close) != len(volume):
        return float(close[-1]) if close else 0.0
    c = np.array(close)
    v = np.array(volume)
    total_vol = v.sum()
    return float(np.sum(c * v) / total_vol) if total_vol > 0 else float(c[-1])


def _compute_amount_stability(data: dict) -> float:
    """Amount stability: 20-day CV of turnover amount, negated so stable = high score."""
    amounts = data.get("amount") or data.get("volume") or []
    if len(amounts) < 5:
        return 0.0
    import statistics
    mean_a = statistics.mean(amounts)
    if mean_a < 1e-6:
        return 0.0
    cv = statistics.stdev(amounts) / mean_a
    return -min(cv, 10.0)


def _compute_panic_greed_diff(data: dict) -> float:
    """Panic-greed diff: current sentiment index minus 20-day mean."""
    idx = data.get("sentiment_index")
    hist = data.get("sentiment_history", [])
    if idx is None or len(hist) < 5:
        return 0.0
    import statistics
    return idx - statistics.mean(hist[-20:])


def _compute_news_heat(data: dict) -> float:
    """News heat: weighted sum of stars over recent items."""
    items = data.get("news_items", [])
    if not items:
        return 0.0
    total = 0.0
    for it in items[-30:]:
        s = float(it.get("stars", 0) or 0)
        total += s
    return total


def _compute_news_direction(data: dict) -> float:
    """News sentiment direction: ratio of positive news in recent items."""
    items = data.get("news_items", [])
    if len(items) < 3:
        return 0.0
    positive = sum(1 for it in items if it.get("level") in ("利好", "重大"))
    total = len(items)
    return positive / max(total, 1)


# ── KDJ 指标 (via pandas-ta) ─────────────────────────────────────
def _compute_kdj_k(data: dict) -> float:
    """technical.kdj.k_value: KDJ K 值 (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 9:
        return 50.0
    result = ta.kdj(high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), k=9, d=3)  # type: ignore[arg-type]
    if result is None or result.empty:
        return 50.0
    k_col = "K_9_3"
    val = result[k_col].iloc[-1]
    return float(val) if not pd.isna(val) else 50.0


def _compute_kdj_d(data: dict) -> float:
    """technical.kdj.d_value: KDJ D 值 (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 9:
        return 50.0
    result = ta.kdj(high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), k=9, d=3)  # type: ignore[arg-type]
    if result is None or result.empty:
        return 50.0
    d_col = "D_9_3"
    val = result[d_col].iloc[-1]
    return float(val) if not pd.isna(val) else 50.0


def _compute_kdj_j(data: dict) -> float:
    """technical.kdj.j_value: KDJ J 值 (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 9:
        return 50.0
    result = ta.kdj(high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), k=9, d=3)  # type: ignore[arg-type]
    if result is None or result.empty:
        return 50.0
    j_col = "J_9_3"
    val = result[j_col].iloc[-1]
    return float(val) if not pd.isna(val) else 50.0


# ── 综合信号（从 signal.py 迁移，2026-07-20） ─────────────────────
def _compute_signal_overall(data: dict) -> float:
    """technical.signal.overall: 综合买卖信号 (-1 ~ +1)"""
    rsi = data.get("rsi", 50)
    score = 0.0
    if rsi is not None:
        if rsi < 30:
            score += 0.4  # 超卖 → 买入信号
        elif rsi > 70:
            score -= 0.4  # 超买 → 卖出信号
        elif rsi < 40:
            score += 0.2
        elif rsi > 60:
            score -= 0.2

    macd = data.get("macd", 0)
    if macd is not None:
        if macd > 0:
            score += 0.2
        elif macd < 0:
            score -= 0.2

    ma_bias = data.get("ma_bias_20", 0)
    if ma_bias is not None:
        if ma_bias > 0.05:
            score -= 0.1
        elif ma_bias < -0.05:
            score += 0.1

    return max(-1.0, min(1.0, score))


# ── industry_diversification 基于 ETFClassifier ──────────────────
def _compute_industry_diversification(data: dict) -> float:
    """etf.industry_diversification: 用行业分布算 HHI（赫芬达尔指数）。
    值越低代表行业越分散（0 = 完全分散，1 = 完全集中）。
    """
    industry_holdings = data.get("industry_holdings", {})
    if not industry_holdings:
        # 无行业分布数据时尝试从概念板块推断
        concepts = data.get("concepts", [])
        if concepts:
            # 概念越多越分散
            n = len(concepts)
            return round(1.0 / max(n, 1), 4)
        return 0.0  # 默认中性

    total = sum(industry_holdings.values())
    if total <= 0:
        return 0.0
    hhi = sum((w / total) ** 2 for w in industry_holdings.values())
    return round(hhi, 4)


def _compute_change_pct(data: dict) -> float:
    """日涨跌幅：(close[-1] - close[-2]) / close[-2]。来源：Sina K-line 数据。"""
    closes = data.get("close", [])
    if len(closes) >= 2:
        return round((closes[-1] - closes[-2]) / closes[-2], 4)
    return 0.0


def _compute_return_1m(data: dict) -> float:
    """近1月收益率：(close[-1] - close[-21]) / close[-21]，约20个交易日。"""
    closes = data.get("close", [])
    if len(closes) >= 21:
        return round((closes[-1] - closes[-21]) / closes[-21], 4)
    if len(closes) >= 2:
        return round((closes[-1] - closes[0]) / closes[0], 4)
    return 0.0


def _compute_return_3m(data: dict) -> float:
    """近3月收益率：(close[-1] - close[-61]) / close[-61]，约60个交易日。"""
    closes = data.get("close", [])
    if len(closes) >= 61:
        return round((closes[-1] - closes[-61]) / closes[-61], 4)
    if len(closes) >= 2:
        return round((closes[-1] - closes[0]) / closes[0], 4)
    return 0.0


def _compute_price(data: dict) -> float:
    """最新价格：优先使用实时价格，fallback到K线最新收盘价。来源：Sina实时 / K-line。"""
    price = data.get("price")
    if price is not None and price > 0:
        return price
    closes = data.get("close", [])
    if closes and closes[-1] > 0:
        return closes[-1]
    return 0.0


# --- Scaffolding functions (保留待后续数据源接入) ---
def _compute_premium_discount(data: dict) -> float:
    """折溢价率：(ETF价格 - IOPV) / IOPV。正常范围 -0.03 ~ 0.03。"""
    nav = data.get("nav")
    price = data.get("price")
    if nav and price and nav > 0:
        return (price - nav) / nav
    return 0.0


def _compute_tracking_error(data: dict) -> float:
    """跟踪误差：ETF与基准指数日收益差的标准差（20日）。
    使用 data["close"] 和 data["benchmark_close"] 计算。
    正常范围 0~0.05，越小越好。
    """
    closes = data.get("close", [])
    bench_closes = data.get("benchmark_close", [])
    if len(closes) < 5 or len(bench_closes) < 5:
        return 0.0
    n = min(len(closes), len(bench_closes))
    diff = []
    for i in range(1, n):
        etf_ret = (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] > 0 else 0
        bench_ret = (bench_closes[i] - bench_closes[i-1]) / bench_closes[i-1] if bench_closes[i-1] > 0 else 0
        diff.append((etf_ret - bench_ret) ** 2)
    if len(diff) < 4:
        return 0.0
    import statistics, math
    return math.sqrt(statistics.mean(diff))


def _compute_shares_change(data: dict) -> float:
    """规模变化率：(当前份额 - 20日前份额) / 20日前份额。"""
    shares_change = data.get("shares_change_20d")
    if shares_change is not None:
        return float(shares_change)
    return 0.0


def _compute_institutional_holdings_change(data: dict) -> float:
    """etf.institutional_holdings_change: 用资金流向变化和份额变化代理机构持仓变化。

    优先级：
    1. data["institutional_holdings_change"] — 直接注入的机构持仓变化
    2. data["shares_change_20d"] — 20日份额变化率（基金规模变化代理）
    3. data["fund_scale"] — 最近一期基金规模变化率
    正值表示增持，负值表示减持。
    """
    # 直接数据
    direct = data.get("institutional_holdings_change")
    if direct is not None:
        return float(direct)

    # 份额变化作为代理（机构通常通过申赎影响份额）
    shares_chg = data.get("shares_change_20d")
    if shares_chg is not None:
        return float(shares_chg) * 0.5  # 折扣因子：份额变化不完全等同于机构持仓

    # 基金规模变化
    scale = data.get("fund_scale")
    if scale is not None and isinstance(scale, (int, float)):
        return float(scale) * 0.3

    return 0.0


# ── Policy factors (十五五 static mapping) ─────────────────────────

_POLICY_ALIGNMENT: dict[str, float] = {
    "半导体": 0.95, "电子": 0.90, "计算机": 0.85,
    "电力设备": 0.85, "通信": 0.80, "国防军工": 0.90,
    "医药生物": 0.75, "汽车": 0.75, "机械设备": 0.60,
    "有色金属": 0.55, "建筑装饰": 0.55, "基础化工": 0.50,
    "交通运输": 0.50, "宽基指数": 0.50,
    "家用电器": 0.45, "传媒": 0.45,
    "非银金融": 0.35, "商贸零售": 0.35,
    "食品饮料": 0.30, "纺织服装": 0.30,
    "银行": 0.25, "房地产": 0.20,
}

_STRATEGIC_EMERGING_INDUSTRIES: set[str] = {
    "半导体", "电子", "计算机", "电力设备",
    "医药生物", "国防军工", "通信", "机械设备", "汽车",
}

_DUAL_CIRCULATION_INDUSTRIES: set[str] = {
    "食品饮料", "家用电器", "汽车", "医药生物", "商贸零售",
}


def _compute_five_year_plan(data: dict) -> float:
    """Compute 十五五 plan alignment score based on ETF industry classification.

    Returns static score 0~1 from _POLICY_ALIGNMENT mapping.
    Fallback to 0.30 for industries not in the mapping.
    """
    industry = data.get("industry", "")
    return _POLICY_ALIGNMENT.get(industry, 0.30)


def _compute_strategic_emerging(data: dict) -> float:
    """Return 1.0 if ETF industry is in 战略新兴产业目录, else 0.0."""
    industry = data.get("industry", "")
    return 1.0 if industry in _STRATEGIC_EMERGING_INDUSTRIES else 0.0


def _compute_dual_circulation(data: dict) -> float:
    """Return 1.0 if ETF industry benefits from dual-circulation policy."""
    industry = data.get("industry", "")
    if industry in _DUAL_CIRCULATION_INDUSTRIES:
        return 1.0
    concepts = data.get("concepts", [])
    for c in concepts:
        if "消费" in c or "内需" in c or "外贸" in c:
            return 1.0
    return 0.0


def _compute_stock_divergence(data: dict) -> float:
    """Stock return divergence: use advance/decline ratio from sentiment_fetcher.

    When AD ratio < 0.5 (more decliners), divergence is negative (panic).
    When AD ratio > 1.5 (more advancers), divergence is positive (greed).
    Normalized to -1.0 ~ 1.0 range with neutral at AD=1.0.
    """
    ad = data.get("advance_decline")
    if ad is not None and ad > 0:
        # AD=1.0 → 0, AD=0.5 → -0.5, AD=2.0 → +0.5
        return min(max((ad - 1.0) * 2.0, -1.0), 1.0)
    try:
        from ..core.async_utils import run_in_thread
        from ..services.market_data_hub import market_data_hub
        import asyncio
        loop = asyncio.get_running_loop()
        if loop and loop.is_running():
            # S02: Reduced timeout from 5s to 2s to prevent 5s blocking loops
            ad_val = run_in_thread(market_data_hub.get_advance_decline, timeout=2)
            if ad_val is not None and ad_val > 0:
                return min(max((ad_val - 1.0) * 2.0, -1.0), 1.0)
    except Exception:
        pass
    return 0.0


# ── Mapping of factor code → compute function ─────────────────────

_BUILTIN_COMPUTERS: dict[str, Callable[[dict], float]] = {
    "style.size.ln_mcap": _compute_ln_mcap,
    "style.size.ln_float_mcap": _compute_ln_mcap,  # Same logic with float_mv
    "technical.ma.sma_5": _compute_sma_5,
    "technical.ma.sma_10": _compute_sma_10,
    "technical.ma.sma_20": _compute_sma_20,
    "technical.ma.sma_60": _compute_sma_60,
    "technical.rsi.rsi_14": _compute_rsi_14,
    "technical.macd.macd": _compute_macd,
    "technical.bollinger.bandwidth": _compute_bollinger_bandwidth,
    "technical.volume.vol_ratio": _compute_volume_ratio,
    "technical.atr.atr_14": _compute_atr_14,
    "technical.volume.vwap": _compute_vwap,
    "etf.amount_stability": _compute_amount_stability,
    "etf.change_pct": _compute_change_pct,
    "etf.return_1m": _compute_return_1m,
    "etf.return_3m": _compute_return_3m,
    "etf.price": _compute_price,
    "etf.premium_discount": _compute_premium_discount,
    "etf.tracking_error": _compute_tracking_error,
    "etf.shares_change": _compute_shares_change,
    "etf.industry_diversification": _compute_industry_diversification,
    "etf.institutional_holdings_change": _compute_institutional_holdings_change,
    "sentiment.panic_greed_diff": _compute_panic_greed_diff,
    "sentiment.stock_divergence": _compute_stock_divergence,
    "sentiment.news_heat": _compute_news_heat,
    "sentiment.news_direction": _compute_news_direction,
    # Policy factors (十五五)
    "china.policy.five_year_plan": _compute_five_year_plan,
    "china.policy.strategic_emerging": _compute_strategic_emerging,
    "china.policy.dual_circulation": _compute_dual_circulation,
    # KDJ (2026-07-20 从 indicators.py 注册)
    "technical.kdj.k_value": _compute_kdj_k,
    "technical.kdj.d_value": _compute_kdj_d,
    "technical.kdj.j_value": _compute_kdj_j,
    # 综合信号 (2026-07-20 从 signal.py 注册)
    "technical.signal.overall": _compute_signal_overall,
}

# 33 core factors for S1 (extend this list as implementation progresses)
_CORE_FACTORS = [
    # Style: Size & Value
    "style.size.ln_mcap",
    "style.size.ln_float_mcap",
    # Technical: MA
    "technical.ma.sma_5",
    "technical.ma.sma_10",
    "technical.ma.sma_20",
    "technical.ma.sma_60",
    # Technical: RSI
    "technical.rsi.rsi_14",
    # Technical: MACD
    "technical.macd.macd",
    # Technical: Bollinger
    "technical.bollinger.bandwidth",
    # Technical: Volume
    "technical.volume.vol_ratio",
    # Technical: ATR
    "technical.atr.atr_14",
    # Technical: VWAP
    "technical.volume.vwap",
    # ETF-specific
    "etf.price",
    "etf.premium_discount",
    "etf.change_pct",
    "etf.return_1m",
    "etf.return_3m",
    "etf.tracking_error",
    "etf.shares_change",
    "etf.amount_stability",
    "etf.industry_diversification",
    "etf.institutional_holdings_change",
    # Sentiment
    "sentiment.panic_greed_diff",
    "sentiment.stock_divergence",
    "sentiment.news_heat",
    "sentiment.news_direction",
    # Policy factors
    "china.policy.five_year_plan",
    "china.policy.strategic_emerging",
    "china.policy.dual_circulation",
    # KDJ
    "technical.kdj.k_value",
    "technical.kdj.d_value",
    "technical.kdj.j_value",
    # Comprehensive signal
    "technical.signal.overall",
]


# CircuitBreaker has been replaced by SourceRegistry (S1: 熔断器接入数据源)
# The old class-level CircuitBreaker was removed — all data source health
# tracking is now handled by source_registry.SourceHealth with per-source
# circuit breakers and exponential backoff.
# K-line caching is retained below for performance.


# 全局 K 线缓存 — 避免每次 compute() 都网络 I/O
_kline_cache: dict[str, dict[str, Any]] = {}
_kline_cache_ts: float = 0.0
KLINE_CACHE_TTL: float = 300.0  # 300s 缓存，覆盖设计→检查之间的时间差


def _get_cached_kline(symbols: list[str]) -> dict[str, dict[str, Any]] | None:
    """如果缓存有效且包含所有请求的 symbol，返回缓存数据。"""
    global _kline_cache, _kline_cache_ts
    if not _kline_cache:
        return None
    if time.time() - _kline_cache_ts > KLINE_CACHE_TTL:
        return None
    missing = [s for s in symbols if s not in _kline_cache]
    if missing:
        return None
    return {s: dict(_kline_cache[s]) for s in symbols}


def _set_kline_cache(data: dict[str, dict[str, Any]]):
    """更新 K 线缓存。"""
    global _kline_cache, _kline_cache_ts
    for sym, d in data.items():
        if "_fetch_error" not in d:  # 只缓存成功获取的数据
            _kline_cache[sym] = dict(d)
    _kline_cache_ts = time.time()


class FactorRegistry:
    """YAML-driven factor registry with async computation.

    Usage:
        reg = FactorRegistry()
        reg.load_definitions()
        factors = reg.list_factors(category="technical")
        result = await reg.compute(["510300", "518880"])
    """

    def __init__(self):
        self._factors: dict[str, FactorDefinition] = {}
        self._computers: dict[str, Callable[[dict], float]] = dict(_BUILTIN_COMPUTERS)
        self._last_ic_batch: dict[str, float] = {}
        # Z03: 因子健康度元数据（sample_count / 最后计算时间）
        self._sample_counts: dict[str, int] = {}
        self._last_computed_at: str | None = None
        self.load_definitions()

    def load_definitions(self, yaml_path: str | None = None) -> None:
        """Load factor definitions from YAML file.
        
        If yaml_path is explicitly provided, clear the existing factor dict
        so the caller can load a clean test YAML (used in unit tests).
        """
        if yaml_path is not None:
            self._factors.clear()
        path = Path(yaml_path) if yaml_path else _DEFAULT_YAML
        if not path.exists():
            logger.warning("Factor definitions not found at %s", path)
            return
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # YAML 根结构是列表（`- code:`），不是 dict（兼容两种格式）
        if isinstance(data, list):
            raw_list = data
        else:
            raw_list = data.get("factor_definitions", [])
        for item in raw_list:
            code = item.get("code", "")
            if not code:
                continue
            self._factors[code] = FactorDefinition(
                code=code,
                name=item.get("name", ""),
                category=item.get("category", ""),
                subcategory=item.get("subcategory", ""),
                frequency=item.get("frequency", "daily"),
                compute_fn=item.get("compute_fn", ""),
                dependencies=item.get("dependencies", []),
                standardization=item.get("standardization", "zscore"),
                lookback_window=item.get("lookback_window", 1),
                ic_threshold=item.get("ic_threshold", 0.02),
                ic_ir_threshold=item.get("ic_ir_threshold", 0.5),
                source=item.get("source", "internal"),
                version=item.get("version", 1),
                description=item.get("description", ""),
                tags=item.get("tags", []),
            )
        logger.info("Loaded %d factor definitions from %s", len(self._factors), path)

    def list_factors(self, category: str | None = None) -> list[FactorDefinition]:
        """List all factors, optionally filtered by category."""
        if category:
            return [f for f in self._factors.values() if f.category == category]
        return list(self._factors.values())

    @staticmethod
    def aggregate_factor_scores(
        factor_scores: dict[str, float],
    ) -> dict[str, float]:
        """B1: 将点分键聚合为顶层分类键。

        FactorRegistry.compute() 返回的键名是点分式如 `technical.ma.sma_5`，
        但 allocation_engine 使用顶层键 `technical`、`momentum`、`valuation`、`sentiment`。

        聚合策略：对每个顶层分类，取下属所有因子值的均值。
        无下属因子的顶层键保持原值（如已存在则直接保留）。
        """
        if not factor_scores:
            return factor_scores

        # 定义顶层分类到点分前缀的映射
        # 注意：etf.return_1m/return_3m/change_pct 等回报类因子由 etf. 前缀捕获到 momentum
        # etf.price 由 valuation 捕获（价格本身也是估值维度之一）
        CATEGORY_PREFIXES = {
            "technical": ["technical."],
            "momentum": ["etf.return_", "etf.change_pct", "china.policy.", "technical.signal."],
            "valuation": ["style.", "etf.price"],
            "sentiment": ["sentiment."],
        }

        # 排除 ln_mcap/ln_float_mcap 从 valuation 聚合：市值维度不等于估值维度
        _EXCLUDE_FROM_VALUATION = {"ln_mcap", "ln_float_mcap"}

        result = dict(factor_scores)  # 保留所有原始键

        for top_key, prefixes in CATEGORY_PREFIXES.items():
            values = []
            for key, val in factor_scores.items():
                if isinstance(val, (int, float)) and abs(val) > 0.001:
                    # 排除市值因子扭曲 valuation 聚合
                    if top_key == "valuation":
                        _short_key = key.split(".")[-1]
                        if _short_key in _EXCLUDE_FROM_VALUATION:
                            continue
                    for prefix in prefixes:
                        if key.startswith(prefix):
                            values.append(val)
                            break
            if values:
                result[top_key] = sum(values) / len(values)
            # 如果没有任何非零匹配子因子，不设置顶层键（让消费方 fallback 到 0.0）

        return result

    def get_factor(self, code: str) -> FactorDefinition | None:
        """Get a single factor definition by code."""
        return self._factors.get(code)

    def register_computer(self, code: str, fn: Callable[[dict], float]) -> None:
        """Register a custom computation function for a factor."""
        self._computers[code] = fn

    async def _fetch_market_data(self, symbols: list[str], symbol_extra: dict[str, dict] | None = None) -> dict[str, dict[str, Any]]:
        """[DEPRECATED] S5: 仅在 Hub 缓存无数据时作为 fallback 使用。

        新代码应通过 MarketDataHub.get_kline() 获取 K 线数据。
        
        .. deprecated::
            Use MarketDataHub.get_kline() or get_kline_rows() instead.
            Will be removed in Phase 20.
        """
        """Fetch real market data for factor computation.

        Uses K-line cache (60s TTL) and circuit breaker to avoid
        hammering external APIs when they are down.
        """
        # 先查缓存(miss 才走网络)
        cached = _get_cached_kline(symbols)
        if cached is not None:
            if symbol_extra:
                for sym in symbols:
                    if sym in cached and sym in symbol_extra:
                        cached[sym].update(symbol_extra[sym])
            return cached

        # 电路断熔（SourceRegistry）：如果外部数据源连续故障，直接返回空数据
        source_h = _source_registry._health("factor.history")
        now = time.time()
        if not source_h.available(now):
            logger.warning("[factor] SourceRegistry circuit open for factor.history — returning empty data for %s", symbols)
            return {sym: {} for sym in symbols}

        from ..services.market_data_hub import market_data_hub
        import asyncio

        sem = asyncio.Semaphore(8)

        async def fetch_one(sym: str) -> tuple[str, dict[str, Any]]:
            async with sem:
                try:
                    from ..core.async_utils import run_sync
                    rows = await asyncio.wait_for(
                        run_sync(market_data_hub.get_history, sym, "A", "daily", timeout=20),
                        timeout=25,
                    )
                    if not rows:
                        raise ValueError("empty data")
                    closes = [r.get("close", 0) for r in rows if r.get("close")]
                    highs = [r.get("high", 0) for r in rows if r.get("high")]
                    lows = [r.get("low", 0) for r in rows if r.get("low")]
                    vols = [r.get("volume", 0) for r in rows if r.get("volume")]
                    if len(closes) < 5:
                        raise ValueError(f"too few data points: {len(closes)}")
                    change_pct = round((closes[-1] - closes[-2]) / closes[-2], 4) if len(closes) >= 2 else 0.0
                    return sym, {
                        "total_mv": (
                            float((symbol_extra or {}).get(sym, {}).get("fund_scale", 0) or 0)
                            or float(rows[-1].get("total_mv", 0) or 0)
                            or 100e9
                        ),
                        "float_mv": float(rows[-1].get("float_mv", 80e9) or 80e9),
                        "close": closes[-60:],
                        "high": highs[-60:],
                        "low": lows[-60:],
                        "volume": vols[-60:],
                        "change_pct": change_pct,
                        # S2: inject fund_shares for shares_change factor
                        "fund_shares": float((symbol_extra or {}).get(sym, {}).get("fund_shares", 0) or 0),
                    }
                except Exception as e:
                    logger.warning("[factor] fetch_history failed for %s: %s — skipping", sym, e)
                    source_h.record_failure(time.time(), route="kline", operation="history",
                                            target=sym, error_message=str(e)[:200])
                    return sym, {"_fetch_error": str(e)}

        tasks = [fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks)
        data = dict(results)

        # 2. 批量获取 IOPV 数据（Sina + QQ Tencent 双源降级）
        # 用于 premium_discount 因子计算 (S8: 腾讯QQ降级链)
        try:
            prefixes = {"5": "sh", "6": "sh", "0": "sz", "1": "sz", "3": "sz"}
            sina_list = [f"{prefixes.get(sym[0], chr(39)+sym+chr(39))}" for sym in symbols]

            async def _fetch_iopv_from_sina(s_list: list[str]) -> dict[str, dict]:
                """通过线程池获取新浪 IOPV 实时行情。"""
                from ..core.async_utils import run_sync

                def _sync_fetch():
                    import urllib.request
                    url = f"http://hq.sinajs.cn/list={','.join(s_list)}"
                    req = urllib.request.Request(
                        url, headers={"Referer": "http://finance.sina.com.cn"}
                    )
                    resp = urllib.request.urlopen(req, timeout=8)
                    return resp.read().decode("gbk")

                raw = await run_sync(_sync_fetch, timeout=10)
                parsed: dict[str, dict] = {}
                for line in raw.strip().split("\n"):
                    if '"' not in line:
                        continue
                    parts = line.split('"')[1].split(",")
                    if len(parts) < 10:
                        continue
                    sym = parts[2] if parts[2] else ""
                    if not sym:
                        continue
                    try:
                        price = float(parts[3]) if parts[3] else None
                        nav = float(parts[8]) if parts[8] else None
                        parsed[sym] = {"price": price or 0.0, "nav": nav}
                    except (ValueError, IndexError):
                        pass
                return parsed

            async def _fetch_iopv_from_qq(s_list: list[str]) -> dict[str, dict]:
                """S8: 腾讯 QQ 行情作为 Sina IOPV 的降级源。

                QQ 格式: v_sh510050="1~510050~50ETF~...~price~...~iopv..."
                ETF 字段位置（~分隔）:
                  pos 3 = current price, pos 31 = IOPV (estimated NAV)
                """
                from ..core.async_utils import run_sync

                def _sync_fetch():
                    import urllib.request
                    qq_symbols = ",".join(s_list)
                    url = f"http://qt.gtimg.cn/q={qq_symbols}"
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    resp = urllib.request.urlopen(req, timeout=8)
                    return resp.read().decode("utf-8")

                raw = await run_sync(_sync_fetch, timeout=10)
                parsed: dict[str, dict] = {}
                for line in raw.strip().split("\n"):
                    if "~" not in line or '"' not in line:
                        continue
                    parts = line.split('"')[1].split("~")
                    if len(parts) < 33:
                        continue
                    try:
                        price_str = parts[3] if len(parts) > 3 and parts[3] else ""
                        iopv_str = parts[31] if len(parts) > 31 and parts[31] else ""
                        code = parts[2] if len(parts) > 2 else ""
                        if not code:
                            continue
                        price = float(price_str) if price_str else None
                        iopv = float(iopv_str) if iopv_str else None
                        if iopv and iopv > 0:
                            parsed[code] = {"price": price or 0.0, "nav": iopv}
                    except (ValueError, IndexError):
                        pass
                return parsed

            # 首先尝试 Sina
            iopv_data = await _fetch_iopv_from_sina(sina_list)
            sina_hit_count = sum(1 for v in iopv_data.values() if v.get("nav", 0) > 0)

            # 如果 Sina 数据不足，降级到 QQ Tencent
            if sina_hit_count < len(symbols) * 0.3:
                logger.info("[factor] Sina IOPV only got %d/%d, trying QQ Tencent fallback (S8)",
                            sina_hit_count, len(symbols))
                try:
                    qq_data = await _fetch_iopv_from_qq(sina_list)
                    qq_hit_count = sum(1 for v in qq_data.values() if v.get("nav", 0) > 0)
                    if qq_hit_count > sina_hit_count:
                        logger.info("[factor] QQ Tencent fallback got %d IOPV values", qq_hit_count)
                        iopv_data = qq_data
                except Exception as qq_e:
                    logger.debug("[factor] QQ Tencent IOPV fallback failed: %s", qq_e)

            for sym, values in iopv_data.items():
                if sym in data and values.get("nav", 0) > 0:
                    data[sym].setdefault("price", values.get("price", 0))
                    data[sym]["nav"] = values.get("nav", 0)
        except Exception as e:
            logger.warning("[factor] batch NAV fetch failed: %s (proxy? — non-fatal)", e)

        # Z04: 注入 symbol_extra 中的 etf_specific 字段
        # 这些字段用于：industry/concepts → industry_diversification,
        # benchmark_close → tracking_error, shares_change_20d → shares_change
        if symbol_extra:
            for sym in symbols:
                if sym in data and sym in symbol_extra:
                    extra = symbol_extra[sym]
                    # 只注入 etf_specific 相关字段，不覆盖已有字段
                    for key in ("industry", "concepts", "benchmark_close",
                                "shares_change_20d", "institutional_holdings_change",
                                "shares_change", "fund_scale"):
                        if key in extra and key not in data[sym]:
                            data[sym][key] = extra[key]

        # 缓存成功获取的数据，记录 SourceRegistry 成功
        source_h.record_success(route="kline", operation="batch_fetch", target=",".join(symbols[:3]))
        _set_kline_cache(data)

        return data

    async def warm_cache(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """预热 K 线缓存：仅当缓存为空或过期时获取数据。"""
        cached = _get_cached_kline(symbols)
        if cached is not None:
            return cached
        data = await self._fetch_market_data(symbols)
        return data

    async def compute(
        self,
        symbols: list[str],
        codes: list[str] | None = None,
        market_data: dict[str, dict[str, Any]] | None = None,
        symbol_extra: dict[str, dict] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Compute factor values for given symbols.

        Args:
            symbols: List of ETF/code symbols to compute for.
            codes:   Specific factor codes to compute (None = all with computers).
            market_data: Optional pre-fetched market data. If None, uses mock/placeholder.

        Returns:
            {symbol: {factor_code: standardized_value}}
        """
        if codes is None:
            codes = [c for c in _CORE_FACTORS if c in self._computers]

        if market_data is not None:
            # 使用外部注入的真实数据
            pass
        else:
            market_data = await self._fetch_market_data(symbols, symbol_extra=symbol_extra)

        # Phase 2.7.2: 空数据告警 — 所有 symbol 的 data 均为空时发出错误日志
        if market_data:
            empty_symbols = [sym for sym in symbols if not market_data.get(sym)]
            if len(empty_symbols) == len(symbols):
                logger.error(
                    "[factor] compute() — _fetch_market_data returned EMPTY data for ALL %d symbols: %s",
                    len(symbols), symbols[:5],
                )
            elif empty_symbols:
                logger.warning(
                    "[factor] compute() — %d/%d symbols have empty data: %s",
                    len(empty_symbols), len(symbols), empty_symbols[:5],
                )

        result: dict[str, dict[str, float]] = {}
        for sym in symbols:
            row: dict[str, float] = {}
            data = market_data.get(sym, {}) if market_data else {}

            # Phase 2.7.4: 缓存降级 — 如果 data 为空，尝试降级到过期 K 线缓存
            if not data:
                stale = _get_cached_kline([sym])
                if stale and sym in stale:
                    logger.warning("[factor] compute() — using stale cache for %s (live data empty)", sym)
                    data = stale[sym]

            for code in codes:
                computer = self._computers.get(code)
                if computer is None:
                    continue
                try:
                    raw_value = computer(data)
                    definition = self._factors.get(code)
                    row[code] = raw_value if raw_value is not None else 0.0
                except Exception as e:
                    logger.debug("Factor %s failed for %s: %s", code, sym, e)
                    row[code] = 0.0
            result[sym] = row

        # ── 跨符号 z-score 标准化（用临时 dict 存储原始值） ──
        import statistics
        _raw: dict[str, list[tuple[str, float]]] = {}
        for code in codes:
            definition = self._factors.get(code)
            if not definition or definition.standardization not in ("zscore", "zscore_large"):
                continue
            _raw[code] = []
            for sym in symbols:
                val = result.get(sym, {}).get(code, 0.0)
                _raw[code].append((sym, val))
            all_v = [v for _, v in _raw[code]]
            if len(all_v) < 2:
                continue
            mean_v = statistics.mean(all_v)
            std_v = statistics.stdev(all_v)
            if std_v < 1e-10:
                continue
            # ── 混合归一化（Solution Design S2） ──
            # z-score（统计异常度）* 0.7 + min-max（相对排名）* 0.3
            # 保证即使 z-score 全负，顶部标的仍得正分
            all_vals = [v for _, v in _raw[code]]
            min_v = min(all_vals)
            max_v = max(all_vals)
            mm_range = max_v - min_v
            for sym, val in _raw[code]:
                z = (val - mean_v) / std_v
                # min-max 归一化到 [-1, 1]
                if mm_range > 1e-10:
                    mm = (val - min_v) / mm_range * 2.0 - 1.0
                else:
                    mm = 0.0
                combined = z * 0.7 + mm * 0.3
                result[sym][code] = combined * 5.0 if definition.standardization != "zscore_large" else combined
            # zscore_large: 二次映射到 (0~1)
            if definition.standardization == "zscore_large":
                z_vals = [result[sym][code] for sym, _ in _raw[code]]
                min_z, max_z = min(z_vals), max(z_vals)
                if max_z - min_z > 1e-10:
                    for sym, _ in _raw[code]:
                        result[sym][code] = (result[sym][code] - min_z) / (max_z - min_z)

        # ── 后处理：从已计算因子推导综合信号 ──
        signal_code = "technical.signal.overall"
        if signal_code in self._computers and signal_code not in (codes or []):
            pass  # signal 不在 codes 中时跳过
        elif signal_code in (codes or []) or codes is None:
            for sym in symbols:
                if sym not in result:
                    continue
                # Build enriched data dict from computed factors
                enriched = dict(market_data.get(sym, {}))
                enriched["rsi"] = result[sym].get("technical.rsi.rsi_14", 50)
                enriched["macd"] = result[sym].get("technical.macd.macd", 0)
                # ma_bias: derive from sma_20 and last close
                sma20 = result[sym].get("technical.ma.sma_20", 0)
                last_close = enriched.get("close", [None])[-1] if enriched.get("close") else None
                macd_val = result[sym].get("technical.macd.macd", 0)
                if macd_val is not None and abs(macd_val) > 0.001:
                    enriched["macd"] = macd_val
                if sma20 != 0 and last_close and last_close > 0:
                    enriched["ma_bias_20"] = (last_close - sma20) / sma20
                try:
                    sig = self._computers[signal_code](enriched)
                    result[sym][signal_code] = sig
                except Exception as e:
                    logger.debug("Signal factor failed for %s: %s", sym, e)
                    result[sym][signal_code] = 0.0

        # ── 数据质量管理：记录零分比例但不熔断（P0-2 去除 meltdown 异常） ──
        if codes:
            all_empty = 0
            for sym in symbols:
                if sym not in result or not result[sym]:
                    all_empty += 1
                    continue
                valid = [v for v in result[sym].values() if isinstance(v, (int, float)) and abs(v) > 0.001]
                if len(valid) == 0:
                    all_empty += 1
            total = len(symbols)
            if total > 0 and all_empty / total > 0.5:
                logger.warning("[factor] data quality: %.0f%% of symbols have zero factor scores (P0-2 suppressed meltdown)",
                               all_empty / total * 100)

        # Record for IC tracking
        try:
            for sym in symbols:
                if sym in result and result[sym]:
                    for code, value in result[sym].items():
                        if abs(value) > 0.001:
                            ic_tracker.record(sym, code, value)
        except Exception as e:
            # P0 fix-plan-master: bare except was silently swallowing errors
            logger.warning("[factor] IC tracking record failed (non-fatal): %s", e)

        # Compute periodic IC for current batch
        try:
            if market_data is not None:
                ic_batch = ic_tracker.compute_periodic_ic(result, market_data, window=1)
                if ic_batch:
                    self._last_ic_batch = ic_batch
                    # Z03: 记录样本数与最后计算时间（供 /factors/active 健康度展示）
                    from datetime import datetime, timezone as _tz
                    self._last_computed_at = datetime.now(_tz.utc).isoformat()
                    self._sample_counts = {
                        code: sum(
                            1 for sym in result
                            if abs((result[sym].get(code) or 0)) > 0.001
                        )
                        for code in ic_batch
                    }
                    # B3: IC threshold alerts
                    for code, ic_val in ic_batch.items():
                        definition = self._factors.get(code)
                        if definition and 0 < abs(ic_val) < definition.ic_threshold:
                            logger.warning(
                                "[factor] IC below threshold for %s: ic=%.4f < threshold=%.4f",
                                code, ic_val, definition.ic_threshold,
                            )
        except Exception as exc:
            logger.debug("[factor] IC batch compute failed: %s", exc)

        return result


# Global singleton
registry = FactorRegistry()
