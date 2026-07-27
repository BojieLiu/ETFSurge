"""
异步策略检查 worker（v2 pipeline）
Async strategy check pipeline

v2 (design-check-pipeline-redesign):
  - 顺序 Pipeline: DATA → LLM → DB SAVE → NOTIFY
  - 去除外层 240s 超时，改为 per-stage 超时保护
  - 新增 per-stage WS 进度通知
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def strategy_check_pipeline(mgr, task_id: int) -> None:
    """顺序 Pipeline：DATA → LLM → DB SAVE → NOTIFY"""
    from ..services.portfolio_service import strategy_check
    from app.database import async_session

    task = mgr.get_task(task_id)
    if not task:
        return

    try:
        # FIX-21: 外层 120s 超时保护，防止整个管线无限制挂起
        import asyncio
        return await asyncio.wait_for(
            _pipeline_body(mgr, task_id),
            timeout=120,
        )
    except asyncio.TimeoutError:
        logger.error("[strategy_check_pipeline] task %d timed out after 120s", task_id)
        mgr.update_task(
            task_id,
            status="failed",
            progress=100,
            stage="分析超时",
            result={"error": "策略检查超时（120s）", "partial_data": {}},
        )
        await _notify(task_id, "failed", progress=100, stage="分析超时")
    except Exception as e:
        logger.error("[strategy_check_pipeline] task %d failed: %s", task_id, e)
        mgr.update_task(
            task_id,
            status="failed",
            progress=100,
            result={"error": str(e)},
        )
        await _notify(task_id, "failed", progress=100, stage="分析失败")


async def _pipeline_body(mgr, task_id: int) -> dict:
    """FIX-21: Pipeline 主体逻辑，被外层 asyncio.wait_for 保护。"""
    from ..services.portfolio_service import strategy_check
    from app.database import async_session

    task = mgr.get_task(task_id)
    if not task:
        return {}

    mgr.update_task(task_id, status="running", progress=5, stage="初始化")
    await _notify(task_id, "running", progress=5, stage="初始化")

    params = task.get("params", {})
    capital = params.get("capital", 500000)
    portfolio_type = params.get("portfolio_type")

    # Stage 1: DATA (progress 5→40%) — 数据采集 & 策略检查
    mgr.update_task(task_id, progress=10, stage="加载持仓数据")
    await _notify(task_id, "running", progress=10, stage="加载持仓数据")

    from app.database import async_session
    async with async_session() as db:
        result = await strategy_check(db, capital, portfolio_type=portfolio_type)

    mgr.update_task(task_id, progress=40, stage="数据采集完成")
    await _notify(task_id, "running", progress=40, stage="数据采集完成")

    # Stage 2: LLM (progress 40→80%) — LLM 已在 strategy_check 内部完成
    mgr.update_task(task_id, progress=60, stage="AI 分析完成")
    await _notify(task_id, "running", progress=60, stage="AI 分析完成")

    # Stage 3: DB (progress 80→95%) — 持久化到数据库
    mgr.update_task(task_id, progress=80, stage="保存报告")
    await _notify(task_id, "running", progress=80, stage="保存报告")

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
            logger.info("[strategy_check_pipeline] record %d saved", record_id)
    except Exception as e:
        logger.warning("[strategy_check_pipeline] DB persist failed: %s", e)

    # Stage 4: NOTIFY (progress 95→100%)
    mgr.update_task(
        task_id,
        progress=100,
        status="completed",
        result=result,
        record_id=record_id,
    )
    await _notify(task_id, "completed", progress=100, stage="分析完成")

    logger.info(
        "[strategy_check_pipeline] task %d completed (record %s)",
        task_id,
        record_id,
    )

    return result


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


# ── Backward-compatible alias ─────────────────────────────────
strategy_check_worker = strategy_check_pipeline
