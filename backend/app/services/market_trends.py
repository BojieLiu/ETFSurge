"""
趋势数据采集与市场状态判断 (Market Trends & Regime Detection)

为组合设计引擎提供多周期趋势数据和市场状态分类：
  1. compute_etf_trends():   多周期收益率、均线位置、量比、资金流趋势
  2. compute_sector_momentum(): 申万一级行业20日排名变化
  3. detect_market_regime():   综合趋势+宏观判断市场状态

所有外部 API 调用带超时保护，失败时返回结构化空值。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

# ── 公开接口 ──────────────────────────────────────────────────

async def compute_etf_trends(
    symbols: list[str],
    periods: tuple[str, ...] = ("5d", "1m", "3m"),
) -> dict[str, dict[str, float]]:
    """
    为候选 ETF 计算多周期趋势数据。

    返回:
      {code: {
        "return_5d": float,    # 近5日收益率
        "return_1m": float,    # 近1月收益率
        "return_3m": float,    # 近3月收益率
        "ma_bias_20": float,   # 相对20日均线乖离率
        "ma_bias_60": float,   # 相对60日均线乖离率
        "vol_ratio": float,    # 近20日均量 / 近60日均量 (量比)
        "volatility_20d": float, # 20日年化波动率
        "max_drawdown_1m": float, # 近1月最大回撤
      }}
    """
    if not symbols:
        return {}

    # 分批拉取，避免并发过多
    results = {}
    batch_size = 10
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[_fetch_single_trend(sym) for sym in batch],
            return_exceptions=True,
        )
        for sym, res in zip(batch, batch_results):
            if isinstance(res, dict) and res:
                results[sym] = res
            else:
                results[sym] = {}

    return results


async def _compute_industry_momentum(top_n: int = 15) -> list[dict[str, Any]]:
    """计算申万一级行业板块动量（push2delay 直连，绕过 akshare 硬编码 push2 阻断）。

    返回:
      [{sector, sector_code, type:"industry", rank_current, change_pct, main_inflow, up_count, down_count}]

    round27 R46: 旧实现用 akshare `stock_board_industry_name_em`（硬编码 push2.eastmoney.com，
    被 EM 域名级风控 ProxyError 断连）→ live 源失败 → 首启无快照可写（R40 首启空窗）。
    改用项目自有 `fetch_em_industry_sectors`（EM_PUSH_HOST=push2delay，实测 496 行可用），
    live 源恢复正常 → 快照正常写入。push2delay 空时回退 akshare（防御性）。
    """
    # 主源：push2delay 直连（绕过 akshare 的 push2 阻断）
    try:
        from ..fetchers.sector_fetcher import fetch_em_industry_sectors
        rows = fetch_em_industry_sectors(limit=top_n) or []
    except Exception as e:
        logger.warning("[market_trends] fetch_em_industry_sectors failed: %s", e)
        rows = []

    # 防御性兜底：push2delay 也空时回退 akshare（盘后冷却等异常场景）
    if not rows:
        try:
            import akshare as ak
            from ..utils.decode import decode_df
            from ..core.async_utils import run_sync
            df = await run_sync(ak.stock_board_industry_name_em)
            if df is not None and not df.empty:
                decode_df(df)
                rows = [
                    {
                        "sector_name": str(row.get("板块名称", "")),
                        "sector_code": str(row.get("板块代码", "")),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "main_inflow": float(row.get("主力净流入", 0) or 0),
                        "up_count": int(row.get("上涨家数", 0) or 0),
                        "down_count": int(row.get("下跌家数", 0) or 0),
                    }
                    for _, row in df.iterrows()
                ]
        except Exception as e:
            logger.warning("[market_trends] _compute_industry_momentum akshare fallback failed: %s", e)

    current = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        current.append({
            "sector": str(r.get("sector_name", "")),
            "sector_code": str(r.get("sector_code", "")),
            "type": "industry",
            "change_pct": float(r.get("change_pct") or 0),
            "main_inflow": float(r.get("main_inflow") or 0),
            "up_count": int(r.get("up_count") or 0),
            "down_count": int(r.get("down_count") or 0),
        })

    current.sort(key=lambda x: x["change_pct"], reverse=True)  # type: ignore[arg-type,return-value]
    for rank, item in enumerate(current, 1):
        item["rank_current"] = rank

    return current[:top_n]


async def _compute_concept_momentum(top_n: int = 15) -> list[dict[str, Any]]:
    """计算概念板块动量（push2delay 直连，绕过 akshare 硬编码 push2 阻断）。

    返回:
      [{sector, sector_code, type:"concept", rank_current, change_pct, main_inflow, up_count, down_count}]

    round27 R46: 同 `_compute_industry_momentum`，改调项目自有 `fetch_em_concept_sectors`
    （fs=m:90+t:3，push2delay）。akshare `stock_board_concept_name_em` 同样被 push2 阻断。
    """
    try:
        from ..fetchers.sector_fetcher import fetch_em_concept_sectors
        rows = fetch_em_concept_sectors(limit=top_n) or []
    except Exception as e:
        logger.warning("[market_trends] fetch_em_concept_sectors failed: %s", e)
        rows = []

    if not rows:
        try:
            import akshare as ak
            from ..utils.decode import decode_df
            from ..core.async_utils import run_sync
            df = await run_sync(ak.stock_board_concept_name_em)
            if df is not None and not df.empty:
                decode_df(df)
                rows = [
                    {
                        "sector_name": str(row.get("板块名称", "")),
                        "sector_code": str(row.get("板块代码", "")),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "main_inflow": float(row.get("主力净流入", 0) or 0),
                        "up_count": int(row.get("上涨家数", 0) or 0),
                        "down_count": int(row.get("下跌家数", 0) or 0),
                    }
                    for _, row in df.iterrows()
                ]
        except Exception as e:
            logger.warning("[market_trends] _compute_concept_momentum akshare fallback failed: %s", e)

    current = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        current.append({
            "sector": str(r.get("sector_name", "")),
            "sector_code": str(r.get("sector_code", "")),
            "type": "concept",
            "change_pct": float(r.get("change_pct") or 0),
            "main_inflow": float(r.get("main_inflow") or 0),
            "up_count": int(r.get("up_count") or 0),
            "down_count": int(r.get("down_count") or 0),
        })

    current.sort(key=lambda x: x["change_pct"], reverse=True)  # type: ignore[arg-type,return-value]
    for rank, item in enumerate(current, 1):
        item["rank_current"] = rank

    return current[:top_n]


async def compute_sector_momentum(top_n: int = 15) -> list[dict[str, Any]]:
    """计算行业+概念板块动量（各取 top_n/2）。

    返回:
      [{sector, sector_code, type:"industry"|"concept", 
        rank_current, change_pct, main_inflow, up_count, down_count}]
    """
    half = max(1, top_n // 2)
    ind = await _compute_industry_momentum(half)
    con = await _compute_concept_momentum(half)
    # 按涨幅混排
    merged = ind + con
    merged.sort(key=lambda x: x["change_pct"], reverse=True)
    return merged[:top_n]


def detect_market_regime(
    trends: dict[str, dict[str, float]] | None = None,
    broad_index_code: str = "000001",
    sentiment_index: float = 50.0,
    adv_ratio: float = 0.5,
    index_realtime: list[dict] | None = None,  # P0.5: 实时指数兜底
    daily_change_pct: float | None = None,      # P1: 单日涨跌幅 (如 -0.0735 = -7.35%)
    macro: dict | None = None,                  # round13 §3.1 P1: 宏观快照（PMI/M2/LPR 方向）
) -> str:
    """
    基于趋势数据和情绪指标判断当前市场状态。
    当趋势数据为空（外部数据源超时）时，自动降级使用 index_realtime 做判断。

    round13 §3.1 P1: 可选 macro 参数（fetch_macro_snapshot 输出）做宏观修正——
    同向叠加/顺势修正、冲突保持、缺失不动（宏观为辅助非主导）。默认 None，现有调用零影响。

    Args:
        trends: compute_etf_trends() 的输出（含主要宽基）
        broad_index_code: 主要宽基代码（默认上证指数）
        sentiment_index: 情绪指数 0~100
        adv_ratio: 上涨家数占比 0~1
        index_realtime: 实时指数行情快照（P0.5 fallback）
        daily_change_pct: 单日涨跌幅 (如 -0.0735)，优先于多周期趋势判断
        macro: fetch_macro_snapshot() 输出（含 macro_direction -1/0/+1），默认 None

    Returns:
        "bull_strong" / "bull_weakening" / "range_bound" /
        "correction" / "bear" / "defensive_rotate" / "panic"
    """
    core = _detect_regime_core(
        trends=trends,
        broad_index_code=broad_index_code,
        sentiment_index=sentiment_index,
        adv_ratio=adv_ratio,
        index_realtime=index_realtime,
        daily_change_pct=daily_change_pct,
    )
    return _apply_macro_adjustment(core, macro)


# 宏观修正映射：市态 → 进攻/防御倾向等级（-3 恐慌 … +2 强牛）
_MACRO_REGIME_LEVEL = {
    "panic": -3,
    "bear": -2,
    "correction": -1,
    "defensive_rotate": -1,
    "range_bound": 0,
    "bull_weakening": 1,
    "bull_strong": 2,
}
_MACRO_LEVEL_TO_REGIME = {
    -3: "panic",
    -2: "bear",
    -1: "correction",
    0: "range_bound",
    1: "bull_weakening",
    2: "bull_strong",
}


def _apply_macro_adjustment(regime: str, macro: dict | None) -> str:
    """round13 §3.1 P1: 宏观修正（同向叠加/顺势修正、冲突保持、缺失不动）。

    规则（契约 market/macro-regime.md §2.3）:
    - macro 缺失或 macro_direction=0 → 保持现有输出
    - 中性市态（range_bound）+ 宏观方向 → 顺势给倾向（偏下→defensive_rotate，偏上→bull_weakening）
    - 现有市态与宏观同向 → 强化一级（bull_weakening→bull_strong；defensive_rotate/correction→bear；bear→panic）
    - 冲突（方向相反）→ 保持现有输出（宏观不主导日频快变量）
    """
    if not macro:
        return regime
    macro_dir = macro.get("macro_direction", 0)
    if macro_dir == 0:
        return regime
    level = _MACRO_REGIME_LEVEL.get(regime, 0)
    if level == 0:
        return "defensive_rotate" if macro_dir < 0 else "bull_weakening"
    if (level > 0) == (macro_dir > 0):
        return _MACRO_LEVEL_TO_REGIME.get(level + macro_dir, regime)
    return regime


def _detect_regime_core(
    trends: dict[str, dict[str, float]] | None = None,
    broad_index_code: str = "000001",
    sentiment_index: float = 50.0,
    adv_ratio: float = 0.5,
    index_realtime: list[dict] | None = None,  # P0.5: 实时指数兜底
    daily_change_pct: float | None = None,      # P1: 单日涨跌幅 (如 -0.0735 = -7.35%)
) -> str:
    """市态核心判定（不含宏观修正）——由 detect_market_regime 包装调用。"""
    # 默认
    regime = "range_bound"

    # P1: 单日涨跌幅阈值判定 — 优先于多周期趋势，捕捉暴跌/暴涨
    if daily_change_pct is not None:
        if daily_change_pct < -0.05:
            logger.warning(
                "[detect_market_regime] Daily change %.2f%% < -5%% → panic",
                daily_change_pct * 100,
            )
            return "panic"
        if daily_change_pct < -0.03:
            logger.info(
                "[detect_market_regime] Daily change %.2f%% < -3%% → correction",
                daily_change_pct * 100,
            )
            return "correction"
        if daily_change_pct > 0.05:
            logger.info(
                "[detect_market_regime] Daily change %.2f%% > +5%% → bull_strong",
                daily_change_pct * 100,
            )
            return "bull_strong"
        if daily_change_pct > 0.03:
            logger.info(
                "[detect_market_regime] Daily change %.2f%% > +3%% → correction (surge)",
                daily_change_pct * 100,
            )
            return "bull_weakening"

    # 从趋势数据中提取主要信号
    index_trend = (trends or {}).get(broad_index_code, {})

    ret_1m = index_trend.get("return_1m", 0.0)
    ret_3m = index_trend.get("return_3m", 0.0)
    ma_bias_20 = index_trend.get("ma_bias_20", 0.0)

    # 1. 恐慌: 情绪极低 + 普跌
    if sentiment_index < 20 and adv_ratio < 0.3:
        return "panic"

    # 2. 强牛市: 3m收益率>15% 且 情绪>65
    if ret_3m > 0.15 and sentiment_index > 65:
        return "bull_strong"

    # 3. 牛市趋弱: 3m仍正但1m转负
    if ret_3m > 0.05 and ret_1m < -0.03:
        return "bull_weakening"

    # 4. 防御轮动: 情绪偏弱 + 指数在均线下方
    if sentiment_index < 50 and ma_bias_20 < -0.02:
        return "defensive_rotate"

    # 5. 回调: 1m显著下跌
    if ret_1m < -0.05:
        return "correction"

    # 6. 熊市: 3m显著下跌
    if ret_3m < -0.10:
        return "bear"

    # 7. P0.5: 趋势数据为空时的 fallback — 用 index_realtime 当日涨跌幅判定
    if regime == "range_bound" and index_realtime:
        for idx in index_realtime:
            chg = idx.get("change_pct", 0) or 0
            if chg < -0.05:
                return "panic"
            if chg < -0.03:
                return "correction"
            if chg < -0.02 and sentiment_index < 50:
                return "defensive_rotate"
            if chg > 0.05:
                return "bull_strong"
            if chg > 0.03 and sentiment_index > 60:
                return "bull_weakening"

    return regime


def _compute_trend_from_prices(
    prices: list[float],
    volumes: list[float] | None = None,
    latest_price: float | None = None,
) -> dict[str, float]:
    """
    Compute trend indicators from price/volume arrays using pandas-ta.

    Pure function - no I/O. Returns same fields as _fetch_single_trend.
    """
    import math

    volumes = volumes or []
    n = len(prices)
    result: dict[str, float] = {}
    latest = latest_price if latest_price is not None else (prices[-1] if n > 0 else 0.0)

    if n < 5:
        return {}

    # Multi-period returns
    periods_map = {"return_5d": 5, "return_1m": 20, "return_3m": 60}
    for key, days in periods_map.items():
        idx = n - 1 - days
        if idx >= 0 and prices[idx] != 0:
            result[key] = (latest - prices[idx]) / prices[idx]
        else:
            result[key] = 0.0

    # MA bias via pandas-ta
    ps = pd.Series(prices)
    if n >= 21:
        ma20 = ta.sma(ps, length=20)
        if ma20 is not None and not ma20.empty:
            ma20_val = float(ma20.iloc[-1])
            result["ma_bias_20"] = (latest - ma20_val) / ma20_val if ma20_val != 0 else 0.0
        else:
            result["ma_bias_20"] = 0.0
    else:
        result["ma_bias_20"] = 0.0

    if n >= 61:
        ma60 = ta.sma(ps, length=60)
        if ma60 is not None and not ma60.empty:
            ma60_val = float(ma60.iloc[-1])
            result["ma_bias_60"] = (latest - ma60_val) / ma60_val if ma60_val != 0 else 0.0
        else:
            result["ma_bias_60"] = 0.0
    else:
        result["ma_bias_60"] = 0.0

    # Volume ratio
    if len(volumes) >= 61 and n >= 61:
        vol_20 = sum(volumes[-20:]) / 20
        vol_60 = sum(volumes[-60:]) / 60
        result["vol_ratio"] = vol_20 / vol_60 if vol_60 > 0 else 1.0
    else:
        result["vol_ratio"] = 1.0

    # Volatility & max drawdown via pandas-ta
    if n >= 21:
        ret = ps.pct_change().dropna()
        if len(ret) >= 20:
            result["volatility_20d"] = float(ret.tail(20).std() * (252 ** 0.5))
        max_dd = (ps / ps.cummax() - 1).min()
        result["max_drawdown_1m"] = float(max_dd) if not pd.isna(max_dd) else 0.0

    # Daily change
    if n >= 2 and prices[-2] != 0:
        result["change_pct"] = (prices[-1] - prices[-2]) / prices[-2]
    else:
        result["change_pct"] = 0.0

    return result


# ── 内部实现 ──────────────────────────────────────────────────

async def _fetch_single_trend(symbol: str) -> dict[str, float]:
    """获取单只ETF的趋势数据。
    
    数据源：china_market.fetch_history() → mootdx → Sina 两级降级，
    比直接调 akshare.fund_etf_hist_em 更稳定。
    """
    try:
        from ..services.market_data_hub import market_data_hub

        # 拉取历史日线（经 hub 委托 china_market 的 mootdx → Sina 降级链）
        from ..core.async_utils import run_sync
        rows = await run_sync(market_data_hub.get_history, symbol, "A", "daily", timeout=30)
        if not rows:
            return {}

        # 提取收盘价与成交量（从旧到新）
        prices = [float(r.get("收盘", 0)) for r in rows if r.get("收盘", 0) > 0]
        volumes = [float(r.get("成交量", 0)) for r in rows]
        if len(prices) < 5:
            return {}

        # 使用 pandas-ta 辅助函数计算趋势指标
        result = _compute_trend_from_prices(prices, volumes)

        return result

    except Exception as e:
        logger.debug("[market_trends] _fetch_single_trend(%s) failed: %s", symbol, e)
        return {}
