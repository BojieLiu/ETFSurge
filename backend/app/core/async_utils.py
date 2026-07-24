"""同步→异步包装工具。

统一使用 ``run_sync()`` 在线程池中执行同步函数，替代散落在各模块中
的私有 ``_sync()`` / ``asyncio.to_thread()`` 调用。
"""

import asyncio
import concurrent.futures
import threading

DEFAULT_SYNC_TIMEOUT = 8

# 全局共享线程池，替代各 fetcher 中频繁创建/销毁的 ThreadPoolExecutor
# 32 workers：统一承载 run_sync + 各 fetcher 同步调用 + 数据管道负载
_shared_executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)

# 默认 executor 监控（过渡期记录，P1 统一后移除）
_default_executor_lock = threading.Lock()
_default_executor_max = 0


def run_in_thread(fn, *args, timeout: int = DEFAULT_SYNC_TIMEOUT):
    """同步函数版：在全局共享线程池中执行 fn，带超时保护。

    供同步 fetcher 函数内部使用（替代在每个函数内新建 ThreadPoolExecutor）。
    用法: run_in_thread(fn) 或 run_in_thread(fn, arg1, arg2, timeout=5)
    """
    try:
        future = _shared_executor.submit(fn, *args)
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return None
    except Exception:
        return None


async def run_sync(call, *args, timeout: int = DEFAULT_SYNC_TIMEOUT):
    """在线程池中执行同步函数，带超时保护。

    Args:
        call: 可调用对象（同步函数）。
        *args: 传给 call 的变长参数。
        timeout: 超时秒数，默认 8 秒。

    Returns:
        call(*args) 的返回值。

    Raises:
        asyncio.TimeoutError: 超时未完成。
        call 抛出的原始异常。
    """
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_shared_executor, call, *args), timeout=timeout,
    )


def _get_default_executor_max() -> int:
    """获取默认 executor 的最大 worker 数（仅用于过渡期监控）。"""
    global _default_executor_max
    try:
        loop = asyncio.get_event_loop()
        default_exec = getattr(loop, '_default_executor', None)
        if default_exec is not None and hasattr(default_exec, '_max_workers'):
            _default_executor_max = default_exec._max_workers
    except RuntimeError:
        pass
    return _default_executor_max


def _executor_stats(executor) -> dict:
    """抽线程池的三个核心指标。"""
    max_w = executor._max_workers if hasattr(executor, '_max_workers') else 0
    alive = len(executor._threads) if hasattr(executor, '_threads') else 0
    pending = executor._work_queue.qsize() if hasattr(executor, '_work_queue') else -1
    return {"max_workers": max_w, "alive_threads": alive, "pending_tasks": pending}


def get_thread_pool_stats() -> dict:
    """返回共享线程池和默认 executor 的实时统计信息，用于健康监控。

    过渡期同时监控两个 pool，P1 完全落地后移除 default_executor。
    """
    return {
        "shared_executor": _executor_stats(_shared_executor),
        "default_executor": _executor_stats(
            getattr(asyncio.get_event_loop(), '_default_executor', None)
        ),
    }
