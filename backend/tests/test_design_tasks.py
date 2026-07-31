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


class TestDesignWorker:
    """测试 design_worker 异步任务"""

    def _make_mock_session(self):
        """Minimal mock DB session for pipeline tests."""
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
    async def test_worker_runs_full_pipeline(self, mock_gen, mock_llm, mock_db, task_mgr):
        """验证 worker 调用 generate_full_design"""
        from app.tasks.design_tasks import design_worker

        mgr = task_mgr
        t = await mgr.create_task(task_type="design", params={"capital": 500000})

        mock_llm.return_value = "LLM report"
        mock_db.return_value = self._make_mock_session()
        mock_gen.return_value = {
            "strategies": [{"label": "防御型", "etfs": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.5}]}],
            "market_context": {},
        }

        await design_worker(mgr, task_id=t["task_id"])

        mock_gen.assert_awaited_once()
        task = await mgr.get_task(t["task_id"])
        assert task["status"] == "completed"
        assert task["progress"] == 100
        # Z27: 完成时回写 record_id
        assert task["record_id"] == 999

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_worker_failure_sets_failed_status(self, mock_gen, task_mgr):
        """验证 worker 出错时标记为 failed"""
        from app.tasks.design_tasks import design_worker

        mgr = task_mgr
        t = await mgr.create_task(task_type="design")

        mock_gen.side_effect = Exception("API timeout")

        await design_worker(mgr, task_id=t["task_id"])

        task = await mgr.get_task(t["task_id"])
        assert task["status"] == "failed"
        assert "API timeout" in task["error_message"]

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_worker_saves_design_id(self, mock_gen, mock_llm, mock_db, task_mgr):
        """验证 worker 完成后关联 design_id + record_id"""
        from app.tasks.design_tasks import design_worker

        mgr = task_mgr
        t = await mgr.create_task(task_type="design")

        mock_llm.return_value = "LLM report"
        mock_db.return_value = self._make_mock_session()
        mock_gen.return_value = {
            "strategies": [{"label": "防御型", "etfs": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.5}]}],
            "market_context": {},
        }

        await design_worker(mgr, task_id=t["task_id"])

        task = await mgr.get_task(t["task_id"])
        assert task["status"] == "completed"
        assert task["progress"] == 100
        assert task["record_id"] == 999

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_worker_handles_error_dict(self, mock_gen, task_mgr):
        """验证 generate_enhanced_design 返回带 error 的 dict 时，
        design_worker 正确标记为 failed 并保存错误信息。

        这是 coverage 盲区：现有测试只测了抛异常路径，没测返回 error dict 路径。"""
        from app.tasks.design_tasks import design_worker

        mgr = task_mgr
        t = await mgr.create_task(task_type="design", params={"capital": 500000})

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

        await design_worker(mgr, task_id=t["task_id"])

        task = await mgr.get_task(t["task_id"])
        assert task["status"] == "failed"
        assert "无候选标的" in task.get("error_message", "")


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
