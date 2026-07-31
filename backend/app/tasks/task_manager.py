"""
task_manager.py — 通用异步任务管理器

泛化 DesignTaskManager 为通用 TaskManager，支持多任务类型。

v2 (design-check-pipeline-redesign):
  - 新增 design_pipeline() 顺序 Pipeline 替代 design_worker + fire-and-forget
  - 修复 market_data_hub NameError
  - 新增 per-stage WS 通知
  - 引入 report_quality 分级

v3 (Z27 task-persistence-redesign):
  - TaskManager 改为 DB-backed（SQLite tasks 表为唯一真相源），删除 JSON 双轨
  - create_task/get_task/update_task/list_tasks/prune_tasks 全部 async
  - 任务完成时 record_id 回写任务行（design → portfolio_designs.id; check → strategy_check_records.id）
  - _notify 携带 record_id + task_type（WS 契约 §2.4.2）
  - 启动收敛把遗留非终态任务标记 failed（main.py）
"""
from __future__ import annotations

import asyncio
import json
import logging
import warnings
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

# Z27 (D11): 模块级 import（单例在模块底部创建，此处 import 无循环依赖风险；
# 测试可通过 patch("app.tasks.task_manager.async_session") 覆盖）
from app.database import async_session
from app.models.portfolio_design import PortfolioDesign
from app.models.task import TaskRecord

logger = logging.getLogger(__name__)

# 设计管线并发限流: 同一时间只允许一个任务运行
# Phase 2.6.3: 防止多个任务叠加导致线程池耗尽
_design_semaphore = asyncio.Semaphore(1)

TASK_TYPES = {
    "design": {"label": "组合设计", "ttl": 600},
    "check":  {"label": "策略检查", "ttl": 600},
    "report": {"label": "市场研判", "ttl": 600},
}

# Z27: 终态任务保留策略（替代原 1h TTL JSON 剪枝）
TERMINAL_STATUSES = ("completed", "completed_with_errors", "failed")
ACTIVE_STATUSES = ("pending", "running", "quick_ready")


class TaskManager:
    """通用异步任务管理器（Z27: DB-backed，tasks 表为唯一真相源）。

    所有任务生命周期状态落 SQLite，进程重启后 GET /tasks 仍返回历史任务。
    不再读写 tasks.json；不再持有进程内 _tasks dict / _next_id。
    """

    # Z27: 终态任务保留期（替代原 1h TTL JSON 剪枝）
    RETENTION_TERMINAL_DAYS = 7          # 终态任务保留天数
    RETENTION_TERMINAL_MAX = 100         # 终态任务最大保留条数

    def __init__(self, persist_path: str | None = None, session_factory=None):
        """D10: session_factory 允许测试注入独立 SQLite 引擎；None → 模块级 async_session。"""
        if persist_path is not None:
            warnings.warn(
                "[TaskManager] persist_path is deprecated (Z27: DB-backed); ignored",
                DeprecationWarning,
                stacklevel=2,
            )
            logger.warning("[TaskManager] persist_path ignored (DB-backed since Z27)")
        # ⚠️ 惰性解析：单例在模块底部创建，而 async_session 在文件顶部 import，
        #    方法内部 `self._session_factory or async_session` 每次调用时取模块级全局，
        #    测试 patch("app.tasks.task_manager.async_session") 因此生效。
        self._session_factory = session_factory

    def _sf(self):
        return self._session_factory or async_session

    async def create_task(self, task_type: str = "design", params: dict | None = None) -> dict:
        """创建新任务（INSERT tasks, status=pending），返回契约 dict。"""
        assert task_type in TASK_TYPES, f"unknown task type: {task_type}"
        async with self._sf()() as db:
            record = TaskRecord(
                task_type=task_type,
                status="pending",
                progress=0,
                stage="",
                params_json=json.dumps(params or {}, ensure_ascii=False, default=str),
                result_json=None,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            logger.info("[TaskManager] created task %d (type=%s)", record.id, task_type)
            await self.prune_tasks()
            return record.to_dict()

    async def get_task(self, task_id: int) -> dict | None:
        """SELECT 任务并返回契约 dict（含 type/stage/params/record_id）。"""
        async with self._sf()() as db:
            record = await db.get(TaskRecord, task_id)
            return record.to_dict() if record else None

    async def update_task(self, task_id: int, **kwargs) -> None:
        """更新任务字段（白名单）。params/result 序列化为 JSON 列；status 终态时写 completed_at。"""
        allowed = {"status", "progress", "stage", "params", "result", "error_message", "record_id"}
        async with self._sf()() as db:
            record = await db.get(TaskRecord, task_id)
            if not record:
                return
            for k, v in kwargs.items():
                if k not in allowed or v is None:
                    continue  # 保留旧语义: None 不覆盖既有值
                if k in ("params", "result"):
                    setattr(record, f"{k}_json", json.dumps(v, ensure_ascii=False, default=str))
                else:
                    setattr(record, k, v)
            if kwargs.get("status") in TERMINAL_STATUSES and record.completed_at is None:
                record.completed_at = datetime.utcnow()
            await db.commit()
            if kwargs.get("status") in TERMINAL_STATUSES:
                await self.prune_tasks()

    async def prune_tasks(self, max_count: int = RETENTION_TERMINAL_MAX,
                          max_age_days: int = RETENTION_TERMINAL_DAYS) -> int:
        """删除超期且超出保留条数的终态任务；活跃任务永不清理。

        单条 SQL：DELETE 终态且 created_at 早于 cutoff 且不在最近 max_count 条内。
        """
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        async with self._sf()() as db:
            subq = (
                select(TaskRecord.id)
                .where(TaskRecord.status.in_(TERMINAL_STATUSES))
                .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
                .limit(max_count)
            )
            result = await db.execute(
                delete(TaskRecord).where(
                    TaskRecord.status.in_(TERMINAL_STATUSES),
                    TaskRecord.created_at < cutoff,
                    TaskRecord.id.not_in(subq),
                )
            )
            await db.commit()
            removed = result.rowcount or 0
            if removed:
                logger.info("[TaskManager] pruned %d old terminal task(s) (kept %d recent, %dd window)",
                            removed, max_count, max_age_days)
            return removed

    async def list_tasks(self, limit: int = 20, offset: int = 0) -> list[dict]:
        """列出任务（created_at DESC, id DESC），分页。"""
        await self.prune_tasks()
        async with self._sf()() as db:
            rows = (await db.execute(
                select(TaskRecord)
                .order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
                .limit(limit)
                .offset(offset)
            )).scalars().all()
            return [r.to_dict() for r in rows]


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


async def _notify(task_id: int, status: str, progress: int, stage: str = "", task: dict | None = None,
                  extra: dict | None = None, record_id: int | None = None,
                  task_type: str | None = None) -> None:
    """统一 WS 通知函数（Z27: 契约 §2.4.2 — 携带 task_type + record_id）。

    record_id: design/check 完成时必填；task_type: 前端据此初始化任务类型/label。
    """
    payload = {
        "type": "task_update",
        "task_id": task_id,
        "task_type": task_type or (task.get("type") if task else None),
        "status": status,
        "progress": progress,
        "stage": stage,
        "design_id": None,
        "record_id": record_id,
        "report_quality": None,
    }
    if status in ("completed", "completed_with_errors") and task and task.get("result"):
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


async def design_pipeline(mgr: TaskManager, task_id: int) -> None:
    """顺序 Pipeline（替代旧的 design_worker + fire-and-forget）。

    Stages: DATA+ENGINE → DB WRITE → LLM REPORT → NOTIFY
    """
    task = await mgr.get_task(task_id)
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
        await mgr.update_task(task_id, status="running", progress=10, stage="数据采集与策略计算中")
        await _notify(task_id, "running", progress=10, stage="数据采集与策略计算中")

        task = await mgr.get_task(task_id)
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
            await mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
            await _notify(task_id, "failed", progress=0)
            return

        if not strategies:
            error_msg = "策略生成为空：数据源不可用或未找到符合条件的 ETF"
            logger.warning("[design_pipeline] task %d completed with 0 strategies — treating as failure", task_id)
            await mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
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
            await mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
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
                    # Z27 (M8): 回写 record_id — 此时 design_id 才产生，须在 :334 的 failed 通知之后
                    await mgr.update_task(task_id, record_id=design_id)
                    # 补发一次 WS 通知携带 record_id（前端同步任务面板的 recordId）
                    await _notify(task_id, "failed", progress=0, record_id=design_id,
                                  task_type="design")
            except Exception as db_e:
                logger.warning("[design_pipeline] failed to save empty allocation to DB: %s", db_e)
            return
        else:
            logger.info("[design_pipeline] task %d: %d/%d strategies have valid non-CASH ETFs",
                        task_id, valid_count, len(strategies))

        # ── Stage 3: quick_ready — 先推送组合方案，让用户可操作 ──
        # （Solution Design S1-C: 渐进状态机）
        await mgr.update_task(task_id, progress=60, status="quick_ready", stage="策略计算完成",
                        result={"strategies": strategies, "market_context": market_context,
                                "report_stage": "quick"})
        await _notify(task_id, "quick_ready", progress=60, stage="策略计算完成",
                      extra={"strategies": strategies, "market_context": market_context})

        # ── Stage 4: DB WRITE (progress 60→75%) ──
        await mgr.update_task(task_id, progress=65, stage="保存方案")
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
            await mgr.update_task(task_id, progress=0, status="completed_with_errors",
                            error_message=f"DB 保存失败: {e}",
                            result={"strategies": strategies, "market_context": market_context})
            await _notify(task_id, "completed_with_errors", progress=0,
                          extra={"strategies": strategies})
            return

        logger.info("[design_pipeline] design_id=%s saved with data summary (%d chars)", design_id, len(design_text))
        await mgr.update_task(task_id, progress=75, stage="方案已保存")
        await _notify(task_id, "quick_ready", progress=75, stage="方案已保存")

        # ── Stage 5: LLM REPORT (progress 75→95%) ──
        await mgr.update_task(task_id, progress=80, stage="LLM 报告生成中")
        await _notify(task_id, "quick_ready", progress=80, stage="LLM 报告生成中")

        try:
            # 从 market_context 取市场情绪，避免直接引用 market_data_hub（NameError 修复）
            market_sentiment = market_context.get("market_sentiment", {}) if market_context else {}

            # OPT-06: LLM 阶段 150s 预算（Z19: 原 35s/90s 对完整 provider-failover 链
            # (primary 90s + fallback 60s) 过紧，主 provider 慢/失败时必超时 → partial）
            llm_analysis = await asyncio.wait_for(
                generate_design_report(
                    strategies=strategies,
                    market_sentiment=market_sentiment,
                    market_context=market_context,
                    plan_tables=plan_tables,
                ),
                timeout=150,
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
            await mgr.update_task(
                task_id,
                progress=100,
                status="completed_with_errors",
                record_id=design_id,
                result={
                    "strategies": strategies,
                    "market_context": market_context,
                    "design_id": design_id,
                    "report_quality": report_quality,
                },
            )
            await _notify(task_id, "completed_with_errors", progress=100, stage="LLM 报告暂不可用",
                          record_id=design_id, task_type="design",
                          extra={"design_id": design_id, "report_quality": report_quality})
            logger.info("[design_pipeline] task %d completed_with_errors (design_id=%s, quality=%s)",
                        task_id, design_id, report_quality)
            return

        await mgr.update_task(task_id, progress=95, stage="报告完成")
        await _notify(task_id, "quick_ready", progress=95, stage="报告完成")

        # ── Stage 6: NOTIFY (progress 95→100%) ──
        await mgr.update_task(
            task_id,
            progress=100,
            status="completed",
            record_id=design_id,
            result={
                "strategies": strategies,
                "market_context": market_context,
                "design_id": design_id,
                "report_quality": report_quality,
            },
        )
        await _notify(task_id, "completed", progress=100, stage="设计完成",
                      record_id=design_id, task_type="design",
                      extra={"design_id": design_id, "report_quality": report_quality})

        logger.info("[design_pipeline] task %d completed (design_id=%s, quality=%s)",
                    task_id, design_id, report_quality)

    except asyncio.TimeoutError:
        error_msg = "方案生成超时，数据源响应过慢，请稍后重试"
        logger.warning("[design_pipeline] task %d timed out", task_id)
        await mgr.update_task(task_id, status="failed", progress=0, error_message=error_msg)
        await _notify(task_id, "failed", progress=0)
        if design_id:
            await mgr.update_task(task_id, record_id=design_id)
            await _save_design_error(design_id, error_msg)
    except Exception as e:
        error_msg = str(e)
        logger.exception("[design_pipeline] task %d failed: %s", task_id, error_msg)
        await mgr.update_task(task_id, status="failed", progress=0, error_message=error_msg)
        await _notify(task_id, "failed", progress=0)
        if design_id:
            await mgr.update_task(task_id, record_id=design_id)
            await _save_design_error(design_id, error_msg)


# ── Backward-compatible alias ─────────────────────────────────
design_worker = design_pipeline
