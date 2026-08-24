"""round35 A3 (docs/round35-architecture-review.md §13.4-A3): 共享线程池有界提交守卫。

负向用例（能抓假，§13.8-5）：
- 人为占满提交槽位 → 断言**快速拒绝**（PoolSaturatedError / run_in_thread→None）
  而非无限排队；
- 槽位归还是**工作线程完成时**（finally），调用方超时弃等不吞槽位；
- 异常路径同样归还；long 专用池不受共享池守卫影响。

确定性手段：fixture 将模块级 ``_submit_slots`` 替换为 2 槽小信号量，
避免依赖真实 128 槽的时序。
"""

import asyncio
import threading
import time

import pytest

from app.core import async_utils
from app.core.async_utils import (
    PoolSaturatedError,
    run_in_thread,
    run_sync,
)


@pytest.fixture
def tiny_slots(monkeypatch):
    """2 槽守卫信号量（替换模块级实例），测试结束自动还原。"""
    sem = threading.BoundedSemaphore(2)
    monkeypatch.setattr(async_utils, "_submit_slots", sem)
    return sem


async def _occupy_two_slots_with_real_tasks(tiny_slots):
    """通过真实 run_sync 提交两个阻塞任务占满槽位，返回 (tasks, release_fn)。"""
    release = threading.Event()

    def blocker():
        release.wait(2)
        return "done"

    t1 = asyncio.ensure_future(run_sync(blocker, timeout=5))
    t2 = asyncio.ensure_future(run_sync(blocker, timeout=5))
    for _ in range(50):
        if tiny_slots._value == 0:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("two in-flight submissions did not exhaust 2-slot guard")
    return (t1, t2), release.set


async def test_run_sync_fast_rejects_when_saturated(tiny_slots):
    tasks, release = await _occupy_two_slots_with_real_tasks(tiny_slots)
    t0 = time.monotonic()
    with pytest.raises(PoolSaturatedError, match="in-flight"):
        await run_sync(lambda: 1)
    assert time.monotonic() - t0 < 0.5, "must fast-reject, not queue behind blockers"
    release()
    assert [await t for t in tasks] == ["done", "done"]


async def test_run_sync_succeeds_and_releases_after_completion(tiny_slots):
    assert await run_sync(lambda: 42) == 42
    assert tiny_slots._value == 2, "slot must be returned when worker finishes"
    # 归还后可继续正常提交
    assert await run_sync(lambda: 7) == 7


async def test_run_sync_keeps_slot_until_worker_done_after_timeout(tiny_slots):
    started = threading.Event()

    def slow():
        started.set()
        time.sleep(0.15)
        return "late"

    with pytest.raises(asyncio.TimeoutError):
        await run_sync(slow, timeout=0.02)
    # 调用方已弃等，但线程仍在跑：槽位必须仍被占用（防超限提交）
    deadline = time.monotonic() + 0.5
    while not started.is_set() and time.monotonic() < deadline:
        await asyncio.sleep(0.005)
    assert tiny_slots._value == 1, "abandoned-by-timeout call must still hold its slot"
    await asyncio.sleep(0.25)  # 等工作线程自然完成
    assert tiny_slots._value == 2, "worker completion must return the slot"


async def test_run_sync_returns_slot_on_exception(tiny_slots):
    def boom():
        raise ValueError("worker failure")

    with pytest.raises(ValueError, match="worker failure"):
        await run_sync(boom)
    assert tiny_slots._value == 2, "exception path must also release the slot"


def test_run_in_thread_degrades_to_none_when_saturated(tiny_slots):
    tiny_slots.acquire()
    tiny_slots.acquire()
    before = async_utils.get_queue_depth_spike_count()
    t0 = time.monotonic()
    assert run_in_thread(lambda: 1, timeout=0.5) is None, "contract: never hang"
    assert time.monotonic() - t0 < 0.5
    assert async_utils.get_queue_depth_spike_count() == before + 1, (
        "saturation rejection must bump spike counter (monitoring contract)"
    )


def test_run_in_thread_shared_path_wraps_for_release(tiny_slots):
    assert run_in_thread(lambda: "ok") == "ok"
    assert tiny_slots._value == 2


def test_long_executor_not_guarded_by_shared_slots(tiny_slots):
    tiny_slots.acquire()
    tiny_slots.acquire()
    # 共享池满不应影响 long 专用池（设计/报告长任务隔离语义）
    assert run_in_thread(lambda: "long-ok", executor="long") == "long-ok"
