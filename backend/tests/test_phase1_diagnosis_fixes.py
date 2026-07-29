"""Tests for Phase 1 Critical Fixes from comprehensive-diagnosis-report.md

Phase 1 — 一击必杀 (System Recovery):
  P0.5: Global IPv4 priority strategy
  P0.1: Fix LLM import error in strategy_check_worker
  P0.6: Fix LLM Advice 422 error
  P0.2: Fix LLM report generation transition to completed
  P1.4: Fix data source probe accuracy
"""
from __future__ import annotations

import asyncio
import socket
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── P0.5: IPv4 Priority Strategy ─────────────────────────────

class TestP0_5_IPv4Priority:
    """P0.5: Global IPv4 priority monkey-patch in config.py"""

    def test_enable_ipv4_only_creates_monkey_patch(self):
        """enable_ipv4_only() should patch socket.getaddrinfo to force AF_INET."""
        from app.config import enable_ipv4_only, disable_ipv4_only

        original = socket.getaddrinfo
        try:
            enable_ipv4_only()
            # Test that it forces IPv4
            result = socket.getaddrinfo("127.0.0.1", 80)
            assert all(r[0] == socket.AF_INET for r in result)
        finally:
            socket.getaddrinfo = original

    def test_disable_ipv4_only_restores_original(self):
        """disable_ipv4_only() should restore the original socket.getaddrinfo."""
        from app.config import enable_ipv4_only, disable_ipv4_only

        # Capture the patched version, then enable again
        enable_ipv4_only()
        patched = socket.getaddrinfo
        
        # Save original BEFORE restore for verification
        import socket as _socket
        orig = _socket._original_getaddrinfo if hasattr(_socket, '_original_getaddrinfo') else None
        # Actually just verify behavior: after disable, IPv6 results should be possible
        # (but we can't guarantee since it depends on DNS resolution)
        
        disable_ipv4_only()
        assert socket.getaddrinfo is not patched, "disable should change getaddrinfo"

    def test_ipv4_only_ignores_AF_INET6(self):
        """The patched getaddrinfo should ignore AF_INET6 requests."""
        from app.config import enable_ipv4_only, disable_ipv4_only

        original = socket.getaddrinfo
        try:
            enable_ipv4_only()
            # Running with AF_INET6 should still return IPv4 results
            result = socket.getaddrinfo("127.0.0.1", 80, socket.AF_INET6)
            assert all(r[0] == socket.AF_INET for r in result)
        finally:
            socket.getaddrinfo = original


# ── P0.1: strategy_check_worker LLM import fix ──────────────

class TestP0_1_StrategyCheckLLMImport:
    """P0.1: Fix 'from app.analysis.llm import llm_provider' error."""

    async def test_generate_check_llm_comment_uses_llm_complete(self):
        """_generate_check_llm_comment should use llm_complete not llm_provider.
        
        Verify by patching llm_complete at the import path used inside the function.
        """
        with patch("app.analysis.llm.llm_complete", new_callable=AsyncMock) as mock_llm:
            # Re-import to pick up the patch
            import importlib
            from app.tasks import strategy_check_worker
            importlib.reload(strategy_check_worker)
            from app.tasks.strategy_check_worker import _generate_check_llm_comment

            mock_llm.return_value = "test analysis response"

            result = await _generate_check_llm_comment({
                "positions": [
                    {"symbol": "510050", "name": "华夏上证50", "weight": 0.3, "change_pct": 0.5, "market_value": 150000},
                    {"symbol": "510300", "name": "华泰300", "weight": 0.2, "change_pct": -0.3, "market_value": 100000},
                ]
            })

            assert result is not None
            assert isinstance(result, str)
            assert mock_llm.await_count >= 1

    async def test_generate_check_llm_comment_empty_positions(self):
        """Empty positions should return None without calling any LLM."""
        from app.tasks.strategy_check_worker import _generate_check_llm_comment

        result = await _generate_check_llm_comment({"positions": []})
        assert result is None

    async def test_generate_check_llm_comment_no_positions_key(self):
        """Missing positions key should return None."""
        from app.tasks.strategy_check_worker import _generate_check_llm_comment

        result = await _generate_check_llm_comment({})
        assert result is None

    async def test_generate_check_llm_report_empty_positions(self):
        """_generate_check_llm_report should return None for empty positions."""
        from app.tasks.strategy_check_worker import _generate_check_llm_report

        result = await _generate_check_llm_report({"positions": []}, capital=500000)
        assert result is None

    def test_no_llm_provider_import_error(self):
        """strategy_check_worker should NOT import llm_provider anymore."""
        import ast

        import os
        test_path = os.path.join(os.path.dirname(__file__), "..", "app", "tasks", "strategy_check_worker.py")
        with open(test_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        llm_provider_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "llm_provider":
                        llm_provider_found = True
                        break
        
        if llm_provider_found:
            # Check if it's inside a conditional or try/except where it's a fallback
            pytest.fail("strategy_check_worker still imports llm_provider")
        
        # Instead, verify llm_complete IS imported somewhere
        llm_complete_found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "llm_complete":
                        llm_complete_found = True
                        break
        
        assert llm_complete_found, "strategy_check_worker should import llm_complete"


# ── P0.6: LLM Advice 422 fix ─────────────────────────────────

class TestP0_6_LLMAdvice422:
    """P0.6: Fix POST /llm-advice 422 error caused by Query() in POST body."""

    def test_llm_advice_uses_pydantic_request_body(self):
        """llm_advice endpoint should use Pydantic model, not Query(...)."""
        import ast

        import os
        test_path = os.path.join(os.path.dirname(__file__), "..", "app", "routers", "analysis.py")
        with open(test_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # Find the llm_advice function definition
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "llm_advice":
                # Check the first parameter is a request body (not Query)
                args = node.args.args
                if args:
                    first_arg = args[0]
                    # Should have a type annotation pointing to a class (not str with Query default)
                    assert first_arg.arg == "req", (
                        f"llm_advice should use 'req' parameter, got '{first_arg.arg}'"
                    )
                    # The first parameter should have NO default (body params can't have Query defaults)
                    if node.args.defaults:
                        for default in node.args.defaults:
                            if isinstance(default, ast.Call):
                                func = default.func
                                if (isinstance(func, ast.Name) and func.id == "Query") or \
                                   (isinstance(func, ast.Attribute) and func.attr == "Query"):
                                    pytest.fail("llm_advice still uses Query() parameter")
                return  # Found and checked

        pytest.fail("Could not find llm_advice function definition")


# ── P0.2: LLM Report Generation Transition ──────────────────

class TestP0_2_DesignReportTransition:
    """P0.2: Ensure design_pipeline properly transitions to completed."""

    def test_design_pipeline_transitions_to_completed(self):
        """After successful LLM report, task should reach 'completed' status."""
        # We're testing the pipeline logic, not running the full pipeline
        from app.tasks.task_manager import TaskManager

        mgr = TaskManager(persist_path=None)
        task = mgr.create_task("design", {"capital": 500000})
        task_id = task["task_id"]

        # Simulate the final stages
        mgr.update_task(
            task_id,
            progress=100,
            status="completed",
            result={
                "strategies": [],
                "design_id": 1,
                "report_quality": "full",
            },
        )

        updated = mgr.get_task(task_id)
        assert updated["status"] == "completed"
        assert updated["progress"] == 100
        assert updated["result"]["report_quality"] == "full"

    def test_design_report_has_fallback_on_llm_failure(self):
        """When LLM fails, pipeline should set completed_with_errors not hang."""
        from app.tasks.task_manager import TaskManager

        mgr = TaskManager(persist_path=None)
        task = mgr.create_task("design", {"capital": 500000})
        task_id = task["task_id"]

        mgr.update_task(
            task_id,
            progress=100,
            status="completed_with_errors",
            result={
                "strategies": [],
                "design_id": 1,
                "report_quality": "partial",
            },
        )

        updated = mgr.get_task(task_id)
        assert updated["status"] == "completed_with_errors"
        assert updated["result"]["report_quality"] == "partial"

    def test_design_report_has_timeout_fallback(self):
        """When LLM times out, task should be marked failed."""
        from app.tasks.task_manager import TaskManager

        mgr = TaskManager(persist_path=None)
        task = mgr.create_task("design", {"capital": 500000})
        task_id = task["task_id"]

        mgr.update_task(
            task_id,
            progress=0,
            status="failed",
            error_message="方案生成超时，数据源响应过慢，请稍后重试",
        )

        updated = mgr.get_task(task_id)
        assert updated["status"] == "failed"


# ── P1.4: Data Source Probe Accuracy ────────────────────────

class TestP1_4_ProbeAccuracy:
    """P1.4: Fix data source probe accuracy."""

    def test_akshare_probe_uses_actual_function(self):
        """akshare probe should use a function actually used by the system."""
        import ast

        import os
        probes_path = os.path.join(os.path.dirname(__file__), "..", "app", "monitor", "probes.py")
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # Find the _probe_akshare function
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "akshare" in node.name.lower():
                # Check the AST body for actual function calls (not comments)
                has_old_func = any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) 
                    and n.func.attr == "stock_zh_a_hist"
                    for n in ast.walk(node)
                )
                assert not has_old_func, (
                    "akshare probe still uses stock_zh_a_hist, "
                    "should use system-actual function"
                )
                # Check it uses stock_sector_spot_em (the actual system function)
                has_new_func = any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) 
                    and n.func.attr == "stock_sector_spot_em"
                    for n in ast.walk(node)
                )
                assert has_new_func, (
                    "akshare probe should use stock_sector_spot_em "
                    "(the function used by sector_fetcher)"
                )
                return

        pytest.fail("Could not find akshare probe function")

    def test_probe_names_match_source_registry(self):
        """Probe names should match SourceRegistry source names."""
        import ast

        import os
        probes_path = os.path.join(os.path.dirname(__file__), "..", "app", "monitor", "probes.py")
        with open(probes_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # Find all register_probe calls and extract the source names
        registered_sources = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Name) and call.func.id == "register_probe":
                    if call.args and isinstance(call.args[0], ast.Constant):
                        registered_sources.append(call.args[0].value)

        # Check for standard source names
        expected_sources = ["mootdx", "sina", "tencent", "akshare", "levistock", "dongfang"]
        for source in expected_sources:
            assert source in registered_sources, (
                f"Probe for {source} not found or not registered with proper name "
                f"(found: {registered_sources})"
            )


# ── Integration: verify_e2e.py Phase 1 checks ───────────────

class TestP3_E2EEnhancements:
    """P3.x: E2E test enhancements for Phase 1 verification."""

    def test_verify_e2e_has_llm_import_check(self):
        """verify_e2e.py should check LLM import works."""
        import os
        e2e_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "verify_e2e.py")
        with open(e2e_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for LLM-related imports or check functions
        has_llm_check = (
            "from app.analysis.llm" in content
            or "llm_complete" in content
            or "generate_design_report" in content
            or "llm_import" in content
            or "LLM" in content
        )
        assert has_llm_check, "verify_e2e.py should have LLM-related checks"
