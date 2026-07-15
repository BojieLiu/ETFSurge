"""
数据源主动健康探测。

每 60s 对所有注册源做一次 ping，记录成败到 SourceRegistry，
提前冷却不可用源，避免用户请求打到坏源。
"""

import asyncio
import time
from collections.abc import Callable
from ..core.logging import get_logger
from ..services.source_registry import registry

logger = get_logger(__name__)

# (源名称, 无参 callable, 超时秒)
_PROBES: list[tuple[str, Callable, int]] = []


def register_probe(name: str, fn: Callable, timeout: int = 5):
    """注册一个探测项。name 须与 SourceRegistry 中的源名称一致。"""
    _PROBES.append((name, fn, timeout))


async def run_probes():
    """遍历所有探针，在独立线程中执行探测函数，记录成败到 SourceRegistry。"""
    now = time.time()
    for name, fn, timeout in _PROBES:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(fn), timeout=timeout
            )
            if result:
                registry._health(name).record_success()
                logger.debug(f"[health] {name} OK")
            else:
                registry._health(name).record_failure(now)
                logger.warning(f"[health] {name} returned empty → cooling")
        except Exception as e:
            registry._health(name).record_failure(now)
            logger.warning(f"[health] {name} error: {e}")


async def health_loop(interval: float = 60.0):
    """启动循环探测（在 main.py lifespan 中调用）。"""
    logger.info(f"[health] probe loop started (interval={interval}s)")
    while True:
        await asyncio.sleep(interval)
        await run_probes()
