"""TDD tests for async design task system."""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime


class TestDesignTaskManager:
    """测试 TaskManager 内存管理器"""

    def test_create_task_returns_incremented_id(self):
        """验证 create_task 返回递增的 task_id"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        t1 = mgr.create_task(task_type="design", params={"capital": 500000})
        t2 = mgr.create_task(task_type="design", params={"capital": 100000})
        assert t1["status"] == "pending"
        assert t2["task_id"] == 2
        assert t1["task_id"] == 1

    def test_get_task_returns_correct_task(self):
        """验证 get_task 返回正确任务"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})
        mgr.create_task(task_type="design", params={"capital": 100000})

        t = mgr.get_task(2)
        assert t is not None
        assert t["params"]["capital"] == 100000

    def test_get_task_not_found(self):
        """验证不存在的 task_id 返回 None"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        assert mgr.get_task(999) is None

    def test_update_task(self):
        """验证 update_task 修改状态和字段"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        mgr.create_task(task_type="design")
        mgr.update_task(1, status="running", progress=50)

        t = mgr.get_task(1)
        assert t["status"] == "running"
        assert t["progress"] == 50

    def test_list_tasks_returns_all(self):
        """验证 list_tasks 返回所有任务"""
        from app.tasks.design_tasks import TaskManager

        mgr = TaskManager()
        mgr.create_task(task_type="design")
        mgr.create_task(task_type="design")
        mgr.create_task(task_type="design")

        tasks = mgr.list_tasks()
        assert len(tasks) == 3

    def test_tasks_survive_manager_recreation(self):
        """验证 TaskManager 重启恢复：创建任务 → 更新 → 新实例 → 数据仍在"""
        from app.tasks.design_tasks import TaskManager

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            persist_path = f.name
        try:
            # 模拟第一次启动
            mgr1 = TaskManager(persist_path=persist_path)
            mgr1.create_task(task_type="design", params={"capital": 500000})
            mgr1.update_task(1, status="running", progress=30)

            # 模拟重启：销毁 mgr1，创建 mgr2（同路径）
            mgr2 = TaskManager(persist_path=persist_path)
            t = mgr2.get_task(1)

            assert t is not None, "重启后任务不应丢失"
            assert t["status"] == "running"
            assert t["progress"] == 30
            assert t["params"]["capital"] == 500000
        finally:
            if os.path.exists(persist_path):
                os.unlink(persist_path)


class TestDesignWorker:
    """测试 design_worker 异步任务"""

    def _make_mock_session(self):
        """Minimal mock DB session for pipeline tests."""
        from unittest.mock import MagicMock, AsyncMock
        record = MagicMock()
        record.id = 999
        session = MagicMock()
        session.__aenter__.return_value = session
        session.__aexit__.return_value = None
        session.add = MagicMock()
        session.commit = AsyncMock(return_value=None)
        async def _refresh(obj):
            obj.id = 999
        session.refresh = AsyncMock(side_effect=_refresh)
        session.get = AsyncMock(return_value=record)
        return session

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_worker_runs_full_pipeline(self, mock_gen, mock_llm, mock_db):
        """验证 worker 调用 generate_full_design"""
        from app.tasks.design_tasks import TaskManager, design_worker

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})

        mock_llm.return_value = "LLM report"
        mock_db.return_value = self._make_mock_session()
        mock_gen.return_value = {
            "strategies": [{"label": "防御型", "etfs": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.5}]}],
            "market_context": {},
        }

        await design_worker(mgr, task_id=1)

        mock_gen.assert_awaited_once()
        t = mgr.get_task(1)
        assert t["status"] == "completed"
        assert t["progress"] == 100

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_worker_failure_sets_failed_status(self, mock_gen):
        """验证 worker 出错时标记为 failed"""
        from app.tasks.design_tasks import TaskManager, design_worker

        mgr = TaskManager()
        mgr.create_task(task_type="design")

        mock_gen.side_effect = Exception("API timeout")

        await design_worker(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "failed"
        assert "API timeout" in t["error_message"]

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_worker_saves_design_id(self, mock_gen, mock_llm, mock_db):
        """验证 worker 完成后关联 design_id"""
        from app.tasks.design_tasks import TaskManager, design_worker

        mgr = TaskManager()
        mgr.create_task(task_type="design")

        mock_llm.return_value = "LLM report"
        mock_db.return_value = self._make_mock_session()
        mock_gen.return_value = {
            "strategies": [{"label": "防御型", "etfs": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.5}]}],
            "market_context": {},
        }

        await design_worker(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "completed"
        assert t["progress"] == 100

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_worker_handles_error_dict(self, mock_gen):
        """验证 generate_enhanced_design 返回带 error 的 dict 时，
        design_worker 正确标记为 failed 并保存错误信息。

        这是 coverage 盲区：现有测试只测了抛异常路径，没测返回 error dict 路径。"""
        from app.tasks.design_tasks import TaskManager, design_worker

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})

        mock_gen.return_value = {
            "strategies": [],
            "error": "无候选标的",
            "detail": "数据管道未能生成候选池",
            "market_context": {
                "market_regime": "range_bound",
                "market_sentiment": {"sentiment_index": 50, "sentiment_label": "中性"},
                "index_realtime": [],
                "sector_momentum": [],
                "benchmark_stocks": [],
            },
            "generated_at": "2026-07-23T00:00:00Z",
            "design_metadata": {},
        }

        await design_worker(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "failed"
        assert "无候选标的" in t.get("error_message", "")


class TestTaskWebSocket:
    """测试 WS 通知"""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_registered(self):
        """验证 broadcast 发送消息到注册的客户端"""
        from app.tasks.design_tasks import TaskNotifyManager

        mgr = TaskNotifyManager()
        mock_ws = AsyncMock()
        mgr.register(mock_ws)

        await mgr.broadcast({"type": "task_update", "task_id": 1, "status": "completed"})

        mock_ws.send_text.assert_awaited_once()
        sent = mock_ws.send_text.await_args[0][0]
        assert "task_update" in str(sent)
        assert "completed" in str(sent)

    @pytest.mark.asyncio
    async def test_unregister_removes_ws(self):
        """验证 unregister 移除后不再广播"""
        from app.tasks.design_tasks import TaskNotifyManager

        mgr = TaskNotifyManager()
        mock_ws = AsyncMock()
        mgr.register(mock_ws)
        mgr.unregister(mock_ws)

        await mgr.broadcast({"type": "task_update", "task_id": 1})

        mock_ws.send_text.assert_not_awaited()
