"""
市场核心指标股追踪 (Benchmark Stocks Tracker)

跟踪一批固定 + 动态的核心指标股的行情、资金流、新闻，
为 LLM 提供市场环境快照。

数据流:
  1. 固定底仓 10 只（覆盖主要行业板块）
  2. 动态增补 3~5 只（基于当日卫星层 TOP 5 ETF 的重仓股）
  3. 并行采集行情 + 资金流 + 新闻
  4. 合成信号标签
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.async_utils import run_in_thread
from ..fetchers.china_market import _mootdx_realtime, _sina_realtime

logger = logging.getLogger(__name__)


# ── 固定核心指标股 ───────────────────────────────────────────
CORE_BENCHMARK_STOCKS: dict[str, dict[str, str]] = {
    "600519": {"name": "贵州茅台", "sector": "消费"},
    "600036": {"name": "招商银行", "sector": "金融"},
    "300750": {"name": "宁德时代", "sector": "新能源"},
    "600030": {"name": "中信证券", "sector": "券商"},
    "601318": {"name": "中国平安", "sector": "保险"},
    "300760": {"name": "迈瑞医疗", "sector": "医药"},
    "600309": {"name": "万华化学", "sector": "化工"},
    "000333": {"name": "美的集团", "sector": "家电"},
    "002594": {"name": "比亚迪", "sector": "新能源车"},
    "688981": {"name": "中芯国际", "sector": "半导体"},
}


def judge_signal(
    inst: float, retail: float, change: float
) -> str:
    """根据机构/散户方向 + 涨跌幅判断信号。

    Args:
        inst: 机构净流入 (超大单+大单)
        retail: 散户净流入 (中单+小单)
        change: 涨跌幅 (%)
    """
    if inst > 0 and change > 0.5:
        if retail < -abs(inst) * 0.3:
            return "分歧看多"
        elif abs(inst) > abs(retail) * 2:
            return "机构增配"
        return "温和上涨"
    elif inst < 0 and change < -0.5:
        if retail > abs(inst) * 0.3:
            return "分歧看空"
        elif abs(inst) > abs(retail) * 2:
            return "机构出货"
        return "温和下跌"
    elif inst > 0 and retail < 0:
        return "分歧看多"
    elif inst < 0 and retail > 0:
        return "分歧看空"
    elif abs(change) < 0.5:
        return "震荡"
    return "温和上涨" if change >= 0 else "温和下跌"


def _get_realtime_price(code: str) -> dict:
    """Get realtime price for a single stock via mootdx → Sina."""
    try:
        items = _mootdx_realtime([code])
        if items and items[0].get("price"):
            return items[0]
        items = _sina_realtime([code], "A")
        if items and items[0].get("price"):
            return items[0]
    except Exception:
        pass
    return {}


def _get_stock_news(code: str) -> list[str]:
    """获取个股相关新闻标题（取最新 2 条）。"""
    try:
        from ..fetchers.news_fetcher import fetch_stock_news
        news = fetch_stock_news(code)
        return [n.get("title", "")[:40] for n in (news or [])[:2]]
    except Exception:
        return []


def _get_fund_flow(code: str) -> dict:
    """获取个股四类资金流。"""
    try:
        from ..fetchers.fundamental_fetcher import fetch_fund_flow_detailed
        return fetch_fund_flow_detailed(code) or {}
    except Exception:
        return {}


async def fetch_benchmark_stocks(
    dynamic_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """一站式采集 10 固定 + 动态指标股的行情/资金流/新闻。

    Args:
        dynamic_codes: 动态增补的股票代码列表（当日卫星层 TOP ETF 重仓股）

    返回: 每条包含 {symbol, name, sector, change_pct, ...}
    """
    import asyncio

    all_codes = list(CORE_BENCHMARK_STOCKS.keys())
    if dynamic_codes:
        # 去重 + 限 5 只
        seen = set(all_codes)
        for c in dynamic_codes:
            if c not in seen:
                all_codes.append(c)
                seen.add(c)
        all_codes = all_codes[:15]

    # 并行采集行情、新闻、资金流
    async def _fetch_one(code: str) -> dict[str, Any]:
        meta = CORE_BENCHMARK_STOCKS.get(code, {"name": code, "sector": ""})
        price_data, news, flow = await asyncio.gather(
            asyncio.to_thread(_get_realtime_price, code),
            asyncio.to_thread(_get_stock_news, code),
            asyncio.to_thread(_get_fund_flow, code),
            return_exceptions=True,
        )

        price = price_data.get("price", 0) if isinstance(price_data, dict) else 0
        change = price_data.get("change_pct", 0) if isinstance(price_data, dict) else 0
        news_list = news if isinstance(news, list) else []
        flow_dict = flow if isinstance(flow, dict) else {}

        inst = flow_dict.get("super_large", {}).get("inflow", 0) + flow_dict.get("large", {}).get("inflow", 0)
        retail = flow_dict.get("medium", {}).get("inflow", 0) + flow_dict.get("small", {}).get("inflow", 0)
        main_net_inflow = flow_dict.get("main_net_inflow", 0)
        main_net_inflow_pct = flow_dict.get("main_net_inflow_pct", 0)

        return {
            "symbol": code,
            "name": meta.get("name", code),
            "sector": meta.get("sector", ""),
            "change_pct": round(change, 2),
            "institutional_net_inflow": round(inst, 2),
            "retail_net_inflow": round(retail, 2),
            "main_net_inflow": round(main_net_inflow, 2) if main_net_inflow else None,
            "main_net_inflow_pct": round(main_net_inflow_pct, 2) if main_net_inflow_pct else None,
            "signal": judge_signal(inst, retail, change),
            "top_news": news_list,
        }

    tasks = [_fetch_one(code) for code in all_codes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return [
        r for r in results if isinstance(r, dict) and r.get("symbol")
    ]
