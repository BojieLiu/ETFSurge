"""Tests for design status via TaskManager (Plan B).

Z27 适配：TaskManager 改为 DB-backed async；测试注入独立测试库（tests/db_fixtures）。
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from tests.db_fixtures import task_db, task_mgr  # noqa: F401


class TestDesignStatus:
    """测试通过 TaskManager 查询设计任务状态。"""

    async def test_status_completed(self, task_mgr):
        """验证已完成任务返回 status=completed"""
        mgr = task_mgr
        t = await mgr.create_task(task_type="design", params={"capital": 500000})

        # 模拟 design_worker 执行完毕
        await mgr.update_task(t["task_id"], status="completed", progress=100,
                              result={"strategies": [{"label": "防御型"}], "market_context": {}})

        task = await mgr.get_task(t["task_id"])
        assert task["status"] == "completed"
        assert task["progress"] == 100
        assert "result" in task

    async def test_status_running(self, task_mgr):
        """验证进行中任务返回 status=running"""
        mgr = task_mgr
        t = await mgr.create_task(task_type="design", params={"capital": 500000})

        # 模拟 design_worker 执行中
        await mgr.update_task(t["task_id"], status="running", progress=30)

        task = await mgr.get_task(t["task_id"])
        assert task["status"] == "running"
        assert task["progress"] == 30

    async def test_status_failed(self, task_mgr):
        """验证失败任务返回 status=failed 并携带错误信息"""
        mgr = task_mgr
        t = await mgr.create_task(task_type="design", params={"capital": 500000})

        # 模拟 design_worker 失败
        await mgr.update_task(t["task_id"], status="failed", progress=50,
                              error_message="API timeout")

        task = await mgr.get_task(t["task_id"])
        assert task["status"] == "failed"
        assert task["progress"] == 50
        assert "API timeout" in task.get("error_message", "")

    async def test_status_not_found(self, task_mgr):
        """验证不存在的 task_id 返回 None"""
        assert await task_mgr.get_task(999) is None
