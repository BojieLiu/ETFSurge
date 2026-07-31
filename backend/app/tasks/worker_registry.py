"""
worker_registry.py — Worker 注册表与通用调度器
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Registry: task_type -> async worker function
WORKER_REGISTRY: dict[str, Callable] = {}


def register_worker(task_type: str, worker_fn: Callable) -> None:
    """注册 worker 函数到注册表。"""
    WORKER_REGISTRY[task_type] = worker_fn
    logger.info("[worker_registry] registered worker for %s", task_type)


async def dispatch(manager, task_id: int) -> None:
    """通用调度器：根据 task.type 找到对应 worker 并执行。"""
    task = await manager.get_task(task_id)
    if not task:
        logger.warning("[dispatch] task %d not found", task_id)
        return
    worker = WORKER_REGISTRY.get(task["type"])
    if not worker:
        await manager.update_task(task_id, status="failed",
                                  error_message=f"unknown task type: {task['type']}")
        from .task_manager import _notify
        await _notify(task_id, "failed", 0)
        return
    try:
        await worker(manager, task_id)
    except Exception as e:
        logger.error("[dispatch] task %d worker failed: %s", task_id, e)
        await manager.update_task(task_id, status="failed", error_message=str(e))
        from .task_manager import _notify
        await _notify(task_id, "failed", 0, str(e))
