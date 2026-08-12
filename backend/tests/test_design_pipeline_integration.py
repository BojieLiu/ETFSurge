"""
TDD integration tests for design_pipeline and strategy_check_pipeline.

Test cases (per design-check-pipeline-redesign.md §4.1):
  1. test_pipeline_full_success      — LLM succeeds → report_quality="full"
  2. test_pipeline_llm_timeout       — LLM times out → report_quality="fallback"
  3. test_pipeline_empty_pool        — empty candidates → task failed
  4. test_pipeline_ws_notify         — WS receives progress + completed events
  5. test_strategy_check_pipeline    — strategy check pipeline basic flow

Z27 适配（结构重写，见 docs/z27-task-persistence-redesign.md §8.2）：
  - TaskManager 用真实测试库（tests/db_fixtures.task_mgr，D10），不再 mock async_session 当任务库
  - 保留对 app.tasks.task_manager.async_session 的 patch（D11，管 pipeline 写 portfolio_designs）
  - task_id 从 create_task() 返回值取（不再硬编码 1）
  - 断言目标从「task 内存 dict」改为「DB 读回」
"""
import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, ANY

from tests.db_fixtures import task_db, task_mgr  # noqa: F401


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
      - async_session             → app.tasks.task_manager (module-level import, D11)
      - notify_manager            → app.tasks.task_manager (module-level)
    """

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_full_success(self, mock_gen_design, mock_llm, mock_db_session, task_mgr):
        """Scenario: LLM succeeds → task completed, report_quality='full'."""
        from app.tasks.task_manager import design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
        }
        mock_llm.return_value = "## 市场分析\n当前市场处于震荡阶段，建议均衡配置。"

        mock_db_session.return_value = _make_mock_session(design_id=1001)

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "completed"
        assert got["progress"] == 100
        assert got["result"]["report_quality"] == "full"
        assert got["result"]["design_id"] == 1001
        assert got["record_id"] == 1001  # Z27: 完成时回写 record_id
        assert "strategies" in got["result"]

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_llm_timeout(self, mock_gen_design, mock_llm, mock_db_session, task_mgr):
        """Scenario: LLM raises exception → report_quality='fallback', data summary still available."""
        from app.tasks.task_manager import design_pipeline

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

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        # S1-C: LLM 超时 → completed_with_errors（方案仍然可用）
        assert got["status"] == "completed_with_errors"
        assert got["progress"] == 100
        assert got["result"]["report_quality"] == "partial"
        assert got["result"]["design_id"] == 1002
        assert got["record_id"] == 1002  # Z27

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_empty_pool(self, mock_gen_design, task_mgr):
        """Scenario: empty candidate pool → task failed with error."""
        from app.tasks.task_manager import design_pipeline

        mock_gen_design.return_value = {
            "strategies": [],
            "market_context": _mock_market_context(),
            "error": "无候选标的",
            "detail": "数据管道未能生成候选池",
        }

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "failed"
        assert "无候选标的" in got.get("error_message", "")

    @patch("app.tasks.task_manager.notify_manager")
    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_ws_notify(self, mock_gen_design, mock_llm, mock_db_session,
                                      mock_notify_mgr, task_mgr):
        """Scenario: WS receives progress updates + final completed event."""
        from app.tasks.task_manager import design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
        }
        mock_llm.return_value = "LLM report content"

        mock_db_session.return_value = _make_mock_session(design_id=1003)

        mock_notify_mgr.broadcast = AsyncMock()

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

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
        # Z27: 完成通知携带 record_id + task_type
        assert final["record_id"] == 1003
        assert final["task_type"] == "design"

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_llm_placeholder_not_full(self, mock_gen_design, mock_llm, mock_db_session, task_mgr):
        """P0-1 反假完成：LLM 返回"报告生成失败"占位符 → quality=partial 绝非 full.

        负向断言：全兜底/占位符时不得标 full（即使 len>0）。
        """
        from app.tasks.task_manager import design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
        }
        # LLM 空响应被 llm.py:1646 兜底为 "报告生成失败"（6 字符，len>0）
        mock_llm.return_value = "报告生成失败"
        mock_db_session.side_effect = [
            _make_mock_session(design_id=1005),  # Stage 3: initial write
            _make_mock_session(design_id=1005),  # Stage 4: partial update
        ]

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "completed"
        assert got["result"]["report_quality"] == "partial"
        # 占位符不得进入最终报告文本（跳过 LLM 段落）
        assert "报告生成失败" not in got["result"].get("design_text", "")

    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_engine_error(self, mock_gen_design, task_mgr):
        """Scenario: generate_enhanced_design raises exception → task failed."""
        from app.tasks.task_manager import design_pipeline

        mock_gen_design.side_effect = ValueError("引擎计算异常")

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "failed"
        assert "引擎计算异常" in got.get("error_message", "")

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_market_context_available(self, mock_gen_design, mock_llm, mock_db_session, task_mgr):
        """Regression: market_context passed through, no NameError."""
        from app.tasks.task_manager import design_pipeline

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

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "completed"
        assert "market_context" in got["result"]

    @patch("app.tasks.task_manager.async_session")
    @patch("app.analysis.llm.generate_design_report", new_callable=AsyncMock)
    @patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
    async def test_pipeline_persists_degradation(self, mock_gen_design, mock_llm, mock_db_session, task_mgr):
        """P2-8 (round17): generate_enhanced_design 顶层 degradation 并入 market_context，
        随 market_snapshot_json 持久化（历史设计可查，而非仅新设计内存可见）。"""
        from app.tasks.task_manager import design_pipeline

        mock_gen_design.return_value = {
            "strategies": _mock_strategies(),
            "market_context": _mock_market_context(),
            "degradation": {
                "mode": "partial_data",
                "pool_degraded": True,
                "reason": "部分候选标的缺因子分",
            },
        }
        mock_llm.return_value = "LLM report content"
        stage3_session = _make_mock_session(design_id=1005)
        mock_db_session.side_effect = [
            stage3_session,  # Stage 3: initial write
            _make_mock_session(design_id=1005),  # Stage 4: LLM result update
        ]

        t = await task_mgr.create_task(task_type="design", params={"capital": 500000})
        await design_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "completed"

        # Stage 3 写入的 PortfolioDesign.market_snapshot_json 必须含 degradation
        record = stage3_session.add.call_args[0][0]
        snapshot = json.loads(record.market_snapshot_json)
        assert snapshot.get("degradation", {}).get("mode") == "partial_data"
        assert snapshot["degradation"].get("pool_degraded") is True


# ── Strategy Check Pipeline Tests ─────────────────────────────────

class TestStrategyCheckPipeline:

    @patch("app.database.async_session")  # strategy_check_worker imports async_session from app.database
    @patch("app.services.portfolio_service.strategy_check", new_callable=AsyncMock)
    async def test_strategy_check_full(self, mock_strategy_check, mock_db_session, task_mgr):
        """Scenario: strategy_check succeeds → task completed with result + record_id."""
        from app.tasks.strategy_check_worker import strategy_check_pipeline

        mock_strategy_check.return_value = {
            "summary": "组合健康，建议维持现有配置",
            "suggestions": [{"symbol": "510300", "action": "hold", "reason": "估值合理"}],
            "holdings_analysis": [{"symbol": "510300", "factor_summary": "动量偏多"}],
            "risk_warnings": [],
            "market_regime": "range_bound",
            # U2 R2: report_text 非空 → 任务 completed（空则标记 failed）
            "report_text": "## 策略检查报告\n\n**市态**：震荡\n\n**因子数据质量**：1/1 只持仓因子数据可用（无兜底）。\n\n### 逐标的因子/信号/建议\n\n| 代码 | 名称 | 因子分 | 信号 | 建议 | 理由 |\n\n|------|------|--------|------|------|------|\n\n| 510300 | 沪深300ETF | 0.50 | hold | hold | 估值合理 |\n\n### 风险提示\n\n- [info] 当前组合风险指标正常，未触发自动警告。\n\n### 操作建议\n\n- 510300 沪深300ETF：hold 40.0% → 40.0%｜估值合理\n",
        }

        mock_db_session.return_value = _make_mock_session(design_id=2001)

        t = await task_mgr.create_task(task_type="check", params={"capital": 500000})
        await strategy_check_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "completed"
        assert got["progress"] == 100
        assert "market_regime" in got["result"]
        assert len(got["result"]["suggestions"]) == 1
        assert got.get("record_id") == 2001

    @patch("app.services.portfolio_service.strategy_check", new_callable=AsyncMock)
    async def test_strategy_check_empty_portfolio(self, mock_strategy_check, task_mgr):
        """Scenario: empty portfolio → completed with empty suggestions."""
        from app.tasks.strategy_check_worker import strategy_check_pipeline

        mock_strategy_check.return_value = {
            "summary": "组合为空",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
            "market_regime": "range_bound",
            "report_text": "## 策略检查报告\n\n**市态**：震荡\n\n### 操作建议\n\n- 无可操作标的（组合为空）。\n",
        }

        t = await task_mgr.create_task(task_type="check", params={"capital": 500000})
        await strategy_check_pipeline(task_mgr, task_id=t["task_id"])

        got = await task_mgr.get_task(t["task_id"])
        assert got["status"] == "completed"
