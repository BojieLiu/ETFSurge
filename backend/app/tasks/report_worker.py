"""
report_worker.py — 异步市场研判报告 worker

通过 WS 推送生成进度和最终报告。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from ..analysis.llm import generate_market_report

logger = logging.getLogger(__name__)


async def report_worker(mgr, task_id: int) -> None:
    """后台执行市场研判报告生成。"""
    task = mgr.get_task(task_id)
    if not task:
        return

    async def _notify(status: str, progress: int, stage: str = ""):
        from .task_manager import notify_manager
        await notify_manager.broadcast({
            "type": "task_update",
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "stage": stage,
        })

    try:
        await _notify("running", 5, "采集行情数据")
        mgr.update_task(task_id, status="running", progress=5)

        # 并行采集行情和新闻
        from ..services.market_service import get_all_realtime, get_indices, get_commodities
        from ..fetchers.news_fetcher import fetch_news_headlines, fetch_macro_news

        results = await asyncio.gather(
            asyncio.wait_for(get_all_realtime(), timeout=15),
            asyncio.wait_for(get_indices(), timeout=15),
            asyncio.wait_for(get_commodities(), timeout=15),
            asyncio.to_thread(fetch_news_headlines),
            asyncio.to_thread(fetch_macro_news),
            return_exceptions=True,
        )

        def _safe(r, fallback):
            return r if isinstance(r, list) else fallback

        market_data = _safe(results[0], [])
        indices = _safe(results[1], [])
        commodities = _safe(results[2], [])
        news = _safe(results[3], [])
        macro_items = _safe(results[4], [])
        all_news = news + macro_items

        await _notify("running", 40, f"加载 {len(indices)} 指数 + {len(market_data)} 标的")
        mgr.update_task(task_id, progress=40)

        # 计算部分 K 线指标
        await _notify("running", 50, "计算技术指标")
        from ..analysis.indicators import compute_all_indicators
        from ..services.market_service import get_history

        indicators = {}
        for item in market_data[:5]:
            if item.get("asset_type") in ("index", "futures"):
                continue
            try:
                hist = await asyncio.wait_for(
                    get_history(item["symbol"], item["asset_type"]), timeout=15
                )
                ind = compute_all_indicators(hist)
                if ind:
                    indicators[item["symbol"]] = ind
            except Exception:
                continue

        await _notify("running", 65, "LLM 生成报告")
        mgr.update_task(task_id, progress=65)

        # LLM 生成报告
        report = await asyncio.wait_for(
            generate_market_report(indices, commodities, market_data, indicators, all_news, []),
            timeout=90,
        )

        result = {
            "report": report,
            "market_data": market_data[:10],
            "indices": indices[:10],
            "commodities": commodities[:6],
        }

        mgr.update_task(task_id, progress=100, status="completed", result=result)
        await _notify("completed", 100, "报告生成完成")
        logger.info("[report_worker] task %d completed", task_id)

    except asyncio.TimeoutError:
        logger.warning("[report_worker] task %d timed out", task_id)
        mgr.update_task(task_id, status="failed", error_message="报告生成超时（90s）")
        await _notify("failed", 0, "超时")
    except Exception as e:
        logger.warning("[report_worker] task %d failed: %s", task_id, e)
        mgr.update_task(task_id, status="failed", error_message=str(e))
        await _notify("failed", 0, str(e))
