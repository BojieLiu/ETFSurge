"""
FactorRegistry: YAML-driven factor definitions with async computation engine.

Loads factor_definitions.yaml, manages 167+ factor definitions, and provides
async computation for 30 core factors (S1 scope).
"""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

import numpy as np
import pandas as pd
import pandas_ta as ta
import yaml

# A1 (round23 §10.1): 分类聚合逻辑下沉 core/factor_aggregate（engine 可依赖 core 纯函数）——
# 本模块 re-export 保持旧引用（CATEGORY_AGG / IC_* / _ic_decay_mean）兼容，单一真相源在 core。
# ⚠️ round36：此块为有意 re-export（tests 等外部经本模块导入 IC_FLIP_THRESHOLD 等），
# ruff F401 曾误删导致 ImportError——noqa = 有意保留。
from ..core.factor_aggregate import (  # noqa: F401
    CATEGORY_AGG,
    IC_FLIP_THRESHOLD,
    IC_HALF_LIFE,
    IC_MIN_BATCHES,
    _ic_decay_mean,
)
from ..core.factor_values import is_meaningful_value  # FS1: 零值判定单点
from ..core.source_registry import registry as _source_registry
from ..factors.ic_tracker import ic_tracker

logger = logging.getLogger(__name__)

# Z-score clipping bound: cap extreme Z-scores to [-5, 5] to prevent
# values like 16.22σ from distorting downstream allocation.
ZSCORE_CLIP_BOUND = 5.0

# ── R75 修复: advance_decline 缓存（消除 compute() 内同步阻塞事件循环）──
# 原 _compute_stock_divergence 在每只 symbol 的同步计算里各自 run_in_thread 阻塞事件循环
# 最多 2s；回填 500 个交易日累计 ~16 分钟卡死后端（/health 排队 50s+）。advance_decline
# 是全市场共用指标，改为模块级 TTL 缓存 + 单次非阻塞获取（await run_sync），TTL 内复用，
# 由 compute() 注入每只 symbol 的 data，彻底消除每符号阻塞。
_AD_CACHE_TTL = 60.0
_AD_CACHE_VAL: float | None = None
_AD_CACHE_TS: float = 0.0


async def _cached_advance_decline() -> float | None:
    """非阻塞获取涨跌家数比（带 TTL 缓存）。

    原同步阻塞版（run_in_thread + future.result()）会冻结事件循环；此处改用
    await run_sync（loop.run_in_executor + await），永不阻塞事件循环线程。
    """
    global _AD_CACHE_VAL, _AD_CACHE_TS
    _now = time.monotonic()
    if _AD_CACHE_VAL is not None and (_now - _AD_CACHE_TS) < _AD_CACHE_TTL:
        return _AD_CACHE_VAL
    try:
        from ..core.async_utils import run_sync
        from ..services.market_data_hub import market_data_hub as _hub
        _val = await run_sync(_hub.get_advance_decline, timeout=2)
    except Exception:
        _val = None
    if _val is not None:
        _AD_CACHE_VAL = _val
        _AD_CACHE_TS = _now
    return _AD_CACHE_VAL


# round15 方案一: technical 显式聚合映射（前缀 → (方向, 变换模式)）。
# direction/neutral_value 的单一来源是 FactorDefinition（yaml）；此表仅作
# 默认/文档值——definitions 提供时以 FactorDefinition 为准（防两处配置漂移）。
# 变换模式：symmetric50 = raw 区间因子 (neutral-val)/neutral；
#          negate = zscore 均值回归因子取负（KDJ 超买为负分）。
# A1: 定义已移至 core/factor_aggregate.CATEGORY_AGG（本模块 re-export）


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
    # round15 方案一: 方向契约——+1 正向（动量）/ -1 反向（均值回归），聚合前
    # 方向化用；neutral_value 为 raw 区间因子中性点（如 RSI 50），zscore 因子置 None。
    direction: int = 1
    neutral_value: float | None = None
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

def _compute_ln_mcap(data: dict[str, Any]) -> float | None:
    """style.size.ln_mcap: 对数总市值"""
    # R150: 生产 refresh_pool 注入字段名为 fund_scale（market_data_hub.py:318），
    # 而本函数原读 total_mv —— 两名字对不上导致恒 None。改为别名读取兼容两条路径。
    mv = data.get("total_mv") or data.get("fund_scale") or 0
    # R85 (round30): 缺数据返回 None（下游区分「真实 0」与「无数据」）——
    # 旧 0.0 占位使全标的同值 → z-score std≈0 恒常量，无法区分「市值真 0」与「缺失」。
    return math.log(mv) if mv > 0 else None


def _compute_ln_float_mcap(data: dict[str, Any]) -> float | None:
    """style.size.ln_float_mcap: 对数流通市值"""
    # R150: 原注册到 _compute_ln_mcap 读 total_mv，从未读 float_mv —— ln_float_mcap
    # 恒等于 ln_mcap。拆独立函数读 float_mv（无源时返回 None，gap 机制标注缺失）。
    mv = data.get("float_mv") or 0
    return math.log(mv) if mv > 0 else None


def _compute_sma(data: dict[str, Any], window: int) -> float | None:
    """Shared SMA computation via pandas-ta."""
    close = data.get("close", [])
    if len(close) < window:
        return None
    result = ta.sma(pd.Series(close), length=window)
    if result is None or result.empty:
        return None
    val = result.iloc[-1]
    return float(val) if not np.isnan(val) else None


def _compute_sma_5(data: dict[str, Any]) -> float | None:
    """technical.ma.sma_5: 5日均线"""
    return _compute_sma(data, 5)


def _compute_sma_10(data: dict[str, Any]) -> float | None:
    """technical.ma.sma_10: 10日均线"""
    return _compute_sma(data, 10)


def _compute_sma_20(data: dict[str, Any]) -> float | None:
    """technical.ma.sma_20: 20日均线"""
    return _compute_sma(data, 20)


def _compute_sma_60(data: dict[str, Any]) -> float | None:
    """technical.ma.sma_60: 60日均线"""
    return _compute_sma(data, 60)


def _compute_rsi_14(data: dict[str, Any]) -> float | None:
    """technical.rsi.rsi_14: 14日RSI (via pandas-ta)"""
    close = data.get("close", [])
    if len(close) < 15:
        return None
    result = ta.rsi(pd.Series(close), length=14)
    if result is None or result.empty:
        return None
    val = result.iloc[-1]
    return float(val) if not np.isnan(val) else None


def _compute_macd(data: dict[str, Any]) -> float | None:
    """technical.macd.macd: MACD DIF值 (via pandas-ta)"""
    close = data.get("close", [])
    if len(close) < 26:
        return None
    result = ta.macd(pd.Series(close), fast=12, slow=26, signal=9)
    if result is None or result.empty:
        return None
    dif_col = "MACD_12_26_9"
    val = result[dif_col].iloc[-1]
    return float(val) if not np.isnan(val) else None


def _compute_bollinger_bandwidth(data: dict[str, Any]) -> float | None:
    """technical.bollinger.bandwidth: 布林带宽% (via pandas-ta)"""
    close = data.get("close", [])
    if len(close) < 20:
        return None
    result = ta.bbands(pd.Series(close), length=20, std=2)  # type: ignore[arg-type]
    if result is None or result.empty:
        return None
    bbb_col = "BBB_20_2.0_2.0"
    val = result[bbb_col].iloc[-1]
    return float(val) if not np.isnan(val) else None


def _compute_volume_ratio(data: dict[str, Any]) -> float | None:
    """technical.volume.vol_ratio: 量比 (近5日均量/近20日均量)"""
    volume = data.get("volume", [])
    if len(volume) < 20:
        return None
    vol5 = np.mean(volume[-5:])
    vol20 = np.mean(volume[-20:])
    return float(vol5 / vol20) if vol20 > 0 else None


def _compute_atr_14(data: dict[str, Any]) -> float | None:
    """technical.atr.atr_14: 14日ATR (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 15:
        return None
    result = ta.atr(
        high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), length=14
    )
    if result is None or result.empty:
        return None
    val = result.iloc[-1]
    return float(val) if not np.isnan(val) else None


def _compute_vwap(data: dict[str, Any]) -> float | None:
    """technical.volume.vwap: 成交量加权平均价"""
    close = data.get("close", [])
    volume = data.get("volume", [])
    if not close or not volume or len(close) != len(volume):
        return None
    c = np.array(close)
    v = np.array(volume)
    total_vol = v.sum()
    return float(np.sum(c * v) / total_vol) if total_vol > 0 else None


def _compute_amount_stability(data: dict) -> float | None:
    """Amount stability: 20-day CV of turnover amount, negated so stable = high score."""
    amounts = data.get("amount") or data.get("volume") or []
    if len(amounts) < 5:
        return None
    import statistics
    mean_a = statistics.mean(amounts)
    if mean_a < 1e-6:
        return 0.0
    cv = statistics.stdev(amounts) / mean_a
    return -min(cv, 10.0)


def _compute_panic_greed_diff(data: dict) -> float | None:
    """Panic-greed diff: current sentiment index minus 20-day mean."""
    idx = data.get("sentiment_index")
    hist = data.get("sentiment_history", [])
    if idx is None or len(hist) < 5:
        return None
    import statistics
    return idx - statistics.mean(hist[-20:])


def _safe_stock_news(hub, symbol: str, cache: dict) -> list:
    """F12: 标的相关新闻（线程内调用 + 调用级缓存 + 异常静默）。

    get_news_stock 是同步实时取数（可能触网失败/慢）——经 asyncio.to_thread
    提交线程池避免阻塞事件循环；失败返回 [] 触发市态级降级。
    cache 为调用级 dict（_fetch_market_data 单次调用内复用，避免跨请求 stale）。
    """
    if symbol in cache:
        return cache[symbol]
    try:
        items = hub.get_news_stock(symbol) or []
    except Exception:
        items = []
    cache[symbol] = items
    return items


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


def _compute_news_direction(data: dict) -> float | None:
    """News sentiment direction: ratio of positive news in recent items."""
    items = data.get("news_items", [])
    if len(items) < 3:
        return None
    positive = sum(1 for it in items if it.get("level") in ("利好", "重大"))
    total = len(items)
    return positive / max(total, 1)


# ── KDJ 指标 (via pandas-ta) ─────────────────────────────────────
def _compute_kdj_k(data: dict) -> float | None:
    """technical.kdj.k_value: KDJ K 值 (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 9:
        return None
    result = ta.kdj(high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), k=9, d=3)  # type: ignore[arg-type]
    if result is None or result.empty:
        return None
    k_col = "K_9_3"
    val = result[k_col].iloc[-1]
    return float(val) if not pd.isna(val) else None


def _compute_kdj_d(data: dict) -> float | None:
    """technical.kdj.d_value: KDJ D 值 (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 9:
        return None
    result = ta.kdj(high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), k=9, d=3)  # type: ignore[arg-type]
    if result is None or result.empty:
        return None
    d_col = "D_9_3"
    val = result[d_col].iloc[-1]
    return float(val) if not pd.isna(val) else None


def _compute_kdj_j(data: dict) -> float | None:
    """technical.kdj.j_value: KDJ J 值 (via pandas-ta)"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 9:
        return None
    result = ta.kdj(high=pd.Series(high), low=pd.Series(low), close=pd.Series(close), k=9, d=3)  # type: ignore[arg-type]
    if result is None or result.empty:
        return None
    j_col = "J_9_3"
    val = result[j_col].iloc[-1]
    return float(val) if not pd.isna(val) else None


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
        # R148: 改用 1.0/(1+len(concepts)) 单调递减归一（旧 1.0/max(n,1) 在 n=1,2
        # 时返 1.0/0.5 二元分布，候选池 1/1/2/2 时 O20 判 constant）。
        # n=0 保持返 0.0（兼容 round7 O20 P20-③ 契约：空 concepts 是"无信息中性"
        # 而非"极不分散"，避免 N 个空 concepts 标的返 N 个 1.0 仍判 constant）。
        concepts = data.get("concepts") or []
        if not concepts:
            return 0.0
        n = len(concepts)
        return round(1.0 / (1 + n), 4)

    total = sum(industry_holdings.values())
    if total <= 0:
        return 0.0
    hhi = sum((w / total) ** 2 for w in industry_holdings.values())
    return round(hhi, 4)


def _compute_change_pct(data: dict) -> float | None:
    """日涨跌幅：(close[-1] - close[-2]) / close[-2]。来源：Sina K-line 数据。"""
    closes = data.get("close", [])
    if len(closes) >= 2:
        return round((closes[-1] - closes[-2]) / closes[-2], 4)
    return None


def _compute_return_1m(data: dict) -> float | None:
    """近1月收益率：(close[-1] - close[-21]) / close[-21]，约20个交易日。"""
    closes = data.get("close", [])
    if len(closes) >= 21:
        return round((closes[-1] - closes[-21]) / closes[-21], 4)
    if len(closes) >= 2:
        return round((closes[-1] - closes[0]) / closes[0], 4)
    return None


def _compute_return_3m(data: dict) -> float | None:
    """近3月收益率：(close[-1] - close[-61]) / close[-61]，约60个交易日。"""
    closes = data.get("close", [])
    if len(closes) >= 61:
        return round((closes[-1] - closes[-61]) / closes[-61], 4)
    if len(closes) >= 2:
        return round((closes[-1] - closes[0]) / closes[0], 4)
    return None


def _compute_price(data: dict) -> float | None:
    """最新价格：优先使用实时价格，fallback到K线最新收盘价。来源：Sina实时 / K-line。"""
    price = data.get("price")
    if price is not None and price > 0:
        return price
    closes = data.get("close", [])
    if closes and closes[-1] > 0:
        return closes[-1]
    return None


# --- 已注册在用（round11 P2-7 复核：下列函数均在 _FACTOR_FUNCTIONS 注册并参与计算） ---
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
    import math
    import statistics
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


# ── 宏观环境因子（round13 §3.1 P2，MARKET_LEVEL 类，不参与截面 IC）──
# 数据来源：_fetch_market_data 注入的 data["macro_snapshot"]（fetch_macro_snapshot，
# 24h 缓存）+ data["macro_gdp_series"]（fetch_gdp_series，季频序列）。
# 定位：环境/市态维度慢变量——只做市态/组合层输入，不参与盘中高频决策；
# 前视偏差红线：只用已发布值 + as_of 时间戳标注。

def _compute_macro_m2_trend(data: dict) -> float:
    """macro.m2_trend: M2 同比 3 月斜率方向（-1/0/+1），货币松紧趋势（月频）。"""
    snap = data.get("macro_snapshot") or {}
    d = snap.get("m2_direction")
    return float(d) if isinstance(d, (int, float)) else 0.0


def _compute_macro_pmi_level(data: dict) -> float:
    """macro.pmi_level: PMI ≥50 → 1，<50 → 0（荣枯线水平，月频）。"""
    snap = data.get("macro_snapshot") or {}
    v = snap.get("pmi_value")
    if v is None:
        return 0.0
    try:
        return 1.0 if float(v) >= 50 else 0.0
    except (ValueError, TypeError):
        return 0.0


def _compute_macro_lpr_direction(data: dict) -> float:
    """macro.lpr_direction: LPR 1Y 同比方向（-1/0/+1），降息周期=+1（月频）。"""
    snap = data.get("macro_snapshot") or {}
    d = snap.get("lpr_direction")
    return float(d) if isinstance(d, (int, float)) else 0.0


def _compute_macro_gdp_trend(data: dict) -> float:
    """macro.gdp_trend: GDP 同比增速分位 → 环境分级 -1/0/+1（季频，一年仅 4 点）。

    高于 75 分位 → +1（经济强劲）；低于 25 分位 → -1（走弱）；样本 <4 → 0（诚实降级）。
    """
    series = data.get("macro_gdp_series") or []
    if len(series) < 4:
        return 0.0
    try:
        arr = np.asarray([float(x) for x in series], dtype=float)
    except (ValueError, TypeError):
        return 0.0
    p25, p75 = np.percentile(arr, [25.0, 75.0])
    cur = arr[-1]
    if cur > p75:
        return 1.0
    if cur < p25:
        return -1.0
    return 0.0


def _compute_macro_margin_leverage_trend(data: dict) -> float:
    """macro.margin_leverage_trend: 两融杠杆资金情绪（日频数据，环境定位）。

    沪深融资余额合计 20 日变化率：>+0.05 → +1（杠杆流入/风险偏好升）；
    <-0.05 → -1（杠杆流出/风险偏好降）；中间/缺失 → 0。
    与 sentiment 因子互补（杠杆资金为经典风险偏好代理）。不参与盘中决策。
    读取：优先 data["macro_snapshot"]["margin_leverage_*"]（注入路径），
    兜底 data["margin_leverage_*"]（测试/直传路径）。
    """
    snap = data.get("macro_snapshot") or {}
    direction = snap.get("margin_leverage_direction")
    change = snap.get("margin_leverage_change")
    if direction is None:
        direction = data.get("margin_leverage_direction")
    if change is None:
        change = data.get("margin_leverage_change")
    if direction is not None:
        return float(direction)
    if change is None:
        return 0.0
    try:
        c = float(change)
    except (ValueError, TypeError):
        return 0.0
    return 1.0 if c > 0.05 else (-1.0 if c < -0.05 else 0.0)


def _compute_stock_divergence(data: dict) -> float:
    """Stock return divergence: use advance/decline ratio from market data.

    When AD ratio < 0.5 (more decliners), divergence is negative (panic).
    When AD ratio > 1.5 (more advancers), divergence is positive (greed).
    Normalized to -1.0 ~ 1.0 range with neutral at AD=1.0.

    R75: advance_decline 由 compute() 经 _cached_advance_decline() 单次非阻塞获取后
    注入 data，本函数只读取，不再触网/阻塞事件循环。
    """
    ad = data.get("advance_decline")
    if ad is not None and ad > 0:
        # AD=1.0 → 0, AD=0.5 → -0.5, AD=2.0 → +0.5
        return min(max((ad - 1.0) * 2.0, -1.0), 1.0)
    return 0.0


# ── Mapping of factor code → compute function ─────────────────────

_BUILTIN_COMPUTERS: dict[str, Callable[[dict], float | None]] = {
    "style.size.ln_mcap": _compute_ln_mcap,
    "style.size.ln_float_mcap": _compute_ln_float_mcap,
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
    # Macro environment (round13 §3.1 P2, MARKET_LEVEL 类)
    "macro.m2_trend": _compute_macro_m2_trend,
    "macro.pmi_level": _compute_macro_pmi_level,
    "macro.lpr_direction": _compute_macro_lpr_direction,
    "macro.gdp_trend": _compute_macro_gdp_trend,
    "macro.margin_leverage_trend": _compute_macro_margin_leverage_trend,
    # KDJ (2026-07-20 从 indicators.py 注册)
    "technical.kdj.k_value": _compute_kdj_k,
    "technical.kdj.d_value": _compute_kdj_d,
    "technical.kdj.j_value": _compute_kdj_j,
    # 综合信号 (2026-07-20 从 signal.py 注册)
    "technical.signal.overall": _compute_signal_overall,
}

# F3-4 步骤D: etf_specific 四因子的数据源缺口键（factors/active no_data reason 区分用）
ET_SPECIFIC_GAP_CODES = {
    "etf.premium_discount": "nav",
    "etf.tracking_error": "benchmark_close",
    "etf.shares_change": "shares_change_20d",
    "etf.institutional_holdings_change": "shares_change_20d/institutional_holdings_change",
    # O20 (round7 §7 P20-③): industry_diversification 依赖 concepts 标签——
    # 上游 concepts 为空时 reason 走「数据源未接入（缺 concepts）」而非「IC 未累积」
    "etf.industry_diversification": "concepts",
    # O25 (round8 §7 P6-新): sentiment 三因子缺口键——此前不在任何缺口集合，
    # no_data reason 落「IC 未累积（样本 <3）」兜底，无法区分「数据源未接入」。
    "sentiment.panic_greed_diff": "sentiment_index/sentiment_history",
    "sentiment.stock_divergence": "advance_decline",
    "sentiment.news_direction": "news_items/news_scope",
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
    # Macro environment (round13 §3.1 P2, MARKET_LEVEL 类——static 标注不参与 IC)
    "macro.m2_trend",
    "macro.pmi_level",
    "macro.lpr_direction",
    "macro.gdp_trend",
    "macro.margin_leverage_trend",
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


def _fetch_history_budget(n_symbols: int) -> float:
    """fetch_history gather 整体预算：单任务 25s × N / 8 并发 + 15s 缓冲，下限 30s。

    F23 (round6 §17.2): 防止单个 mootdx socket 卡死把 gather 挂到无限——
    整体 wait_for 保证最坏情况在预算内返回（线程残留由 R6-F1 mootdx 修复联动缓解）。
    """
    return max(30.0, 25.0 * n_symbols / 8 + 15.0)


# ── O18 (round7 §7 P20-①): IOPV 三级降级链（Sina http → QQ http → 东财 https）──
# Sina/QQ 均为 http 明文接口（用户环境 http 可能被禁/被墙 → 全失败）；
# 东财 https（EM_PUSH_HOST push2delay）作为第三顺位（不替换现有降级链）。
# 模块级定义（可单测）；TTJ 日净值由 _fetch_market_data 调用方保持末位兜底。

def _http_get_sync(url: str, headers: dict | None = None,
                   encoding: str = "utf-8", errors: str = "replace") -> str:
    """同步 HTTP GET（urllib.request），超时 8s（round11 P1-3：统一 IOPV 三源拉取样板）。

    三处 IOPV 源（新浪/腾讯/东财）原先各自内联 `urllib.request` + urlopen + decode，
    仅 URL/header/编码不同——参数化收敛。失败/超时抛异常由调用方 run_sync 包裹。
    """
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {})
    resp = urllib.request.urlopen(req, timeout=8)
    return resp.read().decode(encoding, errors=errors)


def _iopv_sina_symbols(symbols: list[str]) -> list[str]:
    """A 股 symbol → 新浪/QQ 带市场前缀（sh/sz）。"""
    prefixes = {"5": "sh", "6": "sh", "0": "sz", "1": "sz", "3": "sz"}
    return [f"{prefixes.get(s[0], 'sh')}{s}" for s in symbols]


async def _fetch_iopv_from_sina(s_list: list[str]) -> dict[str, dict]:
    """通过线程池获取新浪实时行情（仅 price；round9 P0-6：实测 sina 实时接口 34 字段无 IOPV）。

    round9 实测（2026-08-07）：`hq.sinajs.cn` 对 ETF 返回 34 字段，[0]=名称 [1]=今开
    [2]=昨收 [3]=当前价 [4]=最高 [5]=最低 [6]=买一 [7]=卖一 [8]=成交量 [9]=成交额
    ... [30]=日期 [31]=时间 [32]=状态——**无 IOPV/净值字段**。旧实现 `parts[2]` 当 symbol
    （实为昨收价）、`parts[8]` 当 nav（实为成交量）双错位 → 解析 key/值全错、永不命中。
    修复：symbol 从行前缀 `var hq_str_(\\w+)` 提取；仅提供 price，nav 不提供
    （链命中判定 nav>0 自然跳过本级，IOPV/净值交由 QQ pos 81 / 东财 f236 / TTJ 日净值）。
    """
    from ..core.async_utils import run_sync

    url = f"http://hq.sinajs.cn/list={','.join(s_list)}"
    raw = await run_sync(
        lambda: _http_get_sync(url, {"Referer": "http://finance.sina.com.cn"}, encoding="gbk", errors="strict"),
        timeout=10,
    )
    parsed: dict[str, dict] = {}
    for line in raw.strip().split("\n"):
        # symbol 从行前缀提取：`var hq_str_sh510050="..."`（round9 P0-6: 修复旧 parts[2] 错位）
        m = re.match(r"var\s+hq_str_([a-zA-Z]+\d{6})\s*=", line)
        if not m:
            continue
        sym = m.group(1)
        if '"' not in line:
            continue
        parts = line.split('"')[1].split(",")
        if len(parts) < 10:
            continue
        try:
            price = float(parts[3]) if parts[3] else None
            parsed[sym] = {"price": price or 0.0}
        except (ValueError, IndexError):
            pass
    return parsed


async def _fetch_iopv_from_qq(s_list: list[str]) -> dict[str, dict]:
    """S8: 腾讯 QQ 行情作为 Sina IOPV 的降级源（round9 P0-6 修复后为主 nav 源）。

    QQ 格式: v_sh510050="1~510050~50ETF~...~price~...~unit_nav..."（~分隔，88 字段）。
    round9 实测（2026-08-07）：
      pos 3 = current price（现价）、pos 31 = 涨跌额（旧注释"IOPV"错误）、pos 32 = 涨跌幅；
      **pos 81 = 单位净值**——与天天基金 f10/lsjz 的 DWJZ 完全一致（510050: 3.0687 双双命中），
      是盘中可用的可靠 NAV 源（折溢价率分子/分母口径）。
    修复：①`decode("gbk")`（旧 utf-8 遇 GBK 中文抛 UnicodeDecodeError 被整级吞掉）；
          ②nav 改用 pos 81（需 len>=82 字段）；③price 用 pos 3。
    """
    from ..core.async_utils import run_sync

    qq_symbols = ",".join(s_list)
    url = f"http://qt.gtimg.cn/q={qq_symbols}"
    # round9 P0-6: GBK 解码（返回体含中文名称，utf-8 解码必崩）
    raw = await run_sync(
        lambda: _http_get_sync(url, {"User-Agent": "Mozilla/5.0"}, encoding="gbk"),
        timeout=10,
    )
    parsed: dict[str, dict] = {}
    for line in raw.strip().split("\n"):
        if "~" not in line or '"' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 82:
            continue
        try:
            code = parts[2] if len(parts) > 2 else ""
            if not code:
                continue
            price_str = parts[3] if len(parts) > 3 and parts[3] else ""
            nav_str = parts[81] if len(parts) > 81 and parts[81] else ""
            price = float(price_str) if price_str else None
            nav = float(nav_str) if nav_str else None
            if nav and nav > 0:
                parsed[code] = {"price": price or 0.0, "nav": nav}
        except (ValueError, IndexError):
            pass
    return parsed


async def _fetch_iopv_from_em(s_list: list[str]) -> dict[str, dict]:
    """O18: 东财 push2 https 行情 f236 源（round9 P0-6: 实测 f236 常为 "-"/0，仅极偶然兜底）。

    ulist.np/get JSON: data.diff[] → f12=code, f2=price, f236=IOPV。
    东财 secid: 1=沪市 0=深市（5/6 开头沪，0/1/3 深）。
    round9 实测（2026-08-07）：push2 对容器/高频请求 RemoteDisconnected（用 push2delay 降级）；
    clist/get 与 ulist.np/get 的 f236 返回值均为 "-"（fltt=2）或 0（无 fltt）——东财公开行情
    接口实际不暴露可用 IOPV，本级的正数校验保证无效值不误收，真正 NAV 源为 QQ pos 81 / TTJ 日净值。
    """
    from ..core.async_utils import run_sync
    from ..core.market_context import EM_PUSH_HOST

    secids = []
    for s in s_list:
        market = "1" if s[0] in ("5", "6") else "0"
        secids.append(f"{market}.{s}")
    url = (
        f"https://{EM_PUSH_HOST}/api/qt/ulist.np/get"
        f"?secids={','.join(secids)}&fields=f12,f13,f2,f236"
        f"&fltt=2&invt=2"
    )
    raw = await run_sync(
        lambda: _http_get_sync(url, {"User-Agent": "Mozilla/5.0"}),
        timeout=10,
    )
    parsed: dict[str, dict] = {}
    if not raw:
        return parsed
    try:
        import json
        payload = json.loads(raw)
        diff = ((payload.get("data") or {}).get("diff")) or []
        for row in diff:
            code = str(row.get("f12", "") or "")
            price = row.get("f2")
            iopv = row.get("f236")
            if not code:
                continue
            try:
                price_f = float(price) if price not in (None, "-") else None
                iopv_f = float(iopv) if iopv not in (None, "-") else None
            except (ValueError, TypeError):
                continue
            if iopv_f and iopv_f > 0:
                parsed[code] = {"price": price_f or 0.0, "nav": iopv_f}
    except Exception as e:
        logger.debug("[factor] EM IOPV parse failed: %s", e)
    return parsed


async def _fetch_iopv_chain(s_list: list[str], symbols: list[str]) -> tuple[dict[str, dict], str]:
    """O18: IOPV 降级链——Sina → QQ → 东财 https，任一命中足够样本即停。

    返回 (iopv_data, source_name)；全失败返回 ({}, "")（调用方走 TTJ 日净值兜底）。
    """
    try:
        sina_data = await _fetch_iopv_from_sina(s_list)
        if sum(1 for v in sina_data.values() if v.get("nav", 0) > 0) >= len(symbols) * 0.3:
            return sina_data, "sina"
    except Exception as e:
        logger.debug("[factor] Sina IOPV failed: %s", e)
    try:
        qq_data = await _fetch_iopv_from_qq(s_list)
        if sum(1 for v in qq_data.values() if v.get("nav", 0) > 0) >= len(symbols) * 0.3:
            return qq_data, "qq"
    except Exception as e:
        logger.debug("[factor] QQ IOPV failed: %s", e)
    try:
        em_data = await _fetch_iopv_from_em(s_list)
        if em_data:
            logger.info("[factor] EM https IOPV fallback got %d values (O18)", len(em_data))
            return em_data, "em"
    except Exception as e:
        logger.debug("[factor] EM IOPV failed: %s", e)
    return {}, ""


async def _inject_nav(market_data: dict[str, dict[str, Any]], symbols: list[str]) -> dict[str, dict[str, Any]]:
    """R146: 把 IOPV chain + TTJ 日净值兜底的 nav 注入逻辑提取为公共方法。

    原逻辑只存在于 _fetch_market_data（DEPRECATED fallback），生产链路
    （refresh_pool → compute(market_data=cached_kline)）走 market_data 分支、
    跳过该函数 → nav 永不注入 → premium_discount 恒 0.0。提取后在
    _fetch_market_data 与 compute() market_data 分支两处复用。
    直接就地把 nav/price 写入 market_data[sym]，并返回 market_data。
    """
    try:
        sina_list = _iopv_sina_symbols(symbols)
        # O18: Sina → QQ → 东财 https 降级链（模块级实现，可单测）；
        # 全失败时 iopv_data={} → 下方走 TTJ 日净值兜底
        iopv_data, _iopv_source = await _fetch_iopv_chain(sina_list, symbols)
        if not iopv_data:
            logger.info('[factor] IOPV chain exhausted (sina/qq/em all failed), relying on TTJ daily nav fallback')

        for sym, values in iopv_data.items():
            if sym in market_data and values.get('nav', 0) > 0:
                market_data[sym].setdefault('price', values.get('price', 0))
                market_data[sym]['nav'] = values.get('nav', 0)
    except Exception as e:
        logger.warning('[factor] batch NAV fetch failed: %s (proxy? — non-fatal)', e)

    # F3-4 步骤A: IOPV 命中率不足 → 天天基金日频净值降级（收盘折溢价口径，不回退 0.0 假数据）
    _missing_nav = [s for s in symbols if not (market_data.get(s) or {}).get("nav")]
    if _missing_nav:
        import asyncio
        from ..core.async_utils import run_sync_long
        from ..services.market_data_hub import market_data_hub as _hub
        # U7/N08 R2: NAV 拉取并发（旧串行 for 循环）；fetch_fund_nav 已有
        # 24h 缓存（U7 R3），并发 + 缓存使预热期累计 7.5s → ~1 次真实请求
        #
        # round42 A+B (lifespan 5.62s lag 根因修复): 把 NAV 兜底从 _shared_executor
        # (64 worker, 主请求共用) 切到 _long_running_executor (8 worker, 隔离池)——
        # 1618 任务不再侵占主线程池, 事件循环 lag 峰值从 5.6s 降至 < 1s。
        # 同时加 Semaphore(8) 限制在飞任务数（防止 1618 任务同时在飞爆内存/连接）。
        # timeout 6→3s（NAV 兜底是 best-effort, 与设计请求 15/30/75s 预算不冲突）。
        _nav_sem = asyncio.Semaphore(8)

        async def _nav_one(_sym: str) -> None:
            try:
                async with _nav_sem:
                    # round9 P0-7: fetch_fund_nav 契约统一为 dict（旧 tuple 被 .get 抛 AttributeError
                    # 吞掉 → 兜底永远静默失败）；此处加 isinstance 守卫兜住历史形态
                    _nav = await run_sync_long(_hub.get_fund_nav, _sym, timeout=3)
                if isinstance(_nav, dict) and _nav.get("nav"):
                    market_data.setdefault(_sym, {})["nav"] = _nav["nav"]
                elif isinstance(_nav, tuple) and len(_nav) >= 1 and _nav[0]:
                    market_data.setdefault(_sym, {})["nav"] = _nav[0]
            except Exception:
                pass

        await asyncio.gather(*[_nav_one(s) for s in _missing_nav])

    return market_data


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
        self._computers: dict[str, Callable[[dict], float | None]] = dict(_BUILTIN_COMPUTERS)
        self._last_ic_batch: dict[str, float] = {}
        # Z03: 因子健康度元数据（sample_count / 最后计算时间）
        self._sample_counts: dict[str, int] = {}
        self._last_computed_at: str | None = None
        # F3-4 步骤D: 最近一次 _fetch_market_data 的 etf_specific 数据源缺口
        # （factor_code -> [缺失字段的 symbol 列表]；供 factors/active no_data reason 区分）
        self._data_source_gaps: dict[str, list[str]] = {}
        # R100 (round32): 最近一次 compute() 实际产出（非 None 数值）的因子键数——
        # factor_code -> 产出的 symbol 数。factor_data_quality 的「数据可用性」统计
        # 以此为准（对齐 factor_breakdown 真实值），而非定义层 _data_source_gaps。
        self._last_compute_produced: dict[str, int] = {}
        # O20: 常量因子 code 集合（截面 std=0 → IC 无法计算）——
        # factors/active reason 独立标注「截面无差异（常量输出）」，
        # 与「数据源未接入」「IC 未累积」三分
        self._constant_factor_codes: set[str] = set()
        # round15 方案三阶段一: 各因子近 N 批 IC 序列内存缓存（refresh_ic_series 刷新，
        # aggregate_factor_scores 读——IC 加权聚合用；未加载/冷启动回退等权）
        self._ic_series_cache: dict[str, list[float]] = {}
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
                direction=int(item.get("direction", 1)),
                neutral_value=item.get("neutral_value"),
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
        definitions: dict[str, "FactorDefinition"] | None = None,
        ic_series: dict[str, list[float]] | None = None,
    ) -> dict[str, float]:
        """B1 + A1 (round23 §10.1): 将点分键聚合为顶层分类键。

        逻辑已下沉 `core/factor_aggregate.aggregate_factor_scores`（engine 纯函数层
        可依赖 core 而无需 import 本模块）——本方法保留为兼容委托（静态调用路径不变）。

        聚合策略：对每个顶层分类，取下属所有因子值的均值；聚合前先按
        FactorDefinition.direction/neutral_value 方向化 + IC 衰减加权（详见 core 实现）。
        """
        from ..core.factor_aggregate import aggregate_factor_scores as _agg
        return _agg(factor_scores, definitions, ic_series)

    def get_factor(self, code: str) -> FactorDefinition | None:
        """Get a single factor definition by code."""
        return self._factors.get(code)

    def register_computer(self, code: str, fn: Callable[[dict], float | None]) -> None:
        """Register a custom computation function for a factor."""
        self._computers[code] = fn

    async def _inject_macro_data(self, data: dict[str, dict[str, Any]], symbols: list[str]) -> None:
        """round13 §3.1 P2: 注入宏观数据字段（macro_snapshot + GDP 序列 + 两融方向）。

        供 5 个 MARKET_LEVEL 宏观因子（macro.m2_trend / pmi_level / lpr_direction /
        gdp_trend / margin_leverage_trend）读取——全市场单一值，与 sentiment 注入
        同模式（一次注入所有标的）。snapshot 走 fetch_macro_snapshot（24h 缓存）；
        GDP 走 fetch_gdp_series（季频）；两融走 fetch_margin_leverage_snapshot（日频）。
        数据不可用 → 注入 None/[] → compute 输出 0（诚实降级，不编造）。
        """
        import asyncio

        from ..fetchers.macro_fetcher import (
            fetch_gdp_series,
            fetch_macro_snapshot,
            fetch_margin_leverage_snapshot,
        )
        snap = await asyncio.to_thread(fetch_macro_snapshot)
        gdp_series = await asyncio.to_thread(fetch_gdp_series, 8)
        margin = await asyncio.to_thread(fetch_margin_leverage_snapshot)
        for _sym in symbols:
            _d = data.setdefault(_sym, {})
            _d["macro_snapshot"] = snap
            if margin:
                # 两融方向并入 snapshot（margin_leverage_trend compute 读取）
                _snap = dict(snap) if snap else {}
                _snap["margin_leverage_direction"] = margin.get("margin_leverage_direction")
                _snap["margin_leverage_change"] = margin.get("margin_leverage_change")
                _d["macro_snapshot"] = _snap
            if gdp_series:
                _d["macro_gdp_series"] = gdp_series

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
        source_h = _source_registry.health("factor.history")
        now = time.time()
        if not source_h.available(now):
            logger.warning("[factor] SourceRegistry circuit open for factor.history — returning empty data for %s", symbols)
            return {sym: {} for sym in symbols}

        import asyncio

        from ..services.market_data_hub import market_data_hub

        sem = asyncio.Semaphore(8)

        async def fetch_one(sym: str) -> tuple[str, dict[str, Any]]:
            async with sem:
                try:
                    from ..core.async_utils import run_sync
                    # R85 (round30): 先读 hub 已热身 K 线缓存（design-data warmup 填
                    # hub._kline_cache_rows，R59④）——消除「两缓存域断裂」：因子模块
                    # _kline_cache 冷（从未被预热）时不再直接 live fetch（盘后空），
                    # 而是命中 hub 缓存拿到真实 K 线（技术信号路径同款数据源）。
                    rows = market_data_hub.get_kline_rows_any(sym)
                    if not rows:
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
                            # F19 R70: 删除假市值 fallback（1000 亿）——全标的同值 →
                            # z-score std≈0 → ln_mcap 无区分度 → 0 有效。缺数据返回 0，
                            # _compute_ln_mcap 的 mv>0 守卫不会崩，gap 机制标注缺失。
                        ),
                        "float_mv": float(rows[-1].get("float_mv", 0) or 0),
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
        # F23: 整体超时保护——单任务卡死不再把 gather 挂到无限（round6 §17.2 / ROOT_CAUSE.md）
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=_fetch_history_budget(len(symbols)),
            )
        except asyncio.TimeoutError:
            logger.error(
                "[factor] fetch_history overall timeout after %.1fs for %d symbols — "
                "returning empty data (degraded)",
                _fetch_history_budget(len(symbols)), len(symbols),
            )
            results = []
        data = dict(results)

        # 2. 批量获取 IOPV 数据（Sina + QQ + 东财 https 三级降级链，O18）
        # 用于 premium_discount 因子计算 (S8: 腾讯QQ降级链; O18: 东财 https 源)
        # R146: 提取为 _inject_nav 公共方法，与 compute() market_data 分支复用。
        data = await _inject_nav(data, symbols)

        # F3-5: 注入 sentiment 数据字段（panic_greed_diff 用 sentiment_index/history，
        # news_heat / news_direction 用 news_items）——此前只注入到 refresh_pool 的
        # factor_scores，compute 路径拿不到 → 全 0 → 被 IC 过滤 → 永远 no_data。
        try:
            from ..services.market_data_hub import market_data_hub as _hub2
            _sent = _hub2.get_market_sentiment() or {}
            _news = _hub2.get_news_headlines() or []
            for _sym in symbols:
                _d = data.setdefault(_sym, {})
                if _sent.get("sentiment_index") is not None:
                    _d["sentiment_index"] = float(_sent["sentiment_index"])
                if _sent.get("sentiment_history"):
                    _d["sentiment_history"] = _sent["sentiment_history"]
                # F19 R69: 注入 advance_decline（stock_divergence 优先路径），
                # 去掉脆弱的运行时 2s 兜底依赖（fetch_advance_decline）
                if _sent.get("advance_ratio") is not None:
                    _d["advance_decline"] = float(_sent["advance_ratio"])
                # F12 (round6 §15.4): news_heat 按标的新闻注入——旧实现把全市场
                # 新闻写入每个标的 → 所有标的 news_heat 全 100 顶格（无区分度+误导）。
                # 标的新闻可用（get_news_stock）→ news_scope=stock；不可用 →
                # 市态级降级（news_scope=market，全市场热度仅作 regime 输入，
                # 持仓明细展示时须标注"全市场新闻热度，非个股值"）。
                # F12: 无条件尝试标的相关新闻（不可用则市态级降级）
                _stock_cache: dict = {}
                _stock_news: list = []
                try:
                    _stock_news = await asyncio.to_thread(
                        _safe_stock_news, _hub2, _sym, _stock_cache)
                except Exception:
                    _stock_news = []
                if _stock_news:
                    _d["news_items"] = _stock_news[-30:]
                    _d["news_scope"] = "stock"
                else:
                    if _news:
                        _d["news_items"] = _news[-30:]
                    _d["news_scope"] = "market"
        except Exception as _e:
            logger.warning("[factor] sentiment data inject failed: %s", _e)

        # round13 §3.1 P2: 注入 macro 数据字段（4 个宏观因子用）——fetch_macro_snapshot
        # 24h 缓存 + GDP 季频序列，一次注入所有标的（非每标的重复拉取）
        try:
            await self._inject_macro_data(data, symbols)
        except Exception as _e:
            logger.warning("[factor] macro data inject failed: %s", _e)

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

        # F3-4 步骤D + F19 R70: 记录数据源缺口（factors/active no_data reason 区分用）
        self._data_source_gaps = {}
        for _code, _field in ET_SPECIFIC_GAP_CODES.items():
            if _field == "nav":
                _missing = [s for s in symbols if not (data.get(s) or {}).get("nav")]
            elif _field == "benchmark_close":
                _missing = [s for s in symbols if not (data.get(s) or {}).get("benchmark_close")]
            elif _field.startswith("shares_change_20d"):
                _missing = [
                    s for s in symbols
                    if (data.get(s) or {}).get("shares_change_20d") is None
                    and (data.get(s) or {}).get("institutional_holdings_change") is None
                    and not (data.get(s) or {}).get("fund_scale")
                ]
            elif _field == "concepts":
                # O20: industry_diversification 依赖 concepts 标签（或 industry_holdings）
                _missing = [
                    s for s in symbols
                    if not (data.get(s) or {}).get("concepts")
                    and not (data.get(s) or {}).get("industry_holdings")
                ]
            elif _field == "sentiment_index/sentiment_history":
                # O25: panic_greed_diff 依赖市场情绪指数序列
                _missing = [s for s in symbols if not (data.get(s) or {}).get("sentiment_index")]
            elif _field == "advance_decline":
                # O25: stock_divergence 依赖涨跌比（情绪源）
                _missing = [s for s in symbols if not (data.get(s) or {}).get("advance_decline")]
            elif _field == "news_items/news_scope":
                # O25: news_direction 依赖个股级新闻（news_scope=market 时截面无区分度）
                _missing = [
                    s for s in symbols
                    if not (data.get(s) or {}).get("news_items")
                    or (data.get(s) or {}).get("news_scope") != "stock"
                ]
            else:
                _missing = [s for s in symbols if (data.get(s) or {}).get("shares_change_20d") is None]
            if _missing:
                self._data_source_gaps[_code] = _missing
        # F19 R70: style.size.ln_mcap / ln_float_mcap 缺口（total_mv/float_mv 为空即缺失）——
        # 删假市值后 ln_mcap 缺数据时必须落到"数据源未接入"而非模糊的"IC 未累积"
        _mv_missing = [s for s in symbols if not (data.get(s) or {}).get("total_mv")]
        if _mv_missing:
            self._data_source_gaps["style.size.ln_mcap"] = _mv_missing
        _float_mv_missing = [s for s in symbols if not (data.get(s) or {}).get("float_mv")]
        if _float_mv_missing:
            self._data_source_gaps["style.size.ln_float_mcap"] = _float_mv_missing

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
    ) -> dict[str, dict[str, float | None]]:
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
            # round14 P2-Z 修复 1: 外部注入时同样合并 symbol_extra（Z04 同逻辑）——
            # IC 循环传 market_data=_kline_cache（无 benchmark_close/shares_change_20d），
            # 不合并则 tracking_error/shares_change 对每只 ETF 恒 0.0 → IC 永不产生
            #（docs/archived/round14 §2.11）。注意：market_data 实为 _kline_cache 引用，merge
            # 会就地写回共享缓存——asyncio 单线程无并发撕裂，且「不覆盖已有字段」
            # 语义与 Z04 一致（无害）。
            if symbol_extra:
                for sym in symbols:
                    if sym in market_data and sym in symbol_extra:
                        extra = symbol_extra[sym]
                        for key in ("industry", "concepts", "benchmark_close",
                                    "shares_change_20d", "institutional_holdings_change",
                                    "shares_change", "fund_scale"):
                            if key in extra and key not in market_data[sym]:
                                market_data[sym][key] = extra[key]
            # R146: market_data 分支（生产 refresh_pool 路径）也注入 nav —— 原 nav
            # IOPV 链只在 _fetch_market_data（DEPRECATED fallback）里，此处跳过导致
            # premium_discount 恒 0.0。复用 _inject_nav 公共方法。
            await _inject_nav(market_data, symbols)
        else:
            market_data = await self._fetch_market_data(symbols, symbol_extra=symbol_extra)

        # R75 修复: 单次非阻塞获取 advance_decline（TTL 缓存），注入每只 symbol 的 data，
        # 替代原 _compute_stock_divergence 内同步 run_in_thread 阻塞事件循环。
        _ad = await _cached_advance_decline()

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

        result: dict[str, dict[str, float | None]] = {}
        _data_sources: dict[str, str] = {}
        for sym in symbols:
            row: dict[str, float | None] = {}
            data = market_data.get(sym, {}) if market_data else {}

            # Phase 2.7.4: 缓存降级 (P0-C round10) — data 为空或采集失败
            # （{"_fetch_error": ..} / 无 close / 全 0 占位）时，降级到上次成功的
            # K 线缓存（_kline_cache 仅有成功时写入），并记录 data_source 标注。
            _live_usable = isinstance(data, dict) and (
                data.get("close")
                or any(k in data for k in ("open", "high", "low"))
            ) and "_fetch_error" not in data
            if not _live_usable:
                stale = _get_cached_kline([sym])
                if stale and sym in stale:
                    logger.warning(
                        "[factor] compute() — using stale cache for %s (live data unusable: %s)",
                        sym, "_fetch_error" in data if data else "empty",
                    )
                    data = stale[sym]
                    _data_sources[sym] = "stale"
                else:
                    _data_sources[sym] = "unavailable"

            # R75: 注入 advance_decline（全市场共用，已单次获取），避免每只 symbol 同步阻塞。
            # 不就地改写共享 K 线缓存，用副本注入。
            if _ad is not None and "advance_decline" not in data:
                data = {**data, "advance_decline": _ad}

            for code in codes:
                computer = self._computers.get(code)
                if computer is None:
                    continue
                try:
                    raw_value = computer(data)
                    definition = self._factors.get(code)
                    # R85 (round30): 缺数据 None 保留（不再转 0.0 占位冒充「真实 0」）——
                    # 下游 z-score 跳过 None、展示层 _factor_value_real 判 False 标缺失。
                    row[code] = raw_value
                except Exception as e:
                    logger.debug("Factor %s failed for %s: %s", code, sym, e)
                    row[code] = None

            result[sym] = row

        # P0-C (round10 §3.2 根因): 数据源状态冒泡到调用方——`data_source` 键标注
        # stale（缓存兜底）或 unavailable（无缓存冷启动全空），供报告层明示
        # 「数据源不可用」而非假装有数据。
        for _sym, _src in _data_sources.items():
            result[_sym] = {**result[_sym], "data_source": _src}  # type: ignore[dict-item]

        # ── 跨符号 z-score 标准化（用临时 dict 存储原始值） ──
        import statistics
        # R6-F4 (round6 §十 R6-05): 报告展示用因子保留原始值（RSI 0-100 / MACD DIF），
        # 供 rationale 展示真实指标——zscore 值被当原始 RSI 展示是数值失真根因（§十八-7）。
        _RAW_KEEP = {"technical.macd.macd"}  # R6-F4: macd 为 zscore，需保留真实 DIF；rsi_14 已是 raw
        _raw: dict[str, list[tuple[str, float | None]]] = {}
        for code in codes:
            definition = self._factors.get(code)
            if not definition or definition.standardization not in ("zscore", "zscore_large"):
                continue
            _raw[code] = []
            for sym in symbols:
                val = result.get(sym, {}).get(code)
                _raw[code].append((sym, val))
            # R6-F4: 原始值保留与样本数无关（单符号等场景标准化被跳过时 raw 仍可用）
            if code in _RAW_KEEP:
                for _sym, _val in _raw[code]:
                    result[_sym][f"{code}_raw"] = _val
            # R85 (round30): 跳过 None/非数值（缺数据）参与均值/方差——None 值符号
            # 保持 None（展示层标缺失），不再因 None 参与统计导致 std 计算崩溃。
            all_v = [v for _, v in _raw[code] if isinstance(v, (int, float))]
            if len(all_v) < 2:
                continue
            mean_v = statistics.mean(all_v)
            std_v = statistics.stdev(all_v)
            if std_v < 1e-10:
                # O20: 截面无差异（全 0/常量输出）→ IC 无法计算——记录常量因子，
                # factors/active reason 独立标注「截面无差异（常量输出）」
                self._constant_factor_codes.add(code)
                continue
            # ── 混合归一化（Solution Design S2） ──
            # z-score（统计异常度）* 0.7 + min-max（相对排名）* 0.3
            # 保证即使 z-score 全负，顶部标的仍得正分
            all_vals = [v for v in all_v if v == v]  # 排除 NaN
            min_v = min(all_vals)
            max_v = max(all_vals)
            mm_range = max_v - min_v
            for sym, val in _raw[code]:
                if not isinstance(val, (int, float)):
                    continue  # None/非数值符号保持 None（R85 缺数据诚实标注）
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
                z_vals_raw = [result[sym][code] for sym, _ in _raw[code]
                              if isinstance(result[sym][code], (int, float))]
                z_vals: list[float] = cast("list[float]", z_vals_raw)
                if len(z_vals) < 2:
                    continue
                min_z, max_z = min(z_vals), max(z_vals)
                if max_z - min_z > 1e-10:
                    for sym, _ in _raw[code]:
                        _v = result[sym].get(code)
                        if isinstance(_v, (int, float)):
                            result[sym][code] = (_v - min_z) / (max_z - min_z)

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
                # R58（round28 延伸）: 数据源异常时 factor computer 可能返回 str（而非
                # float），abs(str) → TypeError，整批 IC 回填失败（round28 实测
                # 「bad operand type for abs(): 'str'」）。防御性 isinstance 守卫。
                if macd_val is not None and isinstance(macd_val, (int, float)) \
                        and abs(macd_val) > 0.001:
                    enriched["macd"] = macd_val
                # R85 (round30): sma20 缺数据为 None——isinstance 守卫防 TypeError
                if isinstance(sma20, (int, float)) and sma20 != 0 and last_close and last_close > 0:
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
                        # R58（round28 延伸）: 数据源异常时 value 可能为 str，
                        # abs(str) → TypeError。非数值跳过（不记录 IC）。
                        # FS1 (round35 §15.6): 阈值判定收敛单点 core.factor_values。
                        # （isinstance 显式前置供 mypy 窄化。）
                        if isinstance(value, (int, float)) and is_meaningful_value(code, value):
                            ic_tracker.record(sym, code, value)
        except Exception as e:
            # P0 fix-plan-master: bare except was silently swallowing errors
            logger.warning("[factor] IC tracking record failed (non-fatal): %s", e)

        # Compute periodic IC for current batch
        try:
            if market_data is not None:
                ic_batch = ic_tracker.compute_periodic_ic(result, market_data, window=1)
                # U3/N06: 防全 0 覆盖——过滤 None 值；仅当新批次含任一有效 IC
                # （abs(val) > 0.001）才覆盖 _last_ic_batch，否则保留旧值 + WARNING。
                # 旧代码无条件覆盖：常量输入批次返回全 0 dict → 永久丢失有效 IC（Z06）。
                if ic_batch:
                    # R58（round28 延伸）: 数据源异常时 factor value 可能是 str（而非
                    # float），abs(str) → TypeError。防御性过滤：仅保留数值。
                    valid_entries = {
                        code: val for code, val in ic_batch.items()
                        if val is not None
                        and isinstance(val, (int, float))
                        and not (isinstance(val, float) and val != val)
                    }
                    has_signal = any(abs(v) > 0.001 for v in valid_entries.values())
                    if has_signal:
                        self._last_ic_batch = valid_entries
                        # Z03: 记录样本数与最后计算时间（供 /factors/active 健康度展示）
                        from datetime import datetime
                        from datetime import timezone as _tz
                        self._last_computed_at = datetime.now(_tz.utc).isoformat()
                        self._sample_counts = {
                            code: sum(
                                1 for sym in result
                                if isinstance((result[sym].get(code) or 0), (int, float))
                                and abs((result[sym].get(code) or 0)) > 0.001
                            )
                            for code in valid_entries
                        }
                        # B3: IC threshold alerts
                        for code, ic_val in valid_entries.items():
                            definition = self._factors.get(code)
                            if definition and 0 < abs(ic_val) < definition.ic_threshold:
                                logger.warning(
                                    "[factor] IC below threshold for %s: ic=%.4f < threshold=%.4f",
                                    code, ic_val, definition.ic_threshold,
                                )
                    else:
                        logger.warning(
                            "[factor] IC batch has no valid signal (all 0/None), "
                            "keeping previous _last_ic_batch (%d entries)",
                            len(self._last_ic_batch or {}),
                        )
        except Exception as exc:
            logger.debug("[factor] IC batch compute failed: %s", exc)

        # R100 (round32): 记录 compute() 实际产出（非 None 数值）的因子键数——
        # factor_data_quality「数据可用性」统计以此为准（对齐 factor_breakdown 真实值）。
        # 背景：盘后 etf.return_* 未产出（None）但 _data_source_gaps 未标注 → 旧口径
        # 报「97% 可用」掩盖占位退化（设计 697 实证）。此处逐 code 统计非 None 数值的
        # symbol 数，供 _factor_data_quality_report 计算实际产出率。
        try:
            _produced_codes = set(codes or [])
            if signal_code in self._computers:
                _produced_codes.add(signal_code)
            self._last_compute_produced = {
                _code: sum(
                    1 for _sym in symbols
                    if isinstance((result.get(_sym) or {}).get(_code), (int, float))
                )
                for _code in _produced_codes
            }
        except Exception as _exc:
            logger.debug("[factor] produced-key tracking failed (non-fatal): %s", _exc)
            self._last_compute_produced = {}

        return result

    async def restore_ic_from_db(self, session, min_abs: float = 0.001) -> int:
        """R5-1-5: 启动时从 DB 恢复 _last_ic_batch（IC 非请求驱动）。

        /factors/ic 端点只读内存 `_last_ic_batch`，重启后内存态丢失 → IC 空
        （DB 中有历史数据但端点读不到）。本方法读取最近一批 IC 记录回填内存。
        遵循 U3/N06 覆盖保护：仅 abs(val)>0.001 才写入（否则保留空/旧值）。
        """
        from sqlalchemy import select

        from ..models.factor_ic import FactorICRecord

        try:
            rows = (
                await session.execute(
                    select(FactorICRecord)
                    .order_by(FactorICRecord.computed_at.desc())
                    .limit(200)
                )
            ).scalars().all()
        except Exception as exc:
            logger.warning("[factor] IC restore from DB failed: %s", exc)
            return 0

        if not rows:
            return 0

        # 取最近一批（computed_at 最新的记录组）
        latest_ts = rows[0].computed_at
        batch = {
            r.factor_code: float(r.ic_value)
            for r in rows
            if r.computed_at == latest_ts
        }
        valid = {k: v for k, v in batch.items() if abs(v) > min_abs}
        if valid:
            self._last_ic_batch = valid
            # round14 P0-C 配套: 同步恢复最近一批的 sample_count——否则重启后
            # _sample_counts 为空，factors/active 的 IC 最小样本保护会把所有
            # 恢复的 IC 判为「未累积（样本 0 < 30）」，与 DB 历史样本数矛盾。
            restored_samples = {
                r.factor_code: int(getattr(r, "sample_count", 0) or 0)
                for r in rows
                if r.computed_at == latest_ts
            }
            self._sample_counts.update({k: v for k, v in restored_samples.items() if v > 0})
            logger.info("[factor] restored %d IC entries from DB (R5-1-5)", len(valid))
        return len(valid)

    async def refresh_ic_series(self, session, days: int = 20) -> int:
        """round15 方案三阶段一: 从 DB 加载各因子近 `days` 批 IC 序列到内存缓存。

        aggregate_factor_scores 用衰减加权 IC 做顶层键内聚合；IC 样本 < IC_MIN_BATCHES
        视为冷启动回退等权。由 IC 持久化循环（main.py）与启动恢复路径调用。
        失败仅 WARNING，不阻塞（回退等权 = 方案三未启用时的既有行为）。
        """
        from sqlalchemy import select

        from ..models.factor_ic import FactorICRecord

        try:
            rows = (
                await session.execute(
                    select(
                        FactorICRecord.factor_code,
                        FactorICRecord.ic_value,
                        FactorICRecord.computed_at,
                    ).order_by(FactorICRecord.computed_at.desc())
                )
            ).all()
        except Exception as exc:
            logger.warning("[factor] IC series refresh failed: %s", exc)
            return 0

        if not rows:
            self._ic_series_cache = {}
            return 0

        # 取最近 days 批（computed_at 去重后前 days 个时间戳）
        _ts_order: list = []
        for _, _, ts in rows:
            if ts not in _ts_order:
                _ts_order.append(ts)
            if len(_ts_order) >= days:
                break
        allowed = set(_ts_order)

        by_code: dict[str, list[float]] = {}
        # rows 按 computed_at 降序（最新在前）迭代 append；round35 FM1 (§15.3)
        # 构建完成后统一反转为【旧→新】升序——缓存契约 = 旧→新：
        #   · core/factor_aggregate._ic_decay_mean 末位=最新批权重 1.0（此前方向
        #     反转：最旧批拿最大权重，「近因衰减」实为「反近因衰减」）；
        #   · strategy_design fdq `for _v in reversed(_ic)` 首个=最新非 None 值。
        # 两个消费方同时回归各自注释声明的语义。
        for code, val, ts in rows:
            if ts not in allowed:
                continue
            if val is None:
                continue
            by_code.setdefault(code, []).append(float(val))
        for _seq in by_code.values():
            _seq.reverse()
        self._ic_series_cache = by_code
        logger.debug("[factor] refreshed IC series for %d factors (%d batches)", len(by_code), len(_ts_order))
        return len(by_code)


# Global singleton
registry = FactorRegistry()
