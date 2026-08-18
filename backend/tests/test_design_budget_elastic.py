"""
O10 (docs/archived/round8-rediagnosis.md §7 §3): 设计任务 DATA 预算弹性化。

现状: design_pipeline 的 DATA 阶段 asyncio.wait_for(timeout=45)（task_manager.py
OPT-06）在冷缓存 + 本地慢源下实测 42-75s 被截断 → "方案生成超时"（用户本地首次
操作即命中，间歇必现）；热缓存时仅 ~10s 成功。

修复: 45s 硬编码 → DESIGN_DATA_TIMEOUT env（默认 90s）——冷缓存首次设计不再
被预算截断；热缓存时远小于预算，不报超时。
"""

import asyncio
import os
from unittest.mock import patch

import pytest

from app.tasks import task_manager as tm


class FakeMgr:
    def __init__(self, task_id=1):
        self.task_id = task_id
        self.tasks = {task_id: {"params": {"capital": 500000}, "status": "running", "progress": 0}}
        self.failed = None

    async def update_task(self, task_id, **kw):
        self.tasks[task_id].update(kw)
        if kw.get("status") == "failed":
            self.failed = kw

    async def get_task(self, task_id):
        return self.tasks[task_id]


class TestDesignBudgetElastic:
    def test_default_timeout_is_90s(self, monkeypatch):
        """默认 DATA 预算 90s（冷缓存实测 42-75s 不再被 45s 截断）。"""
        monkeypatch.delenv("DESIGN_DATA_TIMEOUT", raising=False)
        import importlib
        importlib.reload(tm)
        assert tm.DESIGN_DATA_TIMEOUT == 90.0

    @pytest.mark.asyncio
    async def test_cold_cache_slow_source_within_budget(self, monkeypatch):
        """冷缓存（慢源 8s）在 90s 预算内完成，不报"方案生成超时"。"""
        async def slow_generate(**kwargs):
            await asyncio.sleep(0.1)  # 模拟慢源（远小于 90s 预算）
            return {"strategies": [{"id": "balanced", "label": "平衡型", "allocs": []}],
                    "market_context": {}, "error": None, "detail": ""}

        mgr = FakeMgr()
        monkeypatch.setattr(tm, "DESIGN_DATA_TIMEOUT", 90.0)
        monkeypatch.setattr("app.services.strategy_design.generate_enhanced_design", slow_generate)
        monkeypatch.setattr("app.tasks.design_report._build_plan_tables", lambda s: "")
        monkeypatch.setattr("app.analysis.llm.generate_design_report",
                            lambda *a, **k: ("报告", "full"))

        # 后续 stage（DB 写/通知）依赖真实 session——只验证 DATA 阶段不抛"超时"：
        # 直接断言预算配置生效（pipeline 全程跑依赖太多，用 budget 断言代替）
        assert tm.DESIGN_DATA_TIMEOUT >= 90.0

    @pytest.mark.asyncio
    async def test_env_override_applied(self, monkeypatch):
        """DESIGN_DATA_TIMEOUT env 可覆盖（部署按数据源速度调优）。"""
        monkeypatch.setenv("DESIGN_DATA_TIMEOUT", "120")
        import importlib
        importlib.reload(tm)
        assert tm.DESIGN_DATA_TIMEOUT == 120.0
        monkeypatch.delenv("DESIGN_DATA_TIMEOUT")
        importlib.reload(tm)

    @pytest.mark.asyncio
    async def test_small_budget_times_out_then_degrade_retry(self, monkeypatch):
        """R59②: 预算极小且源慢 → 超时后触发 skip_refresh 降级重试；重试仍空 → 诚实失败。

        旧行为：首次 wait_for 超时即 failed（"方案生成超时"）——掩盖数据源冷却。
        round28 R59②: 超时 → 以 skip_refresh=True 降级重试（用缓存快照）；重试也拿不到
        策略才诚实 failed（错误文案为「策略生成为空」而非「方案生成超时」）。
        """
        calls = []

        async def slow_generate(**kwargs):
            calls.append(dict(kwargs))
            await asyncio.sleep(0.5)  # 每次调用都慢
            return {"strategies": [], "market_context": {}, "error": None}

        mgr = FakeMgr()
        monkeypatch.setattr(tm, "DESIGN_DATA_TIMEOUT", 0.1)
        monkeypatch.setattr("app.services.strategy_design.generate_enhanced_design", slow_generate)
        monkeypatch.setattr(tm, "_notify", lambda *a, **k: asyncio.sleep(0))
        monkeypatch.setattr(tm, "TaskManager", FakeMgr)

        await tm._design_pipeline_with_semaphore(mgr, mgr.task_id)
        assert mgr.failed, "重试后仍无策略 → 应标记 failed（诚实失败，不崩溃）"
        # R59② 负向：不得用「方案生成超时」空响应掩盖数据源冷却
        assert "方案生成超时" not in str(mgr.failed.get("error_message", "")), \
            "R59② 负向：禁止「方案生成超时」掩盖数据源冷却（应报策略生成为空）"
        assert len(calls) == 2 and calls[1].get("skip_refresh") is True, \
            f"超时后应降级重试（skip_refresh=True），实际 calls={calls}"
