"""
异步设计任务管理系统 (Async Design Task Manager)

支持:
  - 异步提交设计任务，立即返回 task_id
  - 后台 worker 执行 generate_full_design()
  - 查询任务状态和进度
  - WebSocket 推送任务状态变更通知
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ..services.strategy_design import generate_enhanced_design

logger = logging.getLogger(__name__)


# ── 任务管理器 (内存存储) ─────────────────────────────────


class DesignTaskManager:
    """内存任务管理器。生产环境可替换为 Redis/DB 存储。"""

    def __init__(self):
        self._tasks: dict[int, dict] = {}
        self._next_id = 1

    def create_task(self, capital: float = 500000, risk_profile: str = "balanced",
                    constraints: dict | None = None) -> dict:
        """创建新任务，返回任务对象。"""
        task_id = self._next_id
        self._next_id += 1
        task = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "design_id": None,
            "error_message": None,
            "capital": capital,
            "risk_profile": risk_profile,
            "constraints": constraints or {},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "completed_at": None,
        }
        self._tasks[task_id] = task
        logger.info("[DesignTaskManager] created task %d", task_id)
        return task

    def get_task(self, task_id: int) -> dict | None:
        return self._tasks.get(task_id)

    def update_task(self, task_id: int, **kwargs) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        for k, v in kwargs.items():
            if v is not None:
                task[k] = v
        if kwargs.get("status") == "completed":
            task["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def list_tasks(self, limit: int = 20, offset: int = 0) -> list[dict]:
        tasks = sorted(self._tasks.values(), key=lambda t: -t["task_id"])
        return tasks[offset:offset + limit]


# 全局单例
task_manager = DesignTaskManager()


# ── WebSocket 通知管理器 ──────────────────────────────────


class TaskNotifyManager:
    """任务完成通知的 WS 管理器。"""

    def __init__(self):
        self._connections: set = set()

    def register(self, websocket) -> None:
        self._connections.add(websocket)

    def unregister(self, websocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        if not self._connections:
            return
        payload = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister(ws)


notify_manager = TaskNotifyManager()


# ── 后台 Worker ────────────────────────────────────────────


async def design_worker(mgr: DesignTaskManager, task_id: int) -> None:
    """后台执行设计生成任务。"""
    task = mgr.get_task(task_id)
    if not task:
        return

    try:
        mgr.update_task(task_id, status="running", progress=10)
        await _notify(task_id, "running", progress=10)

        # 生成方案
        mgr.update_task(task_id, progress=30)
        await _notify(task_id, "running", progress=30)

        result = await generate_enhanced_design(
            capital=task["capital"],
            constraints=task.get("constraints"),
        )

        strategies = result.get("strategies", [])
        market_context = result.get("market_context", {})

        mgr.update_task(task_id, progress=70)
        await _notify(task_id, "running", progress=70)

        # 保存到数据库设计历史
        from app.models.portfolio_design import PortfolioDesign
        from app.database import async_session
        design_id = None
        try:
            async with async_session() as db:
                record = PortfolioDesign(
                    capital=task["capital"],
                    risk_profile=task.get("risk_profile", "balanced"),
                    strategies_json=json.dumps(strategies, ensure_ascii=False, default=str),
                    market_snapshot_json=json.dumps(market_context, ensure_ascii=False, default=str),
                )
                db.add(record)
                await db.commit()
                await db.refresh(record)
                design_id = record.id
        except Exception as e:
            logger.warning("[design_worker] failed to save design history: %s", e)

        # 保存完成状态与 design_id
        mgr.update_task(task_id, progress=100, status="completed",
                        design_id=design_id,
                        _strategies=strategies,
                        _market_context=market_context)
        await _notify(task_id, "completed", progress=100)

        logger.info("[design_worker] task %d completed with %d strategies",
                    task_id, len(strategies))

    except Exception as e:
        error_msg = str(e)
        logger.warning("[design_worker] task %d failed: %s", task_id, error_msg)
        mgr.update_task(task_id, status="failed", progress=0, error_message=error_msg)
        await _notify(task_id, "failed", progress=0)


async def _notify(task_id: int, status: str, progress: int) -> None:
    """通过 WS 广播任务状态变更。"""
    await notify_manager.broadcast({
        "type": "task_update",
        "task_id": task_id,
        "status": status,
        "progress": progress,
    })
