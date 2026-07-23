"""
task_manager.py — 通用异步任务管理器

泛化 DesignTaskManager 为通用 TaskManager，支持多任务类型。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

TASK_TYPES = {
    "design": {"label": "组合设计", "ttl": 600},
    "check":  {"label": "策略检查", "ttl": 600},
    "report": {"label": "市场研判", "ttl": 600},
}


class TaskManager:
    """通用异步任务管理器。"""

    def __init__(self):
        self._tasks: dict[int, dict] = {}
        self._next_id = 1

    def create_task(self, task_type: str = "design", params: dict | None = None) -> dict:
        """创建新任务，返回任务对象。"""
        assert task_type in TASK_TYPES, f"unknown task type: {task_type}"
        task_id = self._next_id
        self._next_id += 1
        task = {
            "task_id": task_id,
            "type": task_type,
            "status": "pending",
            "progress": 0,
            "stage": "",
            "params": params or {},
            "result": None,
            "error_message": None,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "completed_at": None,
        }
        self._tasks[task_id] = task
        logger.info("[TaskManager] created task %d (type=%s)", task_id, task_type)
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


task_manager = TaskManager()


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


async def _notify(task_id: int, status: str, progress: int, stage: str = "", task: dict | None = None) -> None:
    """统一 WS 通知函数。stage 为可选进度文字描述。可传入 task 对象以携带额外字段。"""
    payload = {
        "type": "task_update",
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "stage": stage,
        "design_id": None,
    }
    if status == "completed" and task and task.get("result"):
        payload["design_id"] = task["result"].get("design_id")
    await notify_manager.broadcast(payload)


# ── Backward-compatible exports ─────────────────────────────────
# design_tasks.py re-exports these for existing importers

async def design_worker(mgr: TaskManager, task_id: int) -> None:
    """后台执行设计生成任务。"""
    from ..services.strategy_design import generate_enhanced_design

    task = mgr.get_task(task_id)
    if not task:
        return

    try:
        mgr.update_task(task_id, status="running", progress=10)
        await _notify(task_id, "running", progress=10)

        params = task.get("params", {})
        capital = params.get("capital", 500000)
        constraints = params.get("constraints")

        mgr.update_task(task_id, progress=30)
        await _notify(task_id, "running", progress=30)

        result = await asyncio.wait_for(
            generate_enhanced_design(
                capital=capital,
                constraints=constraints,
            ),
            timeout=150,
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
                has_error = bool(result.get("error")) or not strategies
                record = PortfolioDesign(
                    capital=capital,
                    risk_profile=params.get("risk_profile", "balanced"),
                    strategies_json=json.dumps(strategies, ensure_ascii=False, default=str),
                    market_snapshot_json=json.dumps(market_context, ensure_ascii=False, default=str),
                    status="failed" if has_error else "completed",
                    error_message=result.get("detail") if not strategies else None,
                )
                db.add(record)
                await db.commit()
                await db.refresh(record)
                design_id = record.id
        except Exception as e:
            logger.exception("[design_worker] failed to save design history: %s", e)

        # 检查结果是否有效：空策略 = 失败（数据源不可用导致）
        error_info = result.get("error")
        if error_info:
            error_msg = f"{error_info}: {result.get('detail', '数据管道未能产出候选标的')}"
            logger.warning("[design_worker] task %d completed but has error: %s", task_id, error_msg)
            mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
            await _notify(task_id, "failed", progress=0)
        elif not strategies:
            logger.warning("[design_worker] task %d completed with 0 strategies — treating as failure", task_id)
            mgr.update_task(task_id, progress=0, status="failed",
                            error_message="策略生成为空：数据源不可用或未找到符合条件的 ETF")
            await _notify(task_id, "failed", progress=0)
        else:
            mgr.update_task(task_id, progress=100, status="completed",
                            result={"strategies": strategies, "market_context": market_context, "design_id": design_id})
            await _notify(task_id, "completed", progress=100, task=mgr.get_task(task_id))

        logger.info("[design_worker] task %d completed with %d strategies",
                    task_id, len(strategies))

    except asyncio.TimeoutError:
        logger.warning("[design_worker] task %d timed out (150s)", task_id)
        mgr.update_task(task_id, status="failed", progress=0, error_message="方案生成超时（150s），数据源响应过慢，请稍后重试")
        await _notify(task_id, "failed", progress=0)
    except Exception as e:
        error_msg = str(e)
        logger.exception("[design_worker] task %d failed: %s", task_id, error_msg)
        mgr.update_task(task_id, status="failed", progress=0, error_message=error_msg)
        await _notify(task_id, "failed", progress=0)
