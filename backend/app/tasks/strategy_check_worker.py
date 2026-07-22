"""
异步策略检查 worker
Async strategy check worker

复用 DesignTaskManager 和 TaskNotifyManager (design_tasks.py)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ..services.portfolio_service import strategy_check
from ..services.portfolio_service import logger as svc_logger

logger = logging.getLogger(__name__)


async def strategy_check_worker(mgr, task_id: int) -> None:
    """后台执行策略检查任务。"""
    task = mgr.get_task(task_id)
    if not task:
        return

    try:
        mgr.update_task(task_id, status="running", progress=5)
        await _notify(task_id, "running", progress=5)

        params = task.get("params", {})
        capital = params.get("capital", 500000)
        portfolio_type = params.get("portfolio_type")

        # 加载持仓 / 因子评分 / 技术指标
        mgr.update_task(task_id, progress=20)
        await _notify(task_id, "running", progress=20, stage="加载持仓数据")

        # 调用 strategy_check（内部并行采集因子+指标+regime）
        from app.database import async_session

        async with async_session() as db:
            result = await asyncio.wait_for(
                strategy_check(db, capital, portfolio_type=portfolio_type),
                timeout=240,
            )

        mgr.update_task(task_id, progress=60)
        await _notify(task_id, "running", progress=60, stage="数据采集完成")

        # LLM 分析（已在 strategy_check 内部完成）
        mgr.update_task(task_id, progress=80)
        await _notify(task_id, "running", progress=80, stage="正在生成分析报告")

        # 持久化到数据库
        record_id = None
        try:
            from app.models.strategy_check import StrategyCheckRecord

            async with async_session() as db:
                record = StrategyCheckRecord(
                    capital=capital,
                    summary=result.get("summary", ""),
                    market_regime=result.get("market_regime", ""),
                    suggestions_json=json.dumps(
                        result.get("suggestions", []), ensure_ascii=False, default=str
                    ),
                    holdings_json=json.dumps(
                        result.get("holdings_analysis", []), ensure_ascii=False, default=str
                    ),
                    risk_warnings_json=json.dumps(
                        result.get("risk_warnings", []), ensure_ascii=False, default=str
                    ),
                )
                db.add(record)
                await db.commit()
                await db.refresh(record)
                record_id = record.id
        except Exception as e:
            logger.warning("[strategy_check_worker] DB persist failed: %s", e)

        # 保存完成状态
        mgr.update_task(
            task_id,
            progress=100,
            status="completed",
            result=result,
            record_id=record_id,
        )
        await _notify(task_id, "completed", progress=100, stage="分析完成")

        logger.info(
            "[strategy_check_worker] task %d completed (record %s)",
            task_id,
            record_id,
        )

    except asyncio.TimeoutError:
        logger.warning("[strategy_check_worker] task %d timed out", task_id)
        mgr.update_task(
            task_id, status="failed", progress=0,
            error_message="策略检查超时（240s），请稍后重试"
        )
        await _notify(task_id, "failed", progress=0)
    except Exception as e:
        error_msg = str(e)
        logger.warning("[strategy_check_worker] task %d failed: %s", task_id, error_msg)
        mgr.update_task(
            task_id, status="failed", progress=0, error_message=error_msg
        )
        await _notify(task_id, "failed", progress=0)


async def _notify(task_id: int, status: str, progress: int, stage: str = "") -> None:
    """通过 WS 广播任务状态变更。"""
    from ..tasks.task_manager import notify_manager

    await notify_manager.broadcast({
        "type": "task_update",
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "stage": stage,
    })
