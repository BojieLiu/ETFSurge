"""
O2 (docs/archived/round7-rediagnosis.md §7 P2): 预热任务串行化——控并发峰值。

P2 根因: 启动预热高峰 shared_executor 64/64 饱和——market_cache（因子 K 线
8 并发 run_sync）+ etf_cache（全量扫描）+ global_indices + instruments_sync
（akshare 分页拉取）同时 create_task 启动，run_sync 任务叠加打满线程池，
阻塞预热与其他端点。方向：控并发而非扩容（与 round6 R6-F10 相反）。

修复: 预热编排改为串行执行（前一个完成再启动下一个），内部并发上限不变。
"""

import asyncio

import pytest

from app.main import _run_warmup_sequence


class TestWarmupSequence:
    @pytest.mark.asyncio
    async def test_tasks_run_serially(self):
        """任务串行——后一个任务在前一个完成后才开始。"""
        order = []

        async def task_a():
            order.append("a_start")
            await asyncio.sleep(0.01)
            order.append("a_end")

        async def task_b():
            order.append("b_start")

        async def task_c():
            order.append("c_start")

        await _run_warmup_sequence([task_a(), task_b(), task_c()])
        # b/c 在 a 完成后才启动
        assert order.index("b_start") > order.index("a_end"), f"b 应在 a 完成后启动: {order}"
        assert order.index("c_start") > order.index("a_end"), f"c 应在 a 完成后启动: {order}"

    @pytest.mark.asyncio
    async def test_exception_does_not_break_chain(self):
        """前序任务异常 → 后续任务仍执行（预热失败不阻断）。"""
        order = []

        async def task_a():
            raise RuntimeError("warmup fail")

        async def task_b():
            order.append("b_done")

        await _run_warmup_sequence([task_a(), task_b()])
        assert order == ["b_done"], "异常后后续任务仍应执行"

    @pytest.mark.asyncio
    async def test_empty_tasks_ok(self):
        await _run_warmup_sequence([])


# ===================================================================
# merged from test_round28_fixes.py::TestR56WarmupGlobalIndicesCardinality (S3.3 de-round, 2026-08-18)
# ===================================================================
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_mod
from app.services import market_service as ms
from app.services.market_data_hub import _rule_news_summary
from app.services.market_service import infer_market_from_symbol


class TestR56WarmupGlobalIndicesCardinality:
    def test_standalone_create_task_removed(self):
        """负向：禁止独立 `create_task(_warmup_global_indices())` 残留（F3 重构遗漏）。

        round28 §1: main.py:268 独立 task + sequence :334 重复调用 → 双重预热 18.4s。
        源码级守卫：独立 create_task 形式不得出现（该调用只允许出现在 sequence 内）。
        """
        src = open(main_mod.__file__, encoding="utf-8").read()
        assert "create_task(_warmup_global_indices())" not in src, \
            "独立 create_task(_warmup_global_indices()) 应已删除（R56）"

    def test_sequence_contains_global_indices_once(self):
        """sequence 内 `_warmup_global_indices(),` 恰好出现一次（基数断言）。"""
        src = open(main_mod.__file__, encoding="utf-8").read()
        # 定义行是 `async def _warmup_global_indices():`（无逗号），
        # sequence 内调用是 `_warmup_global_indices(),`（带逗号）——精确匹配调用点。
        count = src.count("_warmup_global_indices(),")
        assert count == 1, f"sequence 内 _warmup_global_indices() 应为 1 次，实际 {count}（双重执行回归）"

    def test_warmup_sequence_has_design_data_step(self):
        """R59④: 预热 sequence 包含设计数据预热步骤（K 线缓存预热）。"""
        src = open(main_mod.__file__, encoding="utf-8").read()
        assert "_warmup_design_data()" in src, "预热 sequence 应含设计数据预热（R59④）"

    def test_design_warmup_awaits_market_warmup(self):
        """R59④ 修复: 设计数据预热必须先等行情缓存预热任务完成（防 pool-empty 竞态跳过）。

        round28 实测：_warmup_market_cache 是非阻塞后台任务（sequence 内立即返回），
        旧 _warmup_design_data 直接读 pool → 必然先于 pool 填充执行 → 跳过
        （日志「design-data warmup skipped: pool empty」）→ R58 IC 回填拿不到
        K 线、R59③ 永不落盘。修复须 await _market_warmup_task + 轮询 pool。
        """
        src = open(main_mod.__file__, encoding="utf-8").read()
        assert "_market_warmup_task" in src, \
            "设计数据预热必须等待行情预热任务（R59④ 防竞态）"
        assert "asyncio.shield(_mkt_task)" in src, \
            "必须 await 市场预热任务（asyncio.shield 防超时取消）"


# ===================================================================
# merged from test_round28_fixes.py::TestR58IcBackfillRetry (S3.3 de-round, 2026-08-18)
# ===================================================================
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_mod
from app.services import market_service as ms
from app.services.market_data_hub import _rule_news_summary
from app.services.market_service import infer_market_from_symbol


class TestR58IcBackfillRetry:
    class _FakeHub:
        """渐进就绪的假 hub——第 1 次检查空、第 2 次检查有 rows。"""

        def __init__(self):
            self._checks = 0

        @property
        def _kline_cache_rows(self):
            self._checks += 1
            if self._checks >= 2:
                return {"510300": [{"date": "2026-08-14", "close": 3.8}]}
            return {}

    @pytest.mark.asyncio
    async def test_retries_until_kline_ready(self):
        """K 线缓存第 1 次未就绪 → 重试第 2 次就绪 → 返回 rows（非永久跳过）。"""
        hub = self._FakeHub()
        with patch.object(main_mod, "logger") as _logger:
            rows = await main_mod._wait_for_kline_rows(
                hub, initial_sleep=0.0, retry_delays=(0.0, 0.0), max_retries=2
            )
        assert rows, "缓存第 2 次就绪后应返回 rows（重试生效，非永久跳过）"
        assert hub._checks >= 2, f"应至少检查 2 次，实际 {hub._checks}"

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        """缓存恒未就绪 → 重试耗尽返回空 dict（调用方诚实放弃）。"""
        hub = MagicMock()
        hub._kline_cache_rows = {}
        with patch.object(main_mod, "logger") as _logger:
            rows = await main_mod._wait_for_kline_rows(
                hub, initial_sleep=0.0, retry_delays=(0.0, 0.0), max_retries=2
            )
        assert rows == {}, "重试耗尽后应返回空 dict（不得返回 None 或抛异常）"

    @pytest.mark.asyncio
    async def test_wait_for_pool_symbols_polls_until_ready(self):
        """R58 延伸: 启动时组合池未就绪（refresh() 60-90s）→ 轮询等待非空（非恒跳过）。"""
        class _FakePoolHub:
            def __init__(self):
                self._calls = 0

            def get_pool(self):
                self._calls += 1
                if self._calls >= 3:
                    return {
                        "core": [{"symbol": "510300", "name": "沪深300ETF", "layer": "core"}],
                        "satellite": [{"symbol": "159915", "name": "创业板ETF", "layer": "satellite"}],
                    }
                return {}

        hub = _FakePoolHub()
        with patch.object(main_mod, "logger"):
            syms = await main_mod._wait_for_pool_symbols(
                hub, checks=5, interval=0.0,
            )
        assert "510300" in syms, "池就绪后应返回 symbol 列表（轮询生效，非恒跳过）"
        assert hub._calls >= 3, f"应轮询 ≥3 次，实际 {hub._calls}"

    @pytest.mark.asyncio
    async def test_wait_for_pool_symbols_gives_up_honestly(self):
        """池恒空 → 返回空列表（调用方诚实放弃，不抛异常）。"""
        hub = MagicMock()
        hub.get_pool.return_value = {}
        with patch.object(main_mod, "logger"):
            syms = await main_mod._wait_for_pool_symbols(hub, checks=2, interval=0.0)
        assert syms == [], "池恒空应返回空列表"
