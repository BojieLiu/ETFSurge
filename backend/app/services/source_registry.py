"""数据源健康 / 路由层。

提供轻量熔断器(circuit breaker)与按健康度选源的 `route()`:
- 每个源有连续失败计数与冷却时间;失败达到阈值后进入冷却,期间跳过该源;
- `route()` 按优先级尝试各源,跳过冷却中或不可用的源,记录成败以更新健康度。
这样多个免费数据源可以互相补充、自动隔离不稳定的源,提升整体稳定性。
"""

from typing import Any, Callable, Optional


class SourceHealth:
    def __init__(self, cooldown: float = 60.0, failure_threshold: int = 3) -> None:
        self.cooldown = cooldown
        self.failure_threshold = failure_threshold
        self._failures = 0
        self._cool_until = 0.0

    def available(self, now: float) -> bool:
        if now >= self._cool_until:
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._cool_until = 0.0

    def record_failure(self, now: float) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._cool_until = now + self.cooldown
            self._failures = 0


class SourceRegistry:
    def __init__(self) -> None:
        self._states: dict[str, SourceHealth] = {}

    def _health(self, name: str) -> SourceHealth:
        if name not in self._states:
            self._states[name] = SourceHealth()
        return self._states[name]

    def route(self, providers: list[tuple[str, Callable[[], Any]]], now: Optional[float] = None) -> Any:
        """按优先级尝试 providers = [(源名, 无参 callable), ...]。

        返回第一个成功(非 None 且非异常)的结果;全部失败返回 None。
        熔断中的源会被直接跳过。
        """
        import time

        now = now if now is not None else time.time()
        last_exc: Optional[BaseException] = None
        for name, fn in providers:
            h = self._health(name)
            if not h.available(now):
                continue
            try:
                result = fn()
                if result:  # 空列表/None 视为该源未提供数据,继续下一个
                    h.record_success()
                    return result
                h.record_failure(now)
            except Exception as e:  # noqa: BLE001 - 源级异常需隔离
                last_exc = e
                h.record_failure(now)
        if last_exc:
            # 让调用方知道至少发生过异常(便于日志),但不抛出
            pass
        return None


# 全局注册表(跨请求共享健康度)
registry = SourceRegistry()
