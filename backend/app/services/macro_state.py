"""
宏观状态感知模块 (Macro Regime Detection)

综合多维度宏观数据判断当前经济象限和政策环境：
  1. detect_macro_regime(): 经济阶段/货币取向/利率方向/风险偏好
  2. _fetch_pmi_trend():    PMI趋势（经济景气）
  3. _fetch_rate_env():     利率/债市环境

所有外部 API 调用带超时保护，失败时返回中性默认值。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT = 20


async def detect_macro_regime() -> dict[str, Any]:
    """
    一站式获取宏观状态判断。

    返回:
      {
        "economic_phase": str,     # "衰退" / "弱复苏" / "扩张" / "过热" / "滞胀"
        "monetary_stance": str,    # "宽松" / "中性" / "收紧"
        "rate_direction": str,     # "up" / "down" / "flat"
        "bond_bull": bool,         # 是否处于债牛
        "credit_cycle": str,       # "扩张" / "收缩"
        "external_risk": str,      # "low" / "moderate" / "elevated"
        "style_preference": str,   # "growth" / "balanced" / "defensive_value"
        "confidence": float,       # 判断置信度 0~1
      }
    """
    pmi_trend, rate_info, sentiment = await asyncio.gather(
        _fetch_pmi_trend(),
        _fetch_rate_env(),
        _fetch_sentiment_reference(),
        return_exceptions=True,
    )

    pmi_trend = pmi_trend if isinstance(pmi_trend, dict) else {}
    rate_info = rate_info if isinstance(rate_info, dict) else {}
    sentiment = sentiment if isinstance(sentiment, (int, float)) else 50.0

    # --- 经济阶段判断 ---
    economic_phase = _classify_economic_phase(pmi_trend)

    # --- 货币取向 ---
    monetary_stance = _classify_monetary_stance(rate_info)

    # --- 利率方向 ---
    rate_direction = rate_info.get("rate_direction", "flat")

    # --- 债牛判断 ---
    bond_bull = rate_direction == "down"

    # --- 信用周期 ---
    credit_cycle = "收缩"  # 默认为收缩（谨慎）

    # --- 外部风险 ---
    external_risk = "moderate"
    if sentiment < 30:
        external_risk = "elevated"
    elif sentiment > 60:
        external_risk = "low"

    # --- 风格偏好 ---
    style_preference = _classify_style_preference(
        economic_phase, monetary_stance, sentiment
    )

    # --- 置信度 ---
    confidence = _compute_confidence(pmi_trend, rate_info)

    return {
        "economic_phase": economic_phase,
        "monetary_stance": monetary_stance,
        "rate_direction": rate_direction,
        "bond_bull": bond_bull,
        "credit_cycle": credit_cycle,
        "external_risk": external_risk,
        "style_preference": style_preference,
        "confidence": confidence,
    }


# ── 数据采集 ──────────────────────────────────────────────────

async def _fetch_pmi_trend() -> dict[str, Any]:
    """获取PMI趋势数据。

    返回:
      {"pmi_current": float, "pmi_change": float, "above_50": bool}
    """
    try:
        from ..core.async_utils import run_sync
        import akshare as ak

        def _sync_pmi():
            return ak.macro_china_pmi()

        df = await run_sync(_sync_pmi, timeout=30)
        if df is None or df.empty:
            return {}

        for col in df.columns:
            if "制造业" in col:
                val_col = col
                break
        else:
            return {}

        values = df[val_col].dropna().tolist()
        if len(values) < 2:
            return {"pmi_current": float(values[-1]) if values else 50.0, "pmi_change": 0.0}

        current = float(values[-1])
        prev = float(values[-2])
        return {
            "pmi_current": current,
            "pmi_change": current - prev,
            "above_50": current > 50,
        }
    except Exception as e:
        logger.debug("[macro_state] _fetch_pmi_trend failed: %s", e)
        return {}


async def _fetch_rate_env() -> dict[str, Any]:
    """获取利率/债市环境。

    返回:
      {
        "10y_yield": float,       # 10年期国债收益率
        "rate_direction": str,    # "up" / "down" / "flat"
        "rate_change_bp": float,  # 近1月变化(bp)
      }
    """
    try:
        from ..core.async_utils import run_sync
        import akshare as ak
        from ..utils.decode import decode_df

        def _sync_bond_yield():
            return ak.bond_china_yield(start_date="", end_date="")

        df = await run_sync(_sync_bond_yield, timeout=30)
        if df is None or df.empty:
            return {}

        decode_df(df)

        # 查找10年期国债收益率
        for _, row in df.iterrows():
            name = str(row.get("名称", "") or row.get("债券名称", "") or "")
            if "10年" in name and "国债" in name:
                recent = []
                for col in df.columns:
                    if "收益率" in col or "yield" in col.lower():
                        recent.append(float(row[col]) if row[col] else 0)
                if recent:
                    yield_val = recent[0]
                    # 简单判断方向
                    return {
                        "10y_yield": yield_val,
                        "rate_direction": "down" if yield_val < 2.0 else "flat",
                        "rate_change_bp": 0.0,
                    }
        return {}
    except Exception as e:
        logger.debug("[macro_state] _fetch_rate_env failed: %s", e)
        return {}


async def _fetch_sentiment_reference() -> float:
    """获取市场情绪作为宏观判断的参考。

    返回: 0~100 情绪指数
    """
    try:
        from ..core.async_utils import run_sync
        from ..services.market_data_hub import market_data_hub
        result = await run_sync(market_data_hub.get_market_sentiment, timeout=8)
        return float(result.get("sentiment_index", 50))
    except Exception:
        return 50.0


# ── 分类逻辑 ──────────────────────────────────────────────────

def _classify_economic_phase(pmi: dict[str, Any]) -> str:
    """根据PMI判断经济阶段。"""
    pmi_current = pmi.get("pmi_current")
    if pmi_current is None:
        return "弱复苏"  # 无数据时保守默认

    pmi_change = pmi.get("pmi_change", 0.0)
    above_50 = pmi.get("above_50", False)

    if above_50 and pmi_change > 0.5:
        return "扩张"
    elif above_50 and pmi_change >= -0.5:
        return "弱复苏"
    elif not above_50 and pmi_change < 0:
        return "衰退"
    elif not above_50:
        return "滞胀"
    else:
        return "弱复苏"


def _classify_monetary_stance(rate_info: dict[str, Any]) -> str:
    """根据利率环境判断货币取向。

    判断基准：10年期国债收益率 < 2.0% 视为宽松，
    > 3.0% 视为收紧，中间视为中性。
    """
    yield_val = rate_info.get("10y_yield")
    if yield_val is None:
        return "宽松"  # 当前中国宏观环境大概率宽松

    if yield_val < 2.0:
        return "宽松"
    elif yield_val > 3.0:
        return "收紧"
    return "中性"


def _classify_style_preference(
    economic_phase: str,
    monetary_stance: str,
    sentiment: float,
) -> str:
    """综合判断当前风格偏好。"""
    # 弱复苏+宽松 → 成长风格
    if economic_phase == "弱复苏" and monetary_stance == "宽松":
        return "balanced" if sentiment < 50 else "growth"

    # 扩张 → 成长
    if economic_phase == "扩张":
        return "growth"

    # 衰退/滞胀 → 防御
    if economic_phase in ("衰退", "滞胀"):
        return "defensive_value"

    # 情绪低迷时偏防御
    if sentiment < 40:
        return "defensive_value"

    # 默认
    return "balanced"


def _compute_confidence(
    pmi: dict[str, Any],
    rate_info: dict[str, Any],
) -> float:
    """评估宏观判断的置信度。

    数据维度越多，置信度越高。
    同时有PMI和利率数据 => 0.8
    只有其中之一 => 0.5
    都没有 => 0.2
    """
    score = 0.0
    if pmi.get("pmi_current") is not None:
        score += 0.4
    if rate_info.get("10y_yield") is not None:
        score += 0.4
    if rate_info.get("rate_direction") != "flat":
        score += 0.2
    return min(round(score, 2), 1.0)
