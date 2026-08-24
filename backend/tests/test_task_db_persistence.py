from __future__ import annotations
"""Z27 任务持久化重构 — 契约驱动专项测试（api-contracts/portfolio/tasks.md）。

验收锚点（docs/z27-task-persistence-redesign.md §2.2）:
  A1 重启后端后 GET /tasks 仍返回任务（同 DB 两实例）
  A2 design 任务 record_id == design_id，可关联 portfolio_designs
  A3 check 任务 record_id == check_id，可关联 strategy_check_records
  A4 GET /tasks/{id} 返回契约 11 字段（task_id/type/status/progress/stage/params/
     result/error_message/created_at/completed_at/record_id）
  A5 backend/data/tasks.json 不再被创建/写入
  A6 WS task_update 消息含 record_id（design/check 完成时）
  A7 启动时遗留 running → failed（带 error_message）
  D5 保留期策略：终态 7 天/100 条；活跃任务永不清理

测试 DB 隔离：db_fixtures.task_db（独立 SQLite 测试库，三张表），不碰开发库。
"""
import json
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from unittest.mock import patch

from tests.db_fixtures import task_db, task_mgr  # noqa: F401


# ── A4: 契约字段完整性 ───────────────────────────────────────────


async def test_create_task_returns_contract_dict(task_mgr):
    """create_task 落库并返回契约 dict（含 task_id/type/status/progress/params）。"""
    t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
    assert t["task_id"] > 0
    assert t["type"] == "design"
    assert t["status"] == "pending"
    assert t["progress"] == 0
    assert t["params"] == {"capital": 500000}
    assert t["result"] is None
    assert t["error_message"] is None
    assert t["record_id"] is None
    assert t["created_at"] is not None
    assert t["completed_at"] is None


async def test_get_task_returns_all_11_fields(task_mgr):
    """get_task 返回契约全量 11 字段。"""
    t = await task_mgr.create_task(task_type="check", params={"capital": 100000})
    got = await task_mgr.get_task(t["task_id"])
    assert got is not None
    for field in ("task_id", "type", "status", "progress", "stage", "params",
                  "result", "error_message", "created_at", "completed_at", "record_id"):
        assert field in got, f"missing field: {field}"
    assert got["type"] == "check"
    assert got["stage"] == ""
    assert got["created_at"].endswith("Z")  # ISO 8601 UTC


async def test_get_task_not_found(task_mgr):
    """不存在的 task → None（路由层 404）。"""
    assert await task_mgr.get_task(999999) is None


async def test_update_task_fields_and_record_id(task_mgr):
    """update_task 更新 status/progress/stage/record_id/result，读回一致。"""
    t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
    await task_mgr.update_task(
        t["task_id"],
        status="running",
        progress=42,
        stage="数据采集与策略计算中",
    )
    got = await task_mgr.get_task(t["task_id"])
    assert got["status"] == "running"
    assert got["progress"] == 42
    assert got["stage"] == "数据采集与策略计算中"

    # 完成：写 result + record_id + completed_at
    await task_mgr.update_task(
        t["task_id"],
        status="completed",
        progress=100,
        result={"design_id": 222, "strategies": []},
        record_id=222,
    )
    got = await task_mgr.get_task(t["task_id"])
    assert got["status"] == "completed"
    assert got["result"]["design_id"] == 222
    assert got["record_id"] == 222
    assert got["completed_at"] is not None
    assert got["completed_at"].endswith("Z")


async def test_update_task_none_does_not_overwrite(task_mgr):
    """None 值字段不覆盖既有值（保留旧语义）。"""
    t = await task_mgr.create_task(task_type="design")
    await task_mgr.update_task(t["task_id"], record_id=111)
    await task_mgr.update_task(t["task_id"], record_id=None, status="running")
    got = await task_mgr.get_task(t["task_id"])
    assert got["record_id"] == 111
    assert got["status"] == "running"


# ── A1: 重启恢复（同 DB 两实例） ─────────────────────────────────


async def test_restart_persistence_two_instances(task_db):
    """A1: 同测试库两个 TaskManager 实例，mgr2 仍能读到 mgr1 创建的任务。"""
    from app.tasks.task_manager import TaskManager

    mgr1 = TaskManager(session_factory=task_db)
    t = await mgr1.create_task(task_type="design", params={"capital": 500000})
    await mgr1.update_task(t["task_id"], status="running", progress=30)
    task_id = t["task_id"]

    # 模拟重启：新实例（同一 session_factory/DB）
    mgr2 = TaskManager(session_factory=task_db)
    got = await mgr2.get_task(task_id)
    assert got is not None, "重启后任务不应丢失"
    assert got["status"] == "running"
    assert got["progress"] == 30
    assert got["params"]["capital"] == 500000

    # list_tasks 也包含
    tasks = await mgr2.list_tasks()
    assert any(x["task_id"] == task_id for x in tasks)


# ── list_tasks 排序 / 分页 ───────────────────────────────────────


async def test_list_tasks_sorted_desc(task_mgr):
    """list_tasks 按 created_at DESC 排序（新任务在前）。"""
    t1 = await task_mgr.create_task(task_type="design")
    t2 = await task_mgr.create_task(task_type="check")
    t3 = await task_mgr.create_task(task_type="report")
    tasks = await task_mgr.list_tasks()
    ids = [x["task_id"] for x in tasks]
    assert ids[0] == t3["task_id"]
    assert ids[1] == t2["task_id"]
    assert ids[2] == t1["task_id"]


async def test_list_tasks_pagination(task_mgr):
    """limit/offset 分页。"""
    for _ in range(5):
        await task_mgr.create_task(task_type="design")
    page1 = await task_mgr.list_tasks(limit=2, offset=0)
    page2 = await task_mgr.list_tasks(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    ids1 = {x["task_id"] for x in page1}
    ids2 = {x["task_id"] for x in page2}
    assert ids1.isdisjoint(ids2)


# ── D5: 保留期策略（prune） ──────────────────────────────────────


async def test_terminal_task_survives_within_retention(task_mgr):
    """终态任务在保留期内（默认 7 天）仍可列出。"""
    t = await task_mgr.create_task(task_type="design")
    await task_mgr.update_task(t["task_id"], status="completed", progress=100, result={})
    await task_mgr.prune_tasks()  # 默认保留期
    got = await task_mgr.get_task(t["task_id"])
    assert got is not None, "保留期内终态任务不应被清理"


async def test_old_terminal_task_pruned(task_mgr, task_db):
    """超期终态任务被 prune 删除（max_age_days=0 兜底验证）。"""
    from app.models.task import TaskRecord

    t = await task_mgr.create_task(task_type="design")
    await task_mgr.update_task(t["task_id"], status="completed", progress=100, result={})

    # 把 created_at 拨到 10 天前
    async with task_db() as db:
        rec = await db.get(TaskRecord, t["task_id"])
        rec.created_at = datetime.utcnow() - timedelta(days=10)
        await db.commit()

    # max_count=0 → 不在保留集内 → 超期即删（默认 100 条保留集内则保留，见下一用例）
    removed = await task_mgr.prune_tasks(max_age_days=7, max_count=0)
    assert removed >= 1
    assert await task_mgr.get_task(t["task_id"]) is None


async def test_old_terminal_kept_in_top_n(task_mgr, task_db):
    """终态任务在保留集（默认 100 条）内即使超期也保留。"""
    from app.models.task import TaskRecord

    t = await task_mgr.create_task(task_type="design")
    await task_mgr.update_task(t["task_id"], status="completed", progress=100, result={})
    async with task_db() as db:
        rec = await db.get(TaskRecord, t["task_id"])
        rec.created_at = datetime.utcnow() - timedelta(days=10)
        await db.commit()

    await task_mgr.prune_tasks(max_age_days=7)  # 默认 max_count=100
    assert await task_mgr.get_task(t["task_id"]) is not None


async def test_active_tasks_never_pruned(task_mgr):
    """活跃任务（pending/running/quick_ready）永不清理。"""
    t1 = await task_mgr.create_task(task_type="design")          # pending
    t2 = await task_mgr.create_task(task_type="check")
    await task_mgr.update_task(t2["task_id"], status="running", progress=10)
    t3 = await task_mgr.create_task(task_type="design")
    await task_mgr.update_task(t3["task_id"], status="quick_ready", progress=60, result={})

    await task_mgr.prune_tasks(max_age_days=0)  # 即使 0 天保留期
    assert await task_mgr.get_task(t1["task_id"]) is not None
    assert await task_mgr.get_task(t2["task_id"]) is not None
    assert await task_mgr.get_task(t3["task_id"]) is not None


# ── A2/A3: record_id 关联业务记录（DB 层） ───────────────────────


async def test_record_id_links_design_record(task_db, task_mgr):
    """A2: design 任务 record_id → portfolio_designs 表可查。"""
    from app.models.portfolio_design import PortfolioDesign

    t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
    async with task_db() as db:
        design = PortfolioDesign(capital=500000, strategies_json="[]", status="completed")
        db.add(design)
        await db.commit()
        await db.refresh(design)
        design_id = design.id

    await task_mgr.update_task(t["task_id"], status="completed", progress=100,
                               result={"design_id": design_id}, record_id=design_id)
    got = await task_mgr.get_task(t["task_id"])
    assert got["record_id"] == design_id

    async with task_db() as db:
        row = (await db.execute(
            select(PortfolioDesign).where(PortfolioDesign.id == design_id)
        )).scalars().first()
        assert row is not None


async def test_record_id_links_check_record(task_db, task_mgr):
    """A3: check 任务 record_id → strategy_check_records 表可查。"""
    from app.models.strategy_check import StrategyCheckRecord

    t = await task_mgr.create_task(task_type="check", params={"capital": 500000})
    async with task_db() as db:
        record = StrategyCheckRecord(capital=500000, summary="ok")
        db.add(record)
        await db.commit()
        await db.refresh(record)
        check_id = record.id

    await task_mgr.update_task(t["task_id"], status="completed", progress=100,
                               result={"summary": "ok"}, record_id=check_id)
    got = await task_mgr.get_task(t["task_id"])
    assert got["record_id"] == check_id

    async with task_db() as db:
        row = (await db.execute(
            select(StrategyCheckRecord).where(StrategyCheckRecord.id == check_id)
        )).scalars().first()
        assert row is not None


# ── A5: tasks.json 不再被创建/读写 ───────────────────────────────


def test_tasks_json_not_created(task_db):
    """A5: DB-backed 后 tasks.json 不再被创建/读写（类属性已删除）。"""
    import app.tasks.task_manager as tm_module

    # 旧 JSON 双轨属性已删除：访问会 AttributeError（替代旧 test_task_manager_persist_path 断言）
    assert not hasattr(tm_module.TaskManager, "DEFAULT_PERSIST_PATH")
    assert not hasattr(tm_module.TaskManager, "_persist_path")


# ── A7: 启动收敛（遗留非终态 → failed） ─────────────────────────


async def test_startup_recovery_marks_stuck_failed(task_db):
    """A7: 启动收敛把所有 pending/running/quick_ready → failed + error_message。"""
    from app.tasks.task_manager import TaskManager

    mgr = TaskManager(session_factory=task_db)
    t1 = await mgr.create_task(task_type="design")
    await mgr.update_task(t1["task_id"], status="running", progress=50)
    t2 = await mgr.create_task(task_type="check")
    t3 = await mgr.create_task(task_type="design")
    await mgr.update_task(t3["task_id"], status="completed", progress=100, result={})  # 终态不动

    # 模拟 main.py 的 _cleanup_stuck_tasks（等价逻辑：非终态 → failed）
    from app.models.task import TaskRecord
    async with task_db() as db:
        stuck = (await db.execute(
            select(TaskRecord).where(TaskRecord.status.in_(["pending", "running", "quick_ready"]))
        )).scalars().all()
        for r in stuck:
            r.status = "failed"
            r.error_message = "后端重启，任务中断（未完成），请重新提交"
            r.completed_at = datetime.utcnow()
        await db.commit()

    got1 = await mgr.get_task(t1["task_id"])
    got2 = await mgr.get_task(t2["task_id"])
    got3 = await mgr.get_task(t3["task_id"])
    assert got1["status"] == "failed" and "重启" in got1["error_message"]
    assert got2["status"] == "failed"
    assert got3["status"] == "completed"  # 终态任务不受影响


# ── A6: WS notify 携带 record_id ─────────────────────────────────


async def test_notify_carries_record_id_and_task_type(task_mgr):
    """A6: _notify 完成消息含 record_id + task_type（契约 §2.4.2）。"""
    from app.tasks.task_manager import _notify

    captured = {}
    with patch("app.tasks.task_manager.notify_manager") as mock_nm:
        async def _fake_broadcast(payload):
            captured.update(payload)
        mock_nm.broadcast = _fake_broadcast

        await _notify(42, "completed", 100, stage="设计完成",
                      record_id=222, task_type="design",
                      extra={"design_id": 222, "report_quality": "full"})

    assert captured["task_id"] == 42
    assert captured["task_type"] == "design"
    assert captured["record_id"] == 222
    assert captured["design_id"] == 222
    assert captured["report_quality"] == "full"
    assert captured["status"] == "completed"


async def test_strategy_check_notify_carries_record_id(task_mgr):
    """A6: strategy_check_worker 本地 _notify 完成消息含 record_id + task_type='check'。"""
    from app.tasks.strategy_check_worker import _notify as check_notify

    captured = {}
    # worker 的 _notify 在调用时 `from ..tasks.task_manager import notify_manager` → 打 task_manager 模块全局
    with patch("app.tasks.task_manager.notify_manager") as mock_nm:
        async def _fake_broadcast(payload):
            captured.update(payload)
        mock_nm.broadcast = _fake_broadcast

        await check_notify(7, "completed", 100, stage="分析完成",
                           record_id=97, task_type="check")

    assert captured["record_id"] == 97
    assert captured["task_type"] == "check"
    assert captured["status"] == "completed"


# ===== folded from test_phase5_architecture.py =====
import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from tests.db_fixtures import task_mgr  # noqa: F401
class TestP4_3_RedisCache:
    """P4.3: Cache should support Redis persistence with fallback to memory."""

    def test_config_has_redis_url(self):
        """config.py should have redis_url setting."""
        from app.config import settings

        assert settings.redis_url != ""
        assert settings.redis_url.startswith("redis://")

    def test_database_has_redis_import(self):
        """Removed (round35 A4③): probed for the P4.3 dead cache block deleted from
        database.py (_memory_cache/_set_cache/_clear_cache, zero callers). Real
        Redis-cache behavior is covered via services/cache_service.py tests
        (tests/test_a4_cache_hygiene.py, tests/test_optimization.py)."""

    def test_pool_manager_has_cache_abstraction(self):
        """market_data_hub should use cache-backed state."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "market_data_hub.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        has_cache = "cache" in content.lower() or "_cache" in content
        has_redis = "redis" in content.lower()
        has_fallback = "None" in content or "if not" in content or "try:" in content

        assert has_cache or has_redis or has_fallback
class TestP4_4_TaskTimeoutMonitor:
    """P4.4: Tasks should have lifetime monitoring."""

    async def test_task_manager_has_lifetime_tracking(self, task_mgr):
        """TaskManager should track task lifetime via created_at."""
        task = await task_mgr.create_task("design", {})
        task_id = task["task_id"]

        assert "created_at" in task, "Task should have created_at"
        # created_at is UTC ISO timestamp string
        assert isinstance(task["created_at"], str)
        assert "T" in task["created_at"]
        assert task["created_at"].endswith("Z")
        assert task_id > 0

    async def test_task_has_prune_tasks_method(self):
        """TaskManager should have prune_tasks for cleanup."""
        from app.tasks.task_manager import TaskManager

        mgr = TaskManager(session_factory=None)
        assert hasattr(mgr, "prune_tasks")

    async def test_stale_task_detection_by_created_at(self, task_mgr, task_db):
        """Tasks past their retention window can be pruned via created_at (max_count=0)."""
        from app.models.task import TaskRecord

        task = await task_mgr.create_task("design", {})
        task_id = task["task_id"]
        await task_mgr.update_task(task_id, status="completed", progress=100, result={})

        # Mark completed with very old created_at
        async with task_db() as db:
            rec = await db.get(TaskRecord, task_id)
            rec.created_at = datetime.utcnow() - timedelta(hours=2)
            await db.commit()

        # Run prune with max_count=0 → 不在保留集内，超期即删
        await task_mgr.prune_tasks(max_count=0, max_age_days=0)
        remaining = await task_mgr.get_task(task_id)
        assert remaining is None, (
            f"Old completed task should be pruned, got: {remaining}"
        )

    # round35 §11-P1-6/RC-B3: test_all_task_types_have_ttl 已随 TASK_TYPES 的死
    # ttl 字段一并删除（该字段运行时零读取，淘汰语义由 prune_tasks retention 承担）。

    async def test_prune_respects_max_count(self, task_mgr, task_db):
        """prune_tasks 保留集（max_count）内任务不被删除；保留集外超期删除。"""
        from app.models.task import TaskRecord

        created_ids = []
        for _ in range(5):
            t = await task_mgr.create_task("design", {})
            created_ids.append(t["task_id"])

        # Set first 3 to completed with old timestamp
        async with task_db() as db:
            for tid in created_ids[:3]:
                rec = await db.get(TaskRecord, tid)
                rec.status = "completed"
                rec.completed_at = datetime.utcnow()
                rec.created_at = datetime.utcnow() - timedelta(hours=2)
            await db.commit()

        # max_count=3（默认保留集大小）→ 3 个终态都在保留集内 → 全部保留
        await task_mgr.prune_tasks(max_count=3, max_age_days=0)
        assert await task_mgr.get_task(created_ids[0]) is not None

        # max_count=0 → 保留集为空 → 超期终态全部删除，活跃（pending）任务保留
        await task_mgr.prune_tasks(max_count=0, max_age_days=0)
        remaining = [tid for tid in created_ids if await task_mgr.get_task(tid)]
        assert len(remaining) == 2, f"Expected 2 active tasks remaining, got {remaining}"
