"""
市场情绪指数合成模块 (Market Sentiment Fetcher)

综合多维度数据生成 0~100 的市场情绪指数:
  1. 涨跌家数比
  2. 机构共识度 (四类资金流拆解)
  3. 北向资金流向
  4. 两融余额变化

所有外部 API 调用带超时保护，失败时返回中性默认值。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 情绪指数权重
SENTIMENT_WEIGHTS = {
    "advance_ratio": 0.25,     # 涨跌家数比
    "inst_consensus": 0.25,    # 机构共识度
    "north_flow": 0.25,        # 北向资金
    "margin_change": 0.25,     # 两融变化
}


def sentiment_label(index: float) -> str:
    """将情绪指数 (0~100) 映射为文字标签。"""
    if index >= 80:
        return "亢奋"
    elif index >= 65:
        return "乐观"
    elif index >= 55:
        return "中性偏乐观"
    elif index >= 45:
        return "中性"
    elif index >= 35:
        return "中性偏谨慎"
    elif index >= 20:
        return "谨慎"
    else:
        return "恐慌"


def normalize(val: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    """将数值归一化到 [0, 1] 区间。"""
    if max_val == min_val:
        return 0.5
    return max(0.0, min(1.0, (val - min_val) / (max_val - min_val)))


def calc_sentiment_index(
    advance_ratio: float,
    inst_consensus: float,
    north_flow: float,
    margin_change: float,
) -> float:
    """合成四维情绪指数 (0~100)。

    Args:
        advance_ratio: 上涨家数占比 (0~1)
        inst_consensus: 机构共识度 (-1~1)
        north_flow: 北向资金方向 (-1~1, 归一化)
        margin_change: 两融变化 (-1~1, 归一化)
    """
    score = (
        0.25 * advance_ratio
        + 0.25 * normalize(inst_consensus)
        + 0.25 * normalize(north_flow)
        + 0.25 * normalize(margin_change)
    )
    return round(score * 100, 1)


def fetch_advance_decline_ratio() -> float:
    """获取市场涨跌家数比 (上涨家数/总家数)。

    返回: 0~1, 失败时返回 0.5 (中性)
    """
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return 0.5
        up = sum(1 for _, r in df.iterrows() if float(r.get("涨跌幅", 0) or 0) > 0)
        total = len(df)
        return up / max(total, 1)
    except Exception as e:
        logger.warning("[sentiment] fetch_advance_decline_ratio failed: %s", e)
        return 0.5


def fetch_north_flow() -> float:
    """获取北向资金当日净流入 (归一化 -1~1)。

    返回: -1~1, 失败时返回 0
    """
    try:
        import akshare as ak

        # Try multiple akshare north-bound API names (version-dependent)
        df = None
        for func_name in ["stock_hsgt_north_net_flow_in_em",
                          "stock_hsgt_north_flow_in_em",
                          "stock_hsgt_north_net_flow"]:
            try:
                func = getattr(ak, func_name, None)
                if func:
                    df = func(symbol="北上")
                    break
            except Exception:
                continue
        if df is None or (hasattr(df, "empty") and df.empty):
            return 0.0
        # 取最近一条的净流入
        latest = df.iloc[0]
        for col in df.columns:
            if "净流入" in col or "net" in col.lower():
                val = float(latest[col] or 0)
                # 归一化: ±50亿为极端值
                return max(-1.0, min(1.0, val / 50_000_000))
    except Exception as e:
        logger.warning("[sentiment] fetch_north_flow failed: %s", e)
    return 0.0


def fetch_margin_change() -> float:
    """获取两融余额变化率 (归一化 -1~1)。

    返回: -1~1, 失败时返回 0
    """
    try:
        import akshare as ak

        df = ak.stock_margin_szse()
        if df is None or df.empty:
            return 0.0
        if len(df) >= 2:
            # 最近两期的两融余额变化
            try:
                val_col = None
                for col in df.columns:
                    if "融资余额" in col or "余额" in col:
                        val_col = col
                        break
                if val_col:
                    v1 = float(df.iloc[0][val_col] or 0)
                    v2 = float(df.iloc[1][val_col] or 0)
                    if v2 > 0:
                        pct = (v1 - v2) / v2
                        return max(-1.0, min(1.0, pct * 5))  # ±20% => ±1
            except (IndexError, ValueError, TypeError):
                pass
    except Exception as e:
        logger.warning("[sentiment] fetch_margin_change failed: %s", e)
    return 0.0


async def fetch_market_sentiment() -> dict[str, Any]:
    """一站式获取市场情绪指数。

    返回:
    {
        "sentiment_index": 65.0,
        "sentiment_label": "中性偏乐观",
        "advance_ratio": 0.6,
        "institutional_consensus": 0.0,
        "north_flow": 0.0,
        "margin_change": 0.0,
    }
    """
    import asyncio

    advance, north, margin = await asyncio.gather(
        asyncio.wait_for(asyncio.to_thread(fetch_advance_decline_ratio), timeout=15),
        asyncio.wait_for(asyncio.to_thread(fetch_north_flow), timeout=15),
        asyncio.wait_for(asyncio.to_thread(fetch_margin_change), timeout=15),
        return_exceptions=True,
    )

    advance = advance if isinstance(advance, float) and not isinstance(advance, Exception) else 0.5
    north = north if isinstance(north, float) and not isinstance(north, Exception) else 0.0
    margin = margin if isinstance(margin, float) and not isinstance(margin, Exception) else 0.0

    index = calc_sentiment_index(
        advance_ratio=advance,
        inst_consensus=0.0,  # 共识度由调用方传入（需要四类资金流数据）
        north_flow=north,
        margin_change=margin,
    )

    return {
        "sentiment_index": index,
        "sentiment_label": sentiment_label(index),
        "advance_ratio": round(advance, 4),
        "institutional_consensus": 0.0,  # placeholder, 调用方填充
        "north_flow": round(north, 4),
        "margin_change": round(margin, 4),
    }
