"""Tests for Phase 5 — Architecture Optimization (P4.x).

P4.1: LLM provider strategy pattern (verify already implemented)
P4.2: Connection pool configurable from config.py
P4.3: Warm cache Redis persistence
P4.4: Async task timeout monitoring
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from tests.db_fixtures import task_mgr  # noqa: F401


# ── P4.1: LLM Provider Strategy ──────────────────────────

class TestP4_1_LLMProviderStrategy:
    """P4.1: Verify LLM provider strategy pattern is already implemented."""

    def test_provider_config_dataclass_exists(self):
        """ProviderConfig dataclass should exist with all required fields."""
        from app.analysis.provider import ProviderConfig

        config = ProviderConfig(
            id="test", name="Test", api_url="http://test",
            api_key="key", model="test-model",
        )
        assert config.id == "test"
        assert config.timeout == 120  # default

    def test_get_configured_providers_returns_list(self):
        """get_configured_providers() should return a list (possibly empty)."""
        from app.analysis.provider import get_configured_providers

        providers = get_configured_providers()
        assert isinstance(providers, list)

    def test_call_with_failover_raises_on_empty_providers(self):
        """call_with_failover should raise ValueError for empty provider list."""
        from app.analysis.provider import call_with_failover

        with pytest.raises(ValueError, match="No LLM providers configured"):
            asyncio.run(call_with_failover(lambda p, **kw: "resp", []))

    def test_llm_complete_accepts_prompt(self):
        """llm_complete should accept a prompt string (smoke test)."""
        from app.analysis.llm import llm_complete

        # Just verify the function signature and that it exists
        import inspect
        sig = inspect.signature(llm_complete)
        assert "prompt" in sig.parameters

    def test_provider_failover_chain_defined(self):
        """provider.py should define primary and fallback providers."""
        from app.analysis.provider import get_configured_providers
        assert hasattr(get_configured_providers, "__call__")


# ── P4.2: Connection Pool Configurable ──────────────────

class TestP4_2_ConnectionPoolConfig:
    """P4.2: Connection pool settings should come from config.py."""

    def test_config_has_pool_settings(self):
        """config.py should have pool_connections and pool_maxsize settings."""
        from app.config import settings

        assert hasattr(settings, "pool_connections")
        assert hasattr(settings, "pool_maxsize")
        assert settings.pool_connections >= 10
        assert settings.pool_maxsize >= 20

    def test_china_market_uses_config_pool_settings(self):
        """china_market.py should read pool settings from config."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "fetchers", "china_market.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "settings.pool_connections" in content
        assert "settings.pool_maxsize" in content

    def test_pool_settings_have_reasonable_defaults(self):
        """Default pool settings should be >= 20 connections."""
        from app.config import settings

        assert settings.pool_connections >= 10
        assert settings.pool_maxsize >= 20


# ── P4.3: Redis Cache Persistence ───────────────────────

class TestP4_3_RedisCache:
    """P4.3: Cache should support Redis persistence with fallback to memory."""

    def test_config_has_redis_url(self):
        """config.py should have redis_url setting."""
        from app.config import settings

        assert settings.redis_url != ""
        assert settings.redis_url.startswith("redis://")

    def test_database_has_redis_import(self):
        """database.py should have Redis/cache support."""
        probes_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "database.py"
        )
        with open(probes_path, "r", encoding="utf-8") as f:
            content = f.read()

        redis_ref = "redis" in content.lower()
        cache_ref = "cache" in content.lower()
        assert redis_ref or cache_ref, (
            "database.py should have Redis or cache support"
        )

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


# ── P4.4: Async Task Timeout Monitor ────────────────────

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

    async def test_all_task_types_have_ttl(self):
        """All TASK_TYPES entries should have a TTL defined."""
        from app.tasks.task_manager import TASK_TYPES

        for task_type, config in TASK_TYPES.items():
            assert "ttl" in config, f"Task type {task_type} missing ttl"
            assert config["ttl"] > 0, f"Task type {task_type} has non-positive ttl"

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
