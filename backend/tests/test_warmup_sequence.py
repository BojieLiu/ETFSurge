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
# R170 (round52 §4.3 方案A): warmup 分段计时与 budget 告警同口径
#
# round52 §4.1: budget 告警按 _seq_elapsed 全序计时（7 任务）报 39.8s，
# warmup_timing.json 只有 6 records 合计 7.46s——~32s 无归属，告警无法归因。
# 负向断言：慢段必须出现在分段记录里、未覆盖段必须被点名，否则抓不住该回归。
# ===================================================================
import asyncio
import time

import pytest

import app.main as _main


@pytest.fixture(autouse=True)
def _reset_segments():
    _main._WARMUP_SEGMENTS.clear()
    yield
    _main._WARMUP_SEGMENTS.clear()


class TestR170WarmupSegmentTiming:
    @pytest.mark.asyncio
    async def test_labeled_task_records_segment(self):
        """(label, coro) 形态 → 每个任务都留下分段计时（含耗时值）。"""
        async def slow():
            await asyncio.sleep(0.05)

        await _main._run_warmup_sequence([("design_data", slow())])
        segs = {str(s["label"]): float(s["duration_ms"]) for s in _main._WARMUP_SEGMENTS}
        assert "design_data" in segs, f"慢段必须入账，实际 {segs}"
        assert segs["design_data"] >= 50, f"分段耗时应为实测值（≥50ms），实际 {segs}"

    @pytest.mark.asyncio
    async def test_bare_coroutine_does_not_fake_record(self):
        """负向：裸协程（无 label）不得伪造分段记录（保持旧调用兼容）。"""
        async def noop():
            return None

        await _main._run_warmup_sequence([noop()])
        assert _main._WARMUP_SEGMENTS == [], "无 label 的任务不得产生分段记录"

    @pytest.mark.asyncio
    async def test_all_sequence_labels_covered_when_all_run(self):
        """7 段全跑 → 无未覆盖段（budget 告警不再指向无归属差额）。"""
        async def noop():
            return None

        await _main._run_warmup_sequence([(lb, noop()) for lb in _main._WARMUP_SEQUENCE_LABELS])
        assert _main._warmup_uncovered_segments() == [], \
            f"7 段全跑后不应有未覆盖段，实际 {_main._warmup_uncovered_segments()}"
        assert len(_main._WARMUP_SEGMENTS) == len(_main._WARMUP_SEQUENCE_LABELS)

    @pytest.mark.asyncio
    async def test_uncovered_segments_named(self):
        """负向：漏跑的段必须被点名（否则 39.8s vs 7.46s 缺口无人报错）。"""
        async def noop():
            return None

        await _main._run_warmup_sequence([("market_cache", noop()), ("etf_cache", noop())])
        uncovered = _main._warmup_uncovered_segments()
        assert "instruments_sync" in uncovered, f"未跑的段必须出现在未覆盖清单，实际 {uncovered}"
        assert "design_data" in uncovered
        assert len(uncovered) == len(_main._WARMUP_SEQUENCE_LABELS) - 2

    def test_budget_warning_attributes_slow_segment(self):
        """验收口径（round52 §4.3 方案A）: 慢段 35s → 告警必须点名该段。"""
        segments = [
            {"label": "design_data", "duration_ms": 35000.0},
            {"label": "market_cache", "duration_ms": 2100.0},
        ]
        msg = _main._format_warmup_budget_warning(39.8, 30.0, segments, [])
        assert "design_data" in msg, f"告警必须含最慢段名，实际: {msg}"
        assert "35.0s" in msg, f"告警必须含该段耗时，实际: {msg}"
        assert "39.8s" in msg

    def test_budget_warning_lists_uncovered_segments(self):
        """负向：存在未入 timing 的段时，告警必须列出（归因缺口自曝）。"""
        msg = _main._format_warmup_budget_warning(39.8, 30.0, [], ["design_data", "sector_cache"])
        assert "design_data" in msg and "sector_cache" in msg, \
            f"未覆盖段必须在告警中列出，实际: {msg}"

    def test_budget_ok_message_has_no_attribution_noise(self):
        """达标时输出简洁信息（不虚构分段归因）。"""
        msg = _main._format_warmup_budget_warning(7.5, 30.0, [], [])
        assert "7.5s" in msg and "设计" not in msg


def test_warmup_timing_json_carries_sequence_segments(tmp_path):
    """warmup_timing.json 必须携带 sequence 分段（告警指向的 json 可归因）。"""
    from app.profiling.warmup_profiler import WarmupProfiler

    p = WarmupProfiler(output_dir=str(tmp_path))
    p.record("init_db", 100.0, "db")
    path = p.write_report("warmup_timing.json", extra={
        "sequence_segments": [{"label": "design_data", "duration_ms": 35000.0}],
        "sequence_total_ms": 35000.0,
        "sequence_uncovered": ["sector_cache"],
    })
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["sequence_segments"][0]["label"] == "design_data"
    assert data["sequence_uncovered"] == ["sector_cache"]
    # 分段不计入 total_duration_ms——避免 A01 门禁（20s 失败线）被口径变更误伤
    assert data["total_duration_ms"] == 100.0, \
        f"sequence 分段不得并入 total_duration_ms，实际 {data['total_duration_ms']}"


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
        """sequence 内 `_warmup_global_indices()` 恰好调用一次（基数断言）。"""
        src = open(main_mod.__file__, encoding="utf-8").read()
        # R170 (round52): sequence 元素改为 `(label, coro)` 形态，调用点不再带裸逗号；
        # 口径改为「调用次数 = 总出现次数 − 定义行」，仍可抓双重执行回归。
        count = src.count("_warmup_global_indices()") - src.count("async def _warmup_global_indices()")
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
