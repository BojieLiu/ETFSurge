"""Tests for design status via TaskManager (Plan B)."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch


class TestDesignStatus:
    """测试通过 TaskManager 查询设计任务状态。"""

    def test_status_completed(self):
        """验证已完成任务返回 status=completed"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})

        # 模拟 design_worker 执行完毕
        mgr.update_task(1, status="completed", progress=100,
                        result={"strategies": [{"label": "防御型"}], "market_context": {}})

        task = mgr.get_task(1)
        assert task["status"] == "completed"
        assert task["progress"] == 100
        assert "result" in task

    def test_status_running(self):
        """验证进行中任务返回 status=running"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})

        # 模拟 design_worker 执行中
        mgr.update_task(1, status="running", progress=30)

        task = mgr.get_task(1)
        assert task["status"] == "running"
        assert task["progress"] == 30

    def test_status_failed(self):
        """验证失败任务返回 status=failed 并携带错误信息"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})

        # 模拟 design_worker 失败
        mgr.update_task(1, status="failed", progress=50,
                        error_message="API timeout")

        task = mgr.get_task(1)
        assert task["status"] == "failed"
        assert task["progress"] == 50
        assert "API timeout" in task.get("error_message", "")

    def test_status_not_found(self):
        """验证不存在的 task_id 返回 None"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        task = mgr.get_task(999)
        assert task is None
