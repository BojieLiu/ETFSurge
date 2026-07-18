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

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT = 30  # seconds


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


async def compute_sector_momentum(top_n: int = 10) -> list[dict[str, Any]]:
    """
    计算申万一级行业板块20日动量变化。

    返回:
      [{sector, rank_current, rank_change, momentum_score, direction}]
    """
    try:
        import akshare as ak
        from ..utils.decode import decode_df

        # 获取行业板块行情
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return []
        decode_df(df)

        # 获取当前涨幅排名
        current = []
        for _, row in df.iterrows():
            sector_name = str(row.get("板块名称", ""))
            change_pct = float(row.get("涨跌幅", 0) or 0)
            current.append({
                "sector": sector_name,
                "change_pct": change_pct,
            })

        # 按涨幅排序取排名
        current.sort(key=lambda x: x["change_pct"], reverse=True)
        for rank, item in enumerate(current, 1):
            item["rank_current"] = rank

        # 取前 top_n
        return [
            {
                "sector": item["sector"],
                "rank_current": item["rank_current"],
                "change_pct": item["change_pct"],
            }
            for item in current[:top_n]
        ]
    except Exception as e:
        logger.warning("[market_trends] compute_sector_momentum failed: %s", e)
        return []


def detect_market_regime(
    trends: dict[str, dict[str, float]] | None = None,
    broad_index_code: str = "000001",
    sentiment_index: float = 50.0,
    adv_ratio: float = 0.5,
    index_realtime: list[dict] | None = None,  # P0.5: 实时指数兜底
) -> str:
    """
    基于趋势数据和情绪指标判断当前市场状态。
    当趋势数据为空（外部数据源超时）时，自动降级使用 index_realtime 做判断。

    Args:
        trends: compute_etf_trends() 的输出（含主要宽基）
        broad_index_code: 主要宽基代码（默认上证指数）
        sentiment_index: 情绪指数 0~100
        adv_ratio: 上涨家数占比 0~1
        index_realtime: 实时指数行情快照（P0.5 fallback）

    Returns:
        "bull_strong" / "bull_weakening" / "range_bound" /
        "correction" / "bear" / "defensive_rotate" / "panic"
    """
    # 默认
    regime = "range_bound"

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
                return "correction"
            if chg < -0.03 and sentiment_index < 50:
                return "defensive_rotate"
            if chg > 0.03 and sentiment_index > 60:
                return "bull_weakening"

    return regime


# ── 内部实现 ──────────────────────────────────────────────────

async def _fetch_single_trend(symbol: str) -> dict[str, float]:
    """获取单只ETF的趋势数据。
    
    数据源：china_market.fetch_history() → mootdx → Sina 两级降级，
    比直接调 akshare.fund_etf_hist_em 更稳定。
    """
    try:
        from ..fetchers.china_market import fetch_history

        # 拉取历史日线（通过 china_market 的 mootdx → Sina 降级链）
        import asyncio
        rows = await asyncio.to_thread(fetch_history, symbol, "A", "daily")
        if not rows:
            return {}

        # 提取收盘价与成交量（从旧到新）
        prices = [float(r.get("收盘", 0)) for r in rows if r.get("收盘", 0) > 0]
        volumes = [float(r.get("成交量", 0)) for r in rows]
        if len(prices) < 5:
            return {}

        # 计算多周期收益率
        latest = prices[-1]
        result: dict[str, float] = {}

        periods_map = {
            "return_5d": 5,
            "return_1m": 20,
            "return_3m": 60,
        }
        for key, days in periods_map.items():
            idx = len(prices) - 1 - days
            if idx >= 0 and prices[idx] != 0:
                result[key] = (latest - prices[idx]) / prices[idx]
            else:
                result[key] = 0.0

        # 均线乖离率
        if len(prices) >= 21:
            ma20 = sum(prices[-21:-1]) / 20  # 前20日收盘均值
            result["ma_bias_20"] = (latest - ma20) / ma20 if ma20 != 0 else 0.0
        else:
            result["ma_bias_20"] = 0.0

        if len(prices) >= 61:
            ma60 = sum(prices[-61:-1]) / 60
            result["ma_bias_60"] = (latest - ma60) / ma60 if ma60 != 0 else 0.0
        else:
            result["ma_bias_60"] = 0.0

        # 量比: 近20日均量 / 近60日均量
        if len(volumes) >= 61 and len(prices) >= 61:
            vol_20 = sum(volumes[-20:]) / 20
            vol_60 = sum(volumes[-60:]) / 60
            result["vol_ratio"] = vol_20 / vol_60 if vol_60 > 0 else 1.0
        else:
            result["vol_ratio"] = 1.0

        # 20日年化波动率
        if len(prices) >= 21:
            daily_returns = [
                (prices[i] - prices[i - 1]) / prices[i - 1]
                for i in range(len(prices) - 21, len(prices))
                if prices[i - 1] != 0
            ]
            if len(daily_returns) > 1:
                mean = sum(daily_returns) / len(daily_returns)
                variance = sum((r - mean) ** 2 for r in daily_returns) / len(daily_returns)
                import math
                result["volatility_20d"] = math.sqrt(variance * 252)  # 年化
            else:
                result["volatility_20d"] = 0.0
        else:
            result["volatility_20d"] = 0.0

        # 近1月最大回撤
        if len(prices) >= 21:
            lookback = prices[-21:]
            peak = lookback[0]
            max_dd = 0.0
            for p in lookback[1:]:
                if p > peak:
                    peak = p
                dd = (p - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            result["max_drawdown_1m"] = max_dd
        else:
            result["max_drawdown_1m"] = 0.0

        # 当日涨跌幅：最新一日收盘 vs 前一日收盘（用于入选理由「今日涨/跌 X%」）
        if len(prices) >= 2 and prices[-2] != 0:
            result["change_pct"] = (prices[-1] - prices[-2]) / prices[-2]
        else:
            result["change_pct"] = 0.0

        return result

    except Exception as e:
        logger.debug("[market_trends] _fetch_single_trend(%s) failed: %s", symbol, e)
        return {}
