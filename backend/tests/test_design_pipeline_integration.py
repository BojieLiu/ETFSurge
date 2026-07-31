"""
TDD integration tests for design_pipeline and strategy_check_pipeline.

Tests cover the full sequential pipeline with mocked data sources and LLM.
External network / DB / LLM are all mocked; only in-memory task state is real.

Test cases (per design-check-pipeline-redesign.md §4.1):
  1. test_pipeline_full_success      — LLM succeeds → report_quality="full"
  2. test_pipeline_llm_timeout       — LLM times out → report_quality="fallback"
  3. test_pipeline_empty_pool        — empty candidates → task failed
  4. test_pipeline_ws_notify         — WS receives progress + completed events
  5. test_strategy_check_pipeline    — strategy check pipeline basic flow
"""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, ANY


# ── Helpers ───────────────────────────────────────────────────────

def _mock_strategies(count=3):
    """Return a list of mock strategy dicts."""
    labels = ["defensive", "balanced", "aggressive"]
    return [
        {
            "id": labels[i],
            "label": {"defensive": "防御型", "balanced": "平衡型", "aggressive": "进攻型"}[labels[i]],
            "etfs": [
                {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.3,
                 "factor_score": 0.75, "daily_change_pct": 0.01,
                 "selection_rationale": "核心宽基，估值合理"},
            ],
        }
        for i in range(min(count, 3))
    ]


def _mock_market_context():
    return {
        "market_regime": "range_bound",
        "market_sentiment": {"sentiment_index": 55, "sentiment_label": "中性"},
        "index_realtime": [],
        "sector_momentum": [],
    }


def _make_mock_session(design_id: int = 1001):
    """Create a properly configured mock async DB session.

    Real SQLAlchemy async_session uses:
      - async with session() as db:
      - db.add(obj)               — sync, no await
      - await db.commit()         — async
      - await db.refresh(obj)     — async, sets obj.id
      - await db.get(Model, id)  — async, returns record
    """
    record = MagicMock()
    record.id = design_id
    record.report_quality = "pending"

    session = MagicMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = None
    session.add = MagicMock()  # sync method

    session.commit = AsyncMock(return_value=None)

    async def _refresh(obj):
        obj.id = design_id
    session.refresh = AsyncMock(side_effect=_refresh)

    session.get = AsyncMock(return_value=record)

    return session


# ── Design Pipeline Tests ─────────────────────────────────────────

class TestDesignPipeline:
    """Test design_pipeline() with mocked external dependencies.

    Patch targets match LOCAL imports inside design_pipeline():
      - generate_enhanced_design  → app.services.strategy_design (local import)
      - generate_design_report    → app.analysis.llm (local import)
      - async_session             → app.tasks.task_manager (module-level import)
      - notify_manager            → app.tasks.task_manager (module-level)
    """

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_full_success(self, mock_gen_design, mock_llm, mock_db_session):
        """Scenario: LLM succeeds → task completed, report_quality='full'."""
        from app.tasks.task_manager import TaskManager, design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
        }
        mock_llm.return_value = "## 市场分析\n当前市场处于震荡阶段，建议均衡配置。"

        mock_db_session.return_value = _make_mock_session(design_id=1001)

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "completed"
        assert t["progress"] == 100
        assert t["result"]["report_quality"] == "full"
        assert t["result"]["design_id"] == 1001
        assert "strategies" in t["result"]

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_llm_timeout(self, mock_gen_design, mock_llm, mock_db_session):
        """Scenario: LLM raises exception → report_quality='fallback', data summary still available."""
        from app.tasks.task_manager import TaskManager, design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
        }
        mock_llm.side_effect = asyncio.TimeoutError("LLM timeout")

        # Two consecutive sessions needed: Stage 3 write + Stage 4 fallback update
        mock_db_session.side_effect = [
            _make_mock_session(design_id=1002),  # Stage 3: initial write
            _make_mock_session(design_id=1002),  # Stage 4: fallback update
        ]

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(mgr, task_id=1)

        t = mgr.get_task(1)
        # S1-C: LLM 超时 → completed_with_errors（方案仍然可用）
        assert t["status"] == "completed_with_errors"
        assert t["progress"] == 100
        assert t["result"]["report_quality"] == "partial"
        assert t["result"]["design_id"] == 1002

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_empty_pool(self, mock_gen_design):
        """Scenario: empty candidate pool → task failed with error."""
        from app.tasks.task_manager import TaskManager, design_pipeline

        mock_gen_design.return_value = {
            "strategies": [],
            "market_context": _mock_market_context(),
            "error": "无候选标的",
            "detail": "数据管道未能生成候选池",
        }

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "failed"
        assert "无候选标的" in t.get("error_message", "")

    @patch("app.tasks.task_manager.notify_manager")
    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_ws_notify(self, mock_gen_design, mock_llm, mock_db_session,
                                      mock_notify_mgr):
        """Scenario: WS receives progress updates + final completed event."""
        from app.tasks.task_manager import TaskManager, design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
        }
        mock_llm.return_value = "LLM report content"

        mock_db_session.return_value = _make_mock_session(design_id=1003)

        mock_notify_mgr.broadcast = AsyncMock()

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(mgr, task_id=1)

        # Verify WS notifications were broadcast
        assert mock_notify_mgr.broadcast.called
        # Should have been called at least 5 times (progress stages + completed)
        assert mock_notify_mgr.broadcast.call_count >= 5

        # Verify final notification has completed status
        all_calls = [call[0][0] for call in mock_notify_mgr.broadcast.call_args_list]
        completed_payloads = [p for p in all_calls if p.get("status") == "completed"]
        assert len(completed_payloads) >= 1
        final = completed_payloads[-1]
        assert final["progress"] == 100
        assert final["design_id"] == 1003
        assert final.get("report_quality") == "full"

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_engine_error(self, mock_gen_design):
        """Scenario: generate_enhanced_design raises exception → task failed."""
        from app.tasks.task_manager import TaskManager, design_pipeline

        mock_gen_design.side_effect = ValueError("引擎计算异常")

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "failed"
        assert "引擎计算异常" in t.get("error_message", "")

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_market_context_available(self, mock_gen_design, mock_llm, mock_db_session):
        """Regression: market_context passed through, no NameError."""
        from app.tasks.task_manager import TaskManager, design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
        }
        mock_llm.return_value = "LLM report content"
        # Two sessions needed: Stage 3 write + Stage 4 LLM result update
        mock_db_session.side_effect = [
            _make_mock_session(design_id=1004),  # Stage 3: initial write
            _make_mock_session(design_id=1004),  # Stage 4: LLM result update
        ]

        mgr = TaskManager()
        mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "completed"
        assert "market_context" in t["result"]


# ── Strategy Check Pipeline Tests ─────────────────────────────────

class TestStrategyCheckPipeline:

    @patch("app.database.async_session")  # strategy_check_worker imports async_session from app.database
    @patch("app.services.portfolio_service.strategy_check", new_callable=AsyncMock)
    async def test_strategy_check_full(self, mock_strategy_check, mock_db_session):
        """Scenario: strategy_check succeeds → task completed with result."""
        from app.tasks.strategy_check_worker import strategy_check_pipeline
        from app.tasks.task_manager import TaskManager

        mock_strategy_check.return_value = {
            "summary": "组合健康，建议维持现有配置",
            "suggestions": [{"symbol": "510300", "action": "hold", "reason": "估值合理"}],
            "holdings_analysis": [{"symbol": "510300", "factor_summary": "动量偏多"}],
            "risk_warnings": [],
            "market_regime": "range_bound",
        }

        mock_db_session.return_value = _make_mock_session(design_id=2001)

        mgr = TaskManager()
        mgr.create_task(task_type="check", params={"capital": 500000})
        await strategy_check_pipeline(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "completed"
        assert t["progress"] == 100
        assert "market_regime" in t["result"]
        assert len(t["result"]["suggestions"]) == 1
        assert t.get("record_id") == 2001

    @patch("app.services.portfolio_service.strategy_check", new_callable=AsyncMock)
    async def test_strategy_check_empty_portfolio(self, mock_strategy_check):
        """Scenario: empty portfolio → completed with empty suggestions."""
        from app.tasks.strategy_check_worker import strategy_check_pipeline
        from app.tasks.task_manager import TaskManager

        mock_strategy_check.return_value = {
            "summary": "组合为空",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
            "market_regime": "range_bound",
        }

        mgr = TaskManager()
        mgr.create_task(task_type="check", params={"capital": 500000})
        await strategy_check_pipeline(mgr, task_id=1)

        t = mgr.get_task(1)
        assert t["status"] == "completed"
