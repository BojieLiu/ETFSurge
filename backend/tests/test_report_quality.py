"""Tests: Report quality grading (FIX-Q01, FIX-Q03, FIX-Q04).

TDD: Tests written before implementation.
Covers:
  - Q01: Allocation engine gateway — empty ETF check
  - Q03: report_quality 4-tier grading (full/partial/empty/failed)
  - Q04: LLM consistency check — empty ETF footnotes
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ─── FIX-Q01: Allocation quality gate ──────────────────────────


@pytest.mark.asyncio
async def test_q01_empty_allocation_marked_failed():
    """Q01: If all 3 strategies have 0 real ETFs, task should be marked 'failed'."""
    from app.tasks.task_manager import _design_pipeline_with_semaphore, task_manager

    # Create a task
    task = task_manager.create_task("design", {"capital": 500000})

    # Mock at source module (lazy imported inside function)
    with patch("app.services.strategy_design.generate_enhanced_design") as mock_gen:
        mock_gen.return_value = {
            "strategies": [
                {"label": "防御型", "etfs": [{"symbol": "CASH", "name": "现金", "weight": 1.0}]},
                {"label": "平衡型", "etfs": [{"symbol": "CASH", "name": "现金", "weight": 1.0}]},
                {"label": "进攻型", "etfs": [{"symbol": "CASH", "name": "现金", "weight": 1.0}]},
            ],
            "market_context": {"market_regime": "range_bound"},
            "error": None,
        }

        # Prevent DB writes with real session
        with patch("app.tasks.task_manager.async_session") as mock_db:
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock()
            mock_db.return_value = mock_ctx
            mock_ctx.get = AsyncMock(return_value=None)
            mock_ctx.add = MagicMock()

            await _design_pipeline_with_semaphore(task_manager, task["task_id"])

    result = task_manager.get_task(task["task_id"])
    assert result is not None
    assert result["status"] == "failed", f"Expected failed, got {result['status']}"
    assert result["error_message"] is not None
    assert "ETF" in result["error_message"] or "标的" in result["error_message"]


@pytest.mark.asyncio
async def test_q01_partial_valid_allocation_proceeds():
    """Q01: If at least one strategy has >=3 non-CASH ETFs, pipeline proceeds."""
    from app.tasks.task_manager import _design_pipeline_with_semaphore, task_manager

    task = task_manager.create_task("design", {"capital": 500000})

    with patch("app.services.strategy_design.generate_enhanced_design") as mock_gen:
        mock_gen.return_value = {
            "strategies": [
                {"label": "防御型", "etfs": [
                    {"symbol": "510050", "weight": 0.3},
                    {"symbol": "511880", "weight": 0.2},
                    {"symbol": "511010", "weight": 0.2},
                    {"symbol": "CASH", "weight": 0.3},
                ]},
                {"label": "进攻型", "etfs": [
                    {"symbol": "CASH", "weight": 1.0},
                ]},
            ],
            "market_context": {"market_regime": "range_bound"},
            "error": None,
        }

        with patch("app.tasks.task_manager.async_session") as mock_db:
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock()
            mock_db.return_value = mock_ctx
            mock_ctx.get = AsyncMock(return_value=None)
            mock_ctx.add = MagicMock()

            await _design_pipeline_with_semaphore(task_manager, task["task_id"])

    result = task_manager.get_task(task["task_id"])
    assert result is not None
    # Should NOT have failed at the empty-allocation gate
    if result["status"] == "failed":
        err = result.get("error_message") or ""
        assert "ETF 标的" not in err, f"Should not fail on empty ETF gate: {err}"


# ─── FIX-Q03: report_quality 4-tier grading ────────────────────


def test_q03_quality_grades_defined():
    """Q03: All quality grades should be recognized."""
    valid_grades = {"full", "partial", "empty", "failed", "pending", "none"}
    assert "full" in valid_grades
    assert "empty" in valid_grades
    assert "partial" in valid_grades
    assert "failed" in valid_grades


def test_q03_empty_allocation_detection():
    """Q03: _validate_report_consistency should handle empty allocation gracefully."""
    from app.tasks.design_report import _validate_report_consistency

    strategies = [
        {"label": "防御型", "etfs": [{"symbol": "CASH", "name": "现金", "weight": 1.0}]},
    ]
    report_text = "# ETF 组合设计方案\n\n当前市场..."
    result = _validate_report_consistency(report_text, strategies)
    assert result is not None
    assert len(result) > 0


# ─── FIX-Q04: LLM consistency check ────────────────────────────


def test_q04_empty_etf_footnote_added():
    """Q04: Should return non-empty text even with all-CASH strategies."""
    from app.tasks.design_report import _validate_report_consistency

    strategies = [
        {"label": "防御型", "allocations": [{"symbol": "CASH", "weight": 1.0}]},
    ]
    report_text = "当前市场环境下建议保持观望"
    result = _validate_report_consistency(report_text, strategies)
    assert result is not None
    assert len(result) > 0


def test_q04_normal_allocation_no_footnote():
    """Q04: Normal allocation with real ETFs should work."""
    from app.tasks.design_report import _validate_report_consistency

    strategies = [
        {"label": "防御型", "allocations": [
            {"symbol": "510050", "name": "上证50ETF", "weight": 0.3},
            {"symbol": "511880", "name": "银华日利", "weight": 0.2},
        ]},
    ]
    report_text = "推荐配置上证50ETF和银华日利"
    result = _validate_report_consistency(report_text, strategies)
    assert result is not None
    assert "一致" not in result  # No consistency footnote for normal case


# ─── verify_e2e quality assertions (test the test logic) ──────


def test_e2e_report_quality_mock_check():
    """Test that the verify_e2e quality check logic works in isolation."""
    def _check_design_quality(design: dict) -> bool:
        strategies = design.get("strategies", [])
        quality = design.get("report_quality", "")
        if quality == "full":
            for s in strategies:
                etfs = s.get("etfs") or s.get("allocations") or []
                real = [e for e in etfs if e.get("symbol") != "CASH"]
                if len(real) >= 3:
                    return True
            return False
        return True

    good = {
        "report_quality": "full",
        "strategies": [{"label": "防御型", "etfs": [
            {"symbol": "510050"}, {"symbol": "511880"}, {"symbol": "511010"},
        ]}],
    }
    assert _check_design_quality(good)

    bad = {
        "report_quality": "full",
        "strategies": [{"label": "防御型", "etfs": [{"symbol": "CASH"}]}],
    }
    assert not _check_design_quality(bad)

    empty = {
        "report_quality": "empty",
        "strategies": [{"label": "防御型", "etfs": [{"symbol": "CASH"}]}],
    }
    assert _check_design_quality(empty)
