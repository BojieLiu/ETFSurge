"""进程内后台任务容器——强引用防 GC + 优雅关停（round35 §11-T-①）。

背景（docs/round35-architecture-review.md §11.2 P0-1/P0-2）：
- 事件循环对 asyncio.Task 只持弱引用，裸 ``asyncio.create_task`` 丢弃返回值后，
  长任务（design 全程 ~6 分钟）存在被 GC 中途回收的风险窗口；
- 常驻刷新循环此前吞 CancelledError 且 shutdown 不 cancel——取消请求静默失效，
  关停时 DB 写入可能被拦腰截断。

用法：lifespan 常驻循环与路由层用户任务提交一律走 :func:`spawn`；
lifespan shutdown 在关闭其它存储之前调用 :func:`shutdown_all`。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def spawn(coro, *, name: str | None = None) -> asyncio.Task:
    """替代裸 asyncio.create_task：注册强引用 + 完成自动摘除。"""
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def active_count() -> int:
    """当前在册任务数（测试/观测用）。"""
    return len(_tasks)


async def shutdown_all(timeout: float = 10.0) -> list[BaseException]:
    """lifespan shutdown 调用：逐个 cancel → gather 收尾。

    CancelledError 是正常取消路径，不计入异常；其余异常打 ERROR 并返回给调用方。
    超时保护：个别任务若卡死不响应 cancel，超过 *timeout* 秒后放弃等待继续关停
    （避免关停流程被单个僵死任务拖死）。
    """
    if not _tasks:
        return []
    for t in _tasks:
        t.cancel()
    done, pending = await asyncio.wait(set(_tasks), timeout=timeout)
    errs: list[BaseException] = []
    for t in done:
        # Task.exception() 对被取消的任务会 *raise* CancelledError（而非返回），
        # 必须先用 t.cancelled() 分流——否则关停流程自身被取消异常打断。
        if t.cancelled():
            continue
        exc = t.exception()
        if exc is None or isinstance(exc, asyncio.CancelledError):
            continue
        errs.append(exc)
    if pending:
        names = [t.get_name() for t in pending]
        logger.error("[background_tasks] %d task(s) did not finish within %.0fs: %s",
                     len(pending), timeout, names)
        for t in pending:
            _tasks.discard(t)
    else:
        _tasks.clear()
    return errs
