from __future__ import annotations
"""
round36 §8-B: 事件循环滞后看门狗单测。

负向断言口径（无看门狗的旧实现下必红）：
  1. 循环被 time.sleep(0.5) 冻结（threshold=0.2）→ 必须产出含任务栈的
     lag 转储文件 + WARNING 日志——旧实现静默挂死、零证据；
  2. 正常 await 流动（无冻结）→ 不得产生转储文件（防误报）。
"""

import asyncio
import time

import pytest


@pytest.fixture
def _dump_dir(tmp_path):
    return tmp_path / "loop_lag"


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_lag_injection_produces_stack_dump(_dump_dir, caplog):
    """负向断言核心：注入 0.5s 循环冻结（阈值 0.2s）→ 必须有带栈转储 + 告警。"""
    from app.core.loop_watchdog import LoopLagWatchdog

    _dump_dir.mkdir(parents=True, exist_ok=True)
    wd = LoopLagWatchdog(interval=0.05, threshold=0.2, dump_dir=str(_dump_dir))
    wd_task = asyncio.ensure_future(wd.run())

    async def _blocker():
        # 直接在协程内同步 sleep：单线程事件循环被真实冻结（模拟 D1 实证的重段）
        time.sleep(0.5)

    await asyncio.ensure_future(_blocker())
    # 给看门狗一个 tick 的感知窗口（解冻后首个调度点即发现 lag）
    await asyncio.sleep(0.15)
    await _cancel(wd_task)

    dumps = list(_dump_dir.glob("loop_lag_*.log"))
    assert dumps, (
        "循环冻结 0.5s（阈值 0.2s）未产出任何 lag 转储——看门狗失效"
    )
    content = dumps[0].read_text(encoding="utf-8")
    assert "lag" in content.lower()
    assert any(rec.levelname == "WARNING" and "loop" in rec.message.lower()
               for rec in caplog.records), "滞后事件必须以 WARNING 记录"


@pytest.mark.asyncio
async def test_no_dump_without_lag(_dump_dir):
    """正常 await 流动 → 零转储（防误报）。"""
    from app.core.loop_watchdog import LoopLagWatchdog

    _dump_dir.mkdir(parents=True, exist_ok=True)
    wd = LoopLagWatchdog(interval=0.02, threshold=5.0, dump_dir=str(_dump_dir))
    wd_task = asyncio.ensure_future(wd.run())
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.3:
        await asyncio.sleep(0.01)
    await _cancel(wd_task)

    assert not list(_dump_dir.glob("loop_lag_*.log")), (
        "无冻结场景不得产生 lag 转储（误报）"
    )


@pytest.mark.asyncio
async def test_dump_respects_max_cap(_dump_dir):
    """max_dumps 上限：同进程内转储文件数封顶，防日志刷盘风暴。"""
    from app.core.loop_watchdog import LoopLagWatchdog

    _dump_dir.mkdir(parents=True, exist_ok=True)
    wd = LoopLagWatchdog(interval=0.02, threshold=0.05, dump_dir=str(_dump_dir),
                         max_dumps=3)
    wd_task = asyncio.ensure_future(wd.run())
    for _ in range(6):
        async def _b():
            time.sleep(0.08)
        await asyncio.ensure_future(_b())
        await asyncio.sleep(0.03)
    await _cancel(wd_task)

    assert len(list(_dump_dir.glob("loop_lag_*.log"))) <= 3, (
        "转储文件数必须被封顶（防冻结频发时刷盘）"
    )
