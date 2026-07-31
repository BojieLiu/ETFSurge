"""
task_manager.py — 通用异步任务管理器

泛化 DesignTaskManager 为通用 TaskManager，支持多任务类型。

v2 (design-check-pipeline-redesign):
  - 新增 design_pipeline() 顺序 Pipeline 替代 design_worker + fire-and-forget
  - 修复 market_data_hub NameError
  - 新增 per-stage WS 通知
  - 引入 report_quality 分级
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 设计管线并发限流: 同一时间只允许一个任务运行
# Phase 2.6.3: 防止多个任务叠加导致线程池耗尽
_design_semaphore = asyncio.Semaphore(1)

TASK_TYPES = {
    "design": {"label": "组合设计", "ttl": 600},
    "check":  {"label": "策略检查", "ttl": 600},
    "report": {"label": "市场研判", "ttl": 600},
}


class TaskManager:
    """通用异步任务管理器。持久化到 JSON 文件，支持重启恢复。
    
    默认不持久化（persist_path=None）。需要持久化时显式传入路径。
    单例 task_manager 默认使用 DEFAULT_PERSIST_PATH。
    """

    # Z27: Fix path - task_manager.py is in app/tasks/, data/ is at project root (backend/data/)
    DEFAULT_PERSIST_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "tasks.json")

    def __init__(self, persist_path: str | None = None):
        self._tasks: dict[int, dict] = {}
        self._next_id = 1
        self._persist_path = persist_path  # None = 不持久化
        self._load()  # 恢复持久化的任务（仅 persist_path 非 None 时）

    def _save(self) -> None:
        """将任务列表持久化到 JSON 文件。"""
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            data = {
                "tasks": list(self._tasks.values()),
                "next_id": self._next_id,
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("[TaskManager] persist save failed: %s", e)

    def _load(self) -> None:
        """从 JSON 文件恢复持久化的任务列表。"""
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            restored = data.get("tasks", [])
            for t in restored:
                tid = t.get("task_id")
                if tid is not None:
                    self._tasks[tid] = t
            self._next_id = max(data.get("next_id", 1), (max(self._tasks.keys(), default=0) + 1))
            logger.info("[TaskManager] restored %d tasks from %s", len(restored), self._persist_path)
        except Exception as e:
            logger.warning("[TaskManager] persist load failed: %s", e)

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
        self._save()
        self.prune_tasks()
        logger.info("[TaskManager] created task %d (type=%s)", task_id, task_type)
        return task

    def get_task(self, task_id: int) -> dict | None:
        task = self._tasks.get(task_id)
        if task:
            # Ensure progress, stage, status are always present
            task.setdefault("progress", 0)
            task.setdefault("stage", "")
            task.setdefault("status", "pending")
        return task

    def update_task(self, task_id: int, **kwargs) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        for k, v in kwargs.items():
            if v is not None:
                task[k] = v
        if kwargs.get("status") == "completed":
            task["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()
        if kwargs.get("status") in ("completed", "failed"):
            self.prune_tasks()

    def prune_tasks(self, max_count: int = 20, max_age_seconds: int = 3600) -> int:
        """清理过期的已完成/失败任务，保留最新的 N 个。
        
        Args:
            max_count: 保留的最大任务数
            max_age_seconds: 已完成/失败任务的最长保留时间（秒）
        
        Returns:
            清理的任务数
        """
        now = time.time()
        # 解析 ISO 时间戳为时间戳
        def _ts(t):
            try:
                # created_at is UTC, but strptime creates a naive datetime.
                # .timestamp() on naive datetime treats it as LOCAL time,
                # causing timezone-dependent age miscalculation.
                # Fix: use timezone.utc to make the timestamp UTC-aware.
                dt = datetime.strptime(t["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                from datetime import timezone as _tz
                return dt.replace(tzinfo=_tz.utc).timestamp()
            except Exception:
                return 0
        
        terminal = {"completed", "failed"}
        active = {"pending", "running"}
        
        # 分离活跃和终端任务
        active_tasks = {tid: t for tid, t in self._tasks.items() if t.get("status") in active}
        terminal_tasks = [(tid, t) for tid, t in self._tasks.items() if t.get("status") in terminal]
        
        # 按创建时间降序排列终端任务
        terminal_tasks.sort(key=lambda x: -_ts(x[1]))
        
        # 保留最新的 N 个终端任务
        keep = set()
        for tid, t in terminal_tasks[:max_count]:
            keep.add(tid)
        
        # 删除超时的和超出数量的终端任务
        removed = 0
        for tid, t in terminal_tasks:
            if tid in keep:
                # 检查是否在老化窗口内（创建时间 < max_age_seconds）
                age = now - _ts(t)
                if age <= max_age_seconds:
                    continue
            # 不在 keep 中或超时 → 删除
            if tid in self._tasks:
                del self._tasks[tid]
                removed += 1
        
        self._save()
        if removed:
            logger.info("[TaskManager] pruned %d old terminal tasks (kept %d active + %d recent)", 
                        removed, len(active_tasks), len(keep))
        return removed

    def list_tasks(self, limit: int = 20, offset: int = 0) -> list[dict]:
        self.prune_tasks(max_count=max(20, limit * 2))
        tasks = sorted(self._tasks.values(), key=lambda t: -t["task_id"])
        return tasks[offset:offset + limit]


task_manager = TaskManager(persist_path=os.path.abspath(TaskManager.DEFAULT_PERSIST_PATH))


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
        logger.warning("[design_pipeline] failed to save error to design_id=%s: %s", design_id, e)


from app.database import async_session
from app.models.portfolio_design import PortfolioDesign


async def design_pipeline(mgr: TaskManager, task_id: int) -> None:
    """顺序 Pipeline（替代旧的 design_worker + fire-and-forget）。

    Stages: DATA+ENGINE → DB WRITE → LLM REPORT → NOTIFY
    """
    task = mgr.get_task(task_id)
    if not task:
        return

    # 并发限流：同一时间只允许一个设计/检查任务运行
    if not _design_semaphore.locked():
        async with _design_semaphore:
            return await _design_pipeline_with_semaphore(mgr, task_id)
    else:
        logger.warning("[design_pipeline] task %d waiting: another design task in progress", task_id)
        async with _design_semaphore:
            return await _design_pipeline_with_semaphore(mgr, task_id)


async def _design_pipeline_with_semaphore(mgr: "TaskManager", task_id: int) -> None:
    """实际的设计管线逻辑，被 _design_semaphore 保护。"""
    # Lazy imports moved here from design_pipeline to be in the correct scope
    from ..services.strategy_design import generate_enhanced_design
    from ..tasks.design_report import _build_plan_tables
    from ..analysis.llm import generate_design_report

    design_id = None
    strategies = []
    market_context = {}
    report_quality = "none"

    try:
        mgr.update_task(task_id, status="running", progress=10, stage="数据采集与策略计算中")
        await _notify(task_id, "running", progress=10, stage="数据采集与策略计算中")

        task = mgr.get_task(task_id)
        if not task:
            logger.error("[design_pipeline] task %d not found after start", task_id)
            return
        params = task.get("params", {})
        capital = params.get("capital", 500000)
        constraints = params.get("constraints")

        # ── Stage 1&2: DATA + ENGINE (combined via generate_enhanced_design) ──
        # OPT-06: 超时预算拆分，DATA 阶段 45s 上限
        result = await asyncio.wait_for(
            generate_enhanced_design(
                capital=capital,
                constraints=constraints,
            ),
            timeout=45,  # OPT-06: DATA 阶段 45s 预算（原 90s 总预算拆分为三段）
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

        # Phase 2.7.1: 逐策略校验非空（非 CASH 标的 >= 1 只）
        # 修复 A: 降级为"至少有一套策略有非 CASH 标的即成功"
        # 无有效标的的策略填充全 CASH + warning 而非让整次设计失败
        valid_count = 0
        for s in strategies:
            etfs = s.get("etfs") or []
            non_cash = [a for a in etfs if a.get("symbol") != "CASH"]
            if len(non_cash) >= 1:
                valid_count += 1
            else:
                logger.warning(
                    "[design_pipeline] task %d strategy '%s' has no non-CASH ETFs — filling with CASH",
                    task_id, s.get("id", "?"),
                )
                s["etfs"] = [{"symbol": "CASH", "name": "现金", "weight": 1.0, "layer": "cash",
                              "selection_rationale": "当前估值/行情数据下无合适标的，全部现金保留"}]
                s["warning"] = "本方案在当前市场状态下无符合条件 ETF，全部配置现金"
        if valid_count == 0:
            # Q01/Q03: Empty allocation → mark as failed with specific error_message
            error_msg = "分配引擎未输出有效ETF标的：所有方案均为100%现金。因子评分均低于阈值或数据源不可用。"
            logger.warning("[design_pipeline] task %d: %s", task_id, error_msg)
            mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
            await _notify(task_id, "failed", progress=0)
            # Also save to DB with report_quality="empty"
            try:
                async with async_session() as db:
                    record = PortfolioDesign(
                        capital=params.get("capital", 500000),
                        risk_profile=params.get("risk_profile", "balanced"),
                        strategies_json=json.dumps(strategies, ensure_ascii=False, default=str),
                        market_snapshot_json=json.dumps(market_context, ensure_ascii=False, default=str),
                        design_text="",
                        report_quality="empty",
                        status="failed",
                        error_message=error_msg,
                    )
                    db.add(record)
                    await db.commit()
                    await db.refresh(record)
                    design_id = record.id
                    logger.info("[design_pipeline] empty allocation saved as design_id=%s (quality=empty)", design_id)
            except Exception as db_e:
                logger.warning("[design_pipeline] failed to save empty allocation to DB: %s", db_e)
            return
        else:
            logger.info("[design_pipeline] task %d: %d/%d strategies have valid non-CASH ETFs",
                        task_id, valid_count, len(strategies))

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

        logger.info("[design_pipeline] design_id=%s saved with data summary (%d chars)", design_id, len(design_text))
        mgr.update_task(task_id, progress=75, stage="方案已保存")
        await _notify(task_id, "quick_ready", progress=75, stage="方案已保存")

        # ── Stage 5: LLM REPORT (progress 75→95%) ──
        mgr.update_task(task_id, progress=80, stage="LLM 报告生成中")
        await _notify(task_id, "quick_ready", progress=80, stage="LLM 报告生成中")

        try:
            # 从 market_context 取市场情绪，避免直接引用 market_data_hub（NameError 修复）
            market_sentiment = market_context.get("market_sentiment", {}) if market_context else {}

            # OPT-06: LLM 阶段 35s 预算
            llm_analysis = await asyncio.wait_for(
                generate_design_report(
                    strategies=strategies,
                    market_sentiment=market_sentiment,
                    market_context=market_context,
                    plan_tables=plan_tables,
                ),
                timeout=35,  # OPT-06: LLM 报告 35s 预算
            )

            if llm_analysis and len(llm_analysis.strip()) > 0:
                full_text = design_text + "\n\n## 二、市场环境与配置建议\n\n" + llm_analysis
                try:
                    async with async_session() as db:
                        d = await db.get(PortfolioDesign, design_id)
                        if d:
                            d.design_text = full_text
                            # Q03: Check if strategies have real ETFs before marking "full"
                            has_real_etfs = any(
                                e.get("symbol") != "CASH"
                                for s in strategies
                                for e in (s.get("etfs") or [])
                            )
                            d.report_quality = "full" if has_real_etfs else "partial"
                            d.report_generated_at = datetime.utcnow()
                            await db.commit()
                            logger.info("[design_pipeline] report saved to design_id=%s (%d chars, quality=%s)",
                                        design_id, len(full_text), d.report_quality)
                except Exception as e:
                    logger.warning("[design_pipeline] DB update for LLM report failed: %s", e)
                report_quality = "full"
            else:
                logger.warning("[design_pipeline] LLM returned empty report for design_id=%s", design_id)
                try:
                    async with async_session() as db:
                        d = await db.get(PortfolioDesign, design_id)
                        if d:
                            # Q03: LLM timed out but allocation succeeded → partial
                            d.report_quality = "partial"
                            await db.commit()
                except Exception as e:
                    logger.warning("[design_pipeline] DB update for partial fallback failed: %s", e)
                report_quality = "partial"

        except Exception as e:
            logger.warning("[design_pipeline] LLM report generation failed for design_id=%s: %s", design_id, e)
            # Q03: Mark as partial — allocation succeeded but LLM failed
            try:
                async with async_session() as db:
                    d = await db.get(PortfolioDesign, design_id)
                    if d:
                        d.report_quality = "partial"
                        await db.commit()
            except Exception as db_e:
                logger.warning("[design_pipeline] DB update after LLM failure failed: %s", db_e)
            report_quality = "partial"
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
            logger.info("[design_pipeline] task %d completed_with_errors (design_id=%s, quality=%s)",
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

        logger.info("[design_pipeline] task %d completed (design_id=%s, quality=%s)",
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
