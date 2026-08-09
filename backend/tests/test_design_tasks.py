"""TDD tests for async design task system.

Z27 适配：TaskManager 改为 DB-backed async；测试注入独立测试库（tests/db_fixtures），
task_id 从 create_task() 返回值取（不再硬编码 1/2）。
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from tests.db_fixtures import task_db, task_mgr  # noqa: F401


class TestDesignTaskManager:
    """测试 TaskManager（DB-backed）"""

    async def test_create_task_returns_incremented_id(self, task_mgr):
        """验证 create_task 返回递增的 task_id"""
        t1 = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        t2 = await task_mgr.create_task(task_type="design", params={"capital": 100000})
        assert t1["status"] == "pending"
        assert t2["task_id"] > t1["task_id"]

    async def test_get_task_returns_correct_task(self, task_mgr):
        """验证 get_task 返回正确任务"""
        t1 = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await task_mgr.create_task(task_type="design", params={"capital": 100000})

        t = await task_mgr.get_task(t1["task_id"])
        assert t is not None
        assert t["params"]["capital"] == 500000

    async def test_get_task_not_found(self, task_mgr):
        """验证不存在的 task_id 返回 None"""
        assert await task_mgr.get_task(999) is None

    async def test_update_task(self, task_mgr):
        """验证 update_task 修改状态和字段"""
        t = await task_mgr.create_task(task_type="design")
        await task_mgr.update_task(t["task_id"], status="running", progress=50)

        task = await task_mgr.get_task(t["task_id"])
        assert task["status"] == "running"
        assert task["progress"] == 50

    async def test_list_tasks_returns_all(self, task_mgr):
        """验证 list_tasks 返回所有任务"""
        for _ in range(3):
            await task_mgr.create_task(task_type="design")

        tasks = await task_mgr.list_tasks()
        assert len(tasks) == 3

    async def test_tasks_survive_manager_recreation(self, task_db):
        """验证重启恢复：同一测试库两个 TaskManager 实例，数据仍在（Z27 A1）"""
        from app.tasks.task_manager import TaskManager

        # 模拟第一次启动
        mgr1 = TaskManager(session_factory=task_db)
        t = await mgr1.create_task(task_type="design", params={"capital": 500000})
        await mgr1.update_task(t["task_id"], status="running", progress=30)

        # 模拟重启：销毁 mgr1，创建 mgr2（同一 session_factory/DB）
        mgr2 = TaskManager(session_factory=task_db)
        got = await mgr2.get_task(t["task_id"])

        assert got is not None, "重启后任务不应丢失"
        assert got["status"] == "running"
        assert got["progress"] == 30
        assert got["params"]["capital"] == 500000



