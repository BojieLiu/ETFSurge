"""同步→异步包装工具。

统一使用 ``run_sync()`` 在线程池中执行同步函数，替代散落在各模块中
的私有 ``_sync()`` / ``asyncio.to_thread()`` 调用。
"""

import asyncio
import concurrent.futures

DEFAULT_SYNC_TIMEOUT = 8

# 全局共享线程池，替代各 fetcher 中频繁创建/销毁的 ThreadPoolExecutor
# 16 workers：预热时 market_refresh (25s) 和 global_indices (30s) 同时运行不争抢
_shared_executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)


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
        loop.run_in_executor(None, call, *args), timeout=timeout,
    )


def get_thread_pool_stats() -> dict:
    """返回全局共享线程池的实时统计信息，用于健康监控。"""
    # ThreadPoolExecutor 内部通过 _threads 集合追踪活跃线程
    workers = _shared_executor._max_workers
    alive = len(_shared_executor._threads) if hasattr(_shared_executor, '_threads') else 0
    # 估算排队任务数：_work_queue.qsize() + 已提交未完成的 future
    pending = _shared_executor._work_queue.qsize() if hasattr(_shared_executor, '_work_queue') else -1
    return {
        "max_workers": workers,
        "alive_threads": alive,
        "pending_tasks": pending,
    }
