"""同步→异步包装工具。

统一使用 ``run_sync()`` 在线程池中执行同步函数，替代散落在各模块中
的私有 ``_sync()`` / ``asyncio.to_thread()`` 调用。
"""

import asyncio

# 默认超时阈值（秒），大部分同步数据源调用应在该时间内完成
DEFAULT_SYNC_TIMEOUT = 8


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
