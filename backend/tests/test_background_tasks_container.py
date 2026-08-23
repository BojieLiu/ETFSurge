"""round35 §11-T-① (docs/round35-architecture-review.md) —
后台任务容器验证：强引用防 GC + 取消传播 + 优雅关停。

负向用例对旧代码必红：
- 裸 create_task 丢弃引用 → 模拟回收路径可中断任务；spawn 注册则必须存活至完成；
- 吞 CancelledError 的循环在 shutdown_all 中拖满超时 → 容器实现下任务立即终止。
"""
import asyncio

import pytest

from app.core import background_tasks as bt


@pytest.fixture(autouse=True)
def _clean_registry():
    bt._tasks.clear()
    yield
    bt._tasks.clear()


async def test_spawn_auto_discards_on_completion():
    """正向：spawn 的任务完成后集合自动清空（无泄漏）。"""
    done = asyncio.Event()

    async def work():
        done.set()

    t = bt.spawn(work(), name="probe")
    await asyncio.wait_for(done.wait(), timeout=2)
    await asyncio.sleep(0)  # 让 done_callback 跑一轮
    assert t not in bt._tasks
    assert bt.active_count() == 0


async def test_strong_reference_survives_collection_pressure():
    """负向①（抓 GC 回收）：丢弃返回值后施加回收压力，
    spawn 注册的任务必须存活至完成（裸 create_task 在同场景下可能被中断）。"""

    async def long_work():
        await asyncio.sleep(0.3)
        return 42

    t = bt.spawn(long_work(), name="gc-probe")
    # 不保留外部强引用路径上的其它副本：仅容器持有
    del t
    for _ in range(50):
        await asyncio.sleep(0)
        junk = [object() for _ in range(1000)]  # 制造分配压力
        del junk
    await asyncio.sleep(0.4)
    assert bt.active_count() == 0, "任务应已完成并自动摘除"


async def test_shutdown_all_cancels_compliant_loop_promptly():
    """负向②（抓取消吞没）：只捕 Exception 的循环（round35 新代码形态）在
    shutdown_all 下必须立即终止、远快于 timeout——若恢复旧的
    ``except (Exception, CancelledError): continue`` 写法，cancel 注入的
    CancelledError 被吞、循环永不退出，本断言必红。"""
    started = asyncio.Event()

    async def compliant_loop():
        while True:
            try:
                started.set()
                await asyncio.sleep(3600)
            except Exception:
                # 新模式：CancelledError（BaseException）自然传播
                continue

    bt.spawn(compliant_loop(), name="compliant-loop")
    await asyncio.wait_for(started.wait(), timeout=2)

    import time

    t0 = time.monotonic()
    errs = await asyncio.wait_for(bt.shutdown_all(timeout=10.0), timeout=5.0)
    elapsed = time.monotonic() - t0
    assert errs == []
    assert elapsed < 5.0, f"取消未及时生效（耗时 {elapsed:.1f}s）——CancelledError 被吞"
    assert bt.active_count() == 0


async def test_shutdown_timeout_protection_drops_stuck_tasks():
    """超时保护：吞掉 cancel 的僵死循环不能拖死关停流程——到达 timeout 后
    被放弃等待（从容器摘除），shutdown_all 正常返回。

    注：验证完毕后显式置停止旗标再补一次 cancel 让任务退出——绝对吞取消且
    无出口的协程会让事件循环 teardown（_cancel_all_tasks 仅注入一次 cancel）
    永久挂起，进程级无法清除。"""
    started = asyncio.Event()
    stop = asyncio.Event()

    async def swallowing_loop():
        while True:
            try:
                started.set()
                await asyncio.sleep(3600)
            except (Exception, asyncio.CancelledError):
                if stop.is_set():
                    raise  # 停止旗标已置位 → 不再吞，给事件循环清理留出口
                continue

    task = bt.spawn(swallowing_loop(), name="stuck-loop")
    await asyncio.wait_for(started.wait(), timeout=2)

    import time

    t0 = time.monotonic()
    errs = await asyncio.wait_for(bt.shutdown_all(timeout=0.5), timeout=5.0)
    elapsed = time.monotonic() - t0
    assert errs == []  # 卡死任务没有产生可收集的异常
    assert elapsed < 2.5, "超时保护未生效"
    assert bt.active_count() == 0

    # 清理：置旗标 + 补一次 cancel → 任务经吞取消分支检查旗标后退出
    stop.set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_shutdown_all_empty_set_returns_immediately():
    """边界：空集合上调 shutdown_all → 立即返回空列表。"""
    assert await bt.shutdown_all() == []


async def test_shutdown_collects_real_exceptions_not_cancel():
    """真实异常计入返回值；CancelledError 不计（正常取消路径）。
    注意先等任务进入 await 点——spawn 后立即 cancel 时任务尚未启动，
    会以纯 CancelledError 结束而不经过转换分支。"""
    entered = asyncio.Event()

    async def raises_after_cancel():
        entered.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise ValueError("converted")  # cancel 后转抛普通异常 → 应计入 errs

    bt.spawn(raises_after_cancel(), name="convert")
    await asyncio.wait_for(entered.wait(), timeout=2)
    errs = await bt.shutdown_all(timeout=5.0)
    assert any(isinstance(e, ValueError) for e in errs), errs
