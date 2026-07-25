"""
task_manager.py — 通用异步任务管理器

泛化 DesignTaskManager 为通用 TaskManager，支持多任务类型。

v2 (design-check-pipeline-redesign):
  - 新增 design_pipeline() 顺序 Pipeline 替代 design_worker + fire-and-forget
  - 修复 pool_manager NameError
  - 新增 per-stage WS 通知
  - 引入 report_quality 分级
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
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


async def _notify(task_id: int, status: str, progress: int, stage: str = "", task: dict | None = None, extra: dict | None = None) -> None:
    """统一 WS 通知函数。stage 为可选进度文字描述。可传入 task 对象以携带额外字段。"""
    payload = {
        "type": "task_update",
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "stage": stage,
        "design_id": None,
        "report_quality": None,
    }
    if status == "completed" and task and task.get("result"):
        payload["design_id"] = task["result"].get("design_id")
        payload["report_quality"] = task["result"].get("report_quality")
    if extra:
        payload.update(extra)
    await notify_manager.broadcast(payload)


async def _save_design_error(design_id: int | None, error_msg: str) -> None:
    """将错误信息保存到 PortfolioDesign DB 记录。"""
    if design_id is None:
        return
    try:
        async with async_session() as db:
            d = await db.get(PortfolioDesign, design_id)
            if d:
                d.status = "failed"
                d.error_message = error_msg
                await db.commit()
    except Exception as e:
        logger.warning("[design_pipeline] failed to save error to design_id=%d: %s", design_id, e)


from app.database import async_session
from app.models.portfolio_design import PortfolioDesign


async def design_pipeline(mgr: TaskManager, task_id: int) -> None:
    """顺序 Pipeline（替代旧的 design_worker + fire-and-forget）。

    Stages: DATA+ENGINE → DB WRITE → LLM REPORT → NOTIFY
    """
    from ..services.strategy_design import generate_enhanced_design
    from ..tasks.design_report import _build_plan_tables
    from ..analysis.llm import generate_design_report

    task = mgr.get_task(task_id)
    if not task:
        return

    design_id = None
    strategies = []
    market_context = {}
    report_quality = "none"

    try:
        mgr.update_task(task_id, status="running", progress=10, stage="数据采集与策略计算中")
        await _notify(task_id, "running", progress=10, stage="数据采集与策略计算中")

        params = task.get("params", {})
        capital = params.get("capital", 500000)
        constraints = params.get("constraints")

        # ── Stage 1&2: DATA + ENGINE (combined via generate_enhanced_design) ──
        # pool_manager.refresh() 内部有 60s timeout + 空池保护，此处给 90s 总预算
        result = await asyncio.wait_for(
            generate_enhanced_design(
                capital=capital,
                constraints=constraints,
            ),
            timeout=90,  # 60s (DATA refresh max) + 10s (ENGINE) + 20s buffer
        )

        strategies = result.get("strategies", [])
        market_context = result.get("market_context", {})

        # 检查结果是否有效
        error_info = result.get("error")
        if error_info:
            error_msg = f"{error_info}: {result.get('detail', '数据管道未能产出候选标的')}"
            logger.warning("[design_pipeline] task %d has error: %s", task_id, error_msg)
            mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
            await _notify(task_id, "failed", progress=0)
            return

        if not strategies:
            error_msg = "策略生成为空：数据源不可用或未找到符合条件的 ETF"
            logger.warning("[design_pipeline] task %d completed with 0 strategies — treating as failure", task_id)
            mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
            await _notify(task_id, "failed", progress=0)
            return

        # ── Stage 3: quick_ready — 先推送组合方案，让用户可操作 ──
        # （Solution Design S1-C: 渐进状态机）
        mgr.update_task(task_id, progress=60, status="quick_ready", stage="策略计算完成",
                        result={"strategies": strategies, "market_context": market_context,
                                "report_stage": "quick"})
        await _notify(task_id, "quick_ready", progress=60, stage="策略计算完成",
                      extra={"strategies": strategies, "market_context": market_context})

        # ── Stage 4: DB WRITE (progress 60→75%) ──
        mgr.update_task(task_id, progress=65, stage="保存方案")
        await _notify(task_id, "quick_ready", progress=65, stage="保存方案")

        plan_tables = _build_plan_tables(strategies)
        design_text = "# ETF 组合设计方案\n\n## 一、三种方案详解\n\n" + plan_tables

        try:
            async with async_session() as db:
                record = PortfolioDesign(
                    capital=capital,
                    risk_profile=params.get("risk_profile", "balanced"),
                    strategies_json=json.dumps(strategies, ensure_ascii=False, default=str),
                    market_snapshot_json=json.dumps(market_context, ensure_ascii=False, default=str),
                    design_text=design_text,
                    report_quality="pending",
                    status="completed",
                )
                db.add(record)
                await db.commit()
                await db.refresh(record)
                design_id = record.id
        except Exception as e:
            logger.exception("[design_pipeline] DB write failed for task %d: %s", task_id, e)
            mgr.update_task(task_id, progress=0, status="completed_with_errors",
                            error_message=f"DB 保存失败: {e}",
                            result={"strategies": strategies, "market_context": market_context})
            await _notify(task_id, "completed_with_errors", progress=0,
                          extra={"strategies": strategies})
            return

        logger.info("[design_pipeline] design_id=%d saved with data summary (%d chars)", design_id, len(design_text))
        mgr.update_task(task_id, progress=75, stage="方案已保存")
        await _notify(task_id, "quick_ready", progress=75, stage="方案已保存")

        # ── Stage 5: LLM REPORT (progress 75→95%) ──
        mgr.update_task(task_id, progress=80, stage="LLM 报告生成中")
        await _notify(task_id, "quick_ready", progress=80, stage="LLM 报告生成中")

        try:
            # 从 market_context 取市场情绪，避免直接引用 pool_manager（NameError 修复）
            market_sentiment = market_context.get("market_sentiment", {}) if market_context else {}

            llm_analysis = await generate_design_report(
                strategies=strategies,
                market_sentiment=market_sentiment,
                market_context=market_context,
                plan_tables=plan_tables,
            )
            # generate_design_report 的 provider timeout 由 config 控制
            # primary=90s, fallback=60s, 不额外包裹 asyncio.wait_for

            if llm_analysis and len(llm_analysis.strip()) > 0:
                full_text = design_text + "\n\n## 二、市场环境与配置建议\n\n" + llm_analysis
                try:
                    async with async_session() as db:
                        d = await db.get(PortfolioDesign, design_id)
                        if d:
                            d.design_text = full_text
                            d.report_quality = "full"
                            d.report_generated_at = datetime.utcnow()
                            await db.commit()
                            logger.info("[design_pipeline] report saved to design_id=%d (%d chars, quality=full)",
                                        design_id, len(full_text))
                except Exception as e:
                    logger.warning("[design_pipeline] DB update for LLM report failed: %s", e)
                report_quality = "full"
            else:
                logger.warning("[design_pipeline] LLM returned empty report for design_id=%d", design_id)
                try:
                    async with async_session() as db:
                        d = await db.get(PortfolioDesign, design_id)
                        if d:
                            d.report_quality = "fallback"
                            await db.commit()
                except Exception as e:
                    logger.warning("[design_pipeline] DB update for fallback failed: %s", e)
                report_quality = "fallback"

        except Exception as e:
            logger.warning("[design_pipeline] LLM report generation failed for design_id=%d: %s", design_id, e)
            # 标记为 completed_with_errors，数据摘要仍然可用
            try:
                async with async_session() as db:
                    d = await db.get(PortfolioDesign, design_id)
                    if d:
                        d.report_quality = "fallback"
                        await db.commit()
            except Exception as db_e:
                logger.warning("[design_pipeline] DB update after LLM failure failed: %s", db_e)
            report_quality = "fallback"
            mgr.update_task(
                task_id,
                progress=100,
                status="completed_with_errors",
                result={
                    "strategies": strategies,
                    "market_context": market_context,
                    "design_id": design_id,
                    "report_quality": report_quality,
                },
            )
            await _notify(task_id, "completed_with_errors", progress=100, stage="LLM 报告暂不可用",
                          extra={"design_id": design_id, "report_quality": report_quality})
            logger.info("[design_pipeline] task %d completed_with_errors (design_id=%d, quality=%s)",
                        task_id, design_id, report_quality)
            return

        mgr.update_task(task_id, progress=95, stage="报告完成")
        await _notify(task_id, "quick_ready", progress=95, stage="报告完成")

        # ── Stage 6: NOTIFY (progress 95→100%) ──
        mgr.update_task(
            task_id,
            progress=100,
            status="completed",
            result={
                "strategies": strategies,
                "market_context": market_context,
                "design_id": design_id,
                "report_quality": report_quality,
            },
        )
        await _notify(task_id, "completed", progress=100, stage="设计完成",
                      extra={"design_id": design_id, "report_quality": report_quality})

        logger.info("[design_pipeline] task %d completed (design_id=%d, quality=%s)",
                    task_id, design_id, report_quality)

    except asyncio.TimeoutError:
        error_msg = "方案生成超时，数据源响应过慢，请稍后重试"
        logger.warning("[design_pipeline] task %d timed out", task_id)
        mgr.update_task(task_id, status="failed", progress=0, error_message=error_msg)
        await _notify(task_id, "failed", progress=0)
        if design_id:
            await _save_design_error(design_id, error_msg)
    except Exception as e:
        error_msg = str(e)
        logger.exception("[design_pipeline] task %d failed: %s", task_id, error_msg)
        mgr.update_task(task_id, status="failed", progress=0, error_message=error_msg)
        await _notify(task_id, "failed", progress=0)
        if design_id:
            await _save_design_error(design_id, error_msg)


# ── Backward-compatible alias ─────────────────────────────────
design_worker = design_pipeline
