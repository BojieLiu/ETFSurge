"""
O2 (docs/round7-rediagnosis.md §7 P2): 预热任务串行化——控并发峰值。

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
