"""同步→异步包装工具。

统一使用 ``run_sync()`` 在线程池中执行同步函数，替代散落在各模块中
的私有 ``_sync()`` / ``asyncio.to_thread()`` 调用。
"""

import asyncio
import concurrent.futures
import logging
import threading

DEFAULT_SYNC_TIMEOUT = 8

# 全局共享线程池，替代各 fetcher 中频繁创建/销毁的 ThreadPoolExecutor
# 64 workers：统一承载 run_sync + 各 fetcher 同步调用 + 数据管道负载
# 原 32 workers 在高并发场景（多次 E2E 并行验证 + LLM 报告）下易耗尽，导致级联超时
# R6-F10 (round6 §十 R6-11): 64/64 饱和根因 = mootdx 容器空转期 run_sync 任务积压
# （R6-02）——R6-F1 修复 mootdx 后不应再饱和；不盲目扩容（>64 线程切换开销增加）。
# 若未来数据管道扩展导致再次饱和，再评估 64→128。
_shared_executor = concurrent.futures.ThreadPoolExecutor(max_workers=64)

# 长任务专用线程池（设计、检查、报告），与快速 API 请求隔离
# 8 workers 防止长任务占满 API 用的共享线程池
_long_running_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

# 默认 executor 监控（过渡期记录，P1 统一后移除）
_default_executor_lock = threading.Lock()
_default_executor_max = 0

# 队列深度峰值计数器 — 累积记录超过 ERROR 阈值的次数
_queue_depth_spike_count = 0
_queue_depth_spike_lock = threading.Lock()


def get_queue_depth_spike_count() -> int:
    """返回自启动以来线程池队列深度超过 ERROR 阈值的总次数。

    用于监控线程池饱和度趋势。
    """
    return _queue_depth_spike_count

# P1-5: 长任务 vs 快速 API 请求的线程池隔离标志
# 调用方可用 _use_long_running_executor() 装饰器或参数切换


def run_in_thread(fn, *args, timeout: int = DEFAULT_SYNC_TIMEOUT,
                  executor: str = "shared"):
    """同步包装：在线程池中执行同步函数，带超时保护。

    供同步 fetcher 内部使用。超时时返回 None，底层线程继续运行但
    完成后会自动归还线程池，不会变成僵尸线程。

    Args:
        fn: 可调用对象（同步函数）。
        *args: 传给 fn 的变长参数。
        timeout: 超时秒数，默认 8 秒。
        executor: 线程池选择。
            "shared" (默认, ≤5s 任务) — 使用 _shared_executor (64 workers)
            "long" (>5s 任务) — 使用 _long_running_executor (8 workers)

    Returns:
        fn(*args) 的返回值，或 None（超时/异常时）。
    """
    pool = _long_running_executor if executor == "long" else _shared_executor
    future = pool.submit(fn, *args)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return None
    except Exception:
        return None


def safe_call(fn, *args, timeout: int = DEFAULT_SYNC_TIMEOUT,
              executor: str = "shared"):
    """统一安全调用（round11 P1-2，收敛各 fetcher 的 _safe/_exec 复制）。

    语义与 run_in_thread 相同：线程池执行 + 超时/异常 → None，绝不挂起。
    不同模块通过 executor 参数选择池（news 用 shared，levistock/sector 用 long）。

    round23 §10.2 D1: safe_call/safe_call_async 是 run_in_thread/run_sync 的零逻辑
    透传——标记 deprecated 别名（短期保留控制改动面，后续轮次移除；新代码直接用
    run_in_thread / run_sync）。
    """
    return run_in_thread(fn, *args, timeout=timeout, executor=executor)


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

    Note:
        当线程池队列深度超过阈值时自动打 WARNING 日志，便于排查级联超时。
    """
    _pending = _shared_executor._work_queue.qsize() if hasattr(_shared_executor, '_work_queue') else 0
    if _pending > 16:
        _logger = logging.getLogger(__name__)
        _logger.error("[async_utils] run_sync queue depth=%d (fn=%s, timeout=%ds) — POOL SATURATION!",
                     _pending, getattr(call, '__name__', str(call)), timeout)
        with _queue_depth_spike_lock:
            global _queue_depth_spike_count
            _queue_depth_spike_count += 1
    elif _pending > 8:
        _logger = logging.getLogger(__name__)
        _logger.warning("[async_utils] run_sync queue depth=%d (fn=%s, timeout=%ds) — pool may be saturated",
                       _pending, getattr(call, '__name__', str(call)), timeout)
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_shared_executor, call, *args), timeout=timeout,
    )


async def run_sync_long(call, *args, timeout: int = 120):
    """在长任务专用线程池中执行同步函数，与快速 API 请求隔离。

    用于设计、检查、报告等耗时 > 10s 的同步操作。
    timeout 默认 120s（长任务通常 30-90s）。
    """
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_long_running_executor, call, *args),
        timeout=timeout,
    )


async def safe_call_async(call, *args, timeout: int = DEFAULT_SYNC_TIMEOUT):
    """统一安全调用 async 版（round11 P1-2，收敛 market_service._call）。

    await run_sync 执行同步函数，超时/异常 → None。
    CancelledError 语义保留：外层 wait_for 超时会触发 CancelledError，
    漏接会冒泡到任务边界（market_service._call 原始注释），故显式返回 None。
    """
    try:
        return await run_sync(call, *args, timeout=timeout)
    except asyncio.CancelledError:
        return None
    except Exception as e:
        logging.getLogger(__name__).warning(
            "[async_utils] safe_call_async failed for %s: %s",
            getattr(call, '__name__', str(call)), e,
        )
        return None


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
    """抽线程池的核心指标。"""
    max_w = executor._max_workers if hasattr(executor, '_max_workers') else 0
    alive = len(executor._threads) if hasattr(executor, '_threads') else 0
    pending = executor._work_queue.qsize() if hasattr(executor, '_work_queue') else -1
    total_spawned = getattr(executor, '_num_threads_ever', 0) if hasattr(executor, '_num_threads_ever') else 0
    return {"max_workers": max_w, "alive_threads": alive, "pending_tasks": pending, "total_spawned": total_spawned}


def get_thread_pool_stats() -> dict:
    """返回共享线程池和默认 executor 的实时统计信息，用于健康监控。

    过渡期同时监控两个 pool，P1 完全落地后移除 default_executor。
    """
    default_exec = None
    try:
        loop = asyncio.get_event_loop()
        default_exec = getattr(loop, '_default_executor', None)
    except RuntimeError:
        # Called from a thread without an event loop (e.g. thread pool probe)
        pass
    return {
        "shared_executor": _executor_stats(_shared_executor),
        "default_executor": _executor_stats(default_exec),
    }
