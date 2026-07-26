"""数据源健康 / 路由层。

提供轻量熔断器(circuit breaker)与按健康度选源的 `route()`:
- 每个源有连续失败计数与冷却时间;失败达到阈值后进入冷却,期间跳过该源;
- `route()` 按优先级尝试各源,跳过冷却中或不可用的源,记录成败以更新健康度。
- 支持 `on_event` 回调,将成功/失败事件推送到 SourceEventStore。
这样多个免费数据源可以互相补充、自动隔离不稳定的源,提升整体稳定性。
"""

import threading
import time
from typing import Any, Callable, Optional


class SourceHealth:
    def __init__(self, cooldown: float = 60.0, failure_threshold: int = 3,
                 on_event: Optional[Callable] = None) -> None:
        self.cooldown = cooldown
        self.failure_threshold = failure_threshold
        self._on_event = on_event
        self._failures = 0
        self._cool_until = 0.0
        self._lock = threading.Lock()

    def available(self, now: float) -> bool:
        with self._lock:
            return now >= self._cool_until

    def record_success(self, route: str = "", operation: str = "realtime",
                       target: str = "", duration_ms: float = 0.0) -> None:
        with self._lock:
            self._failures = 0
            self._cool_until = 0.0
        self._emit_event(route, operation, target, True, duration_ms, "")

    def record_failure(self, now: float, route: str = "", operation: str = "realtime",
                       target: str = "", duration_ms: float = 0.0,
                       error_message: str = "") -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._cool_until = now + self.cooldown
                self._failures = 0
        self._emit_event(route, operation, target, False, duration_ms, error_message)

    def record_hard_failure(self, now: float, route: str = "",
                            operation: str = "realtime", target: str = "",
                            duration_ms: float = 0.0,
                            error_message: str = "") -> None:
        """Immediate cooling — for HTTP 4xx/5xx where the source is clearly dead.

        Skips failure_threshold counting: goes straight to cooldown.
        """
        with self._lock:
            self._cool_until = now + self.cooldown
            self._failures = 0
        self._emit_event(route, operation, target, False, duration_ms,
                         f"[HARD] {error_message}")

    def set_on_event(self, cb: Optional[Callable]) -> None:
        self._on_event = cb

    def _emit_event(self, route: str, operation: str, target: str,
                    success: bool, duration_ms: float, error_message: str) -> None:
        if self._on_event is not None:
            try:
                self._on_event(route, operation, target, success, duration_ms, error_message)
            except Exception:
                pass  # Don't let callbacks cascade exceptions


class SourceRegistry:
    def __init__(self) -> None:
        self._states: dict[str, SourceHealth] = {}
        self._on_event: Optional[Callable] = None

    def set_event_callback(self, cb: Optional[Callable]) -> None:
        """Set a global event callback for all source health events.

        The callback receives (source_name, route, operation, target,
        success, duration_ms, error_message).
        """
        self._on_event = cb
        for name, h in self._states.items():
            h.set_on_event(cb)
            # Inject source_name into the callback closure
            h.set_on_event(self._make_source_callback(name))

    def _make_source_callback(self, source_name: str) -> Callable:
        """Wrap the global _on_event with source_name injection."""
        def _wrapped(route, operation, target, success, duration_ms, error_message):
            if self._on_event is not None:
                try:
                    self._on_event(source_name, route, operation, target,
                                   success, duration_ms, error_message)
                except Exception:
                    pass
        return _wrapped

    def _health(self, name: str) -> SourceHealth:
        if name not in self._states:
            h = SourceHealth(on_event=self._make_source_callback(name))
            self._states[name] = h
        return self._states[name]

    def route(self, providers: list[tuple[str, Callable[[], Any]]],
              route_name: str = "",
              operation: str = "realtime",
              target: str = "") -> Any:
        """按优先级尝试 providers = [(源名, 无参 callable), ...]。

        Args:
            providers: 源列表 [(源名, callable), ...]
            route_name: 路由名称 (如 'US_ETF', 'A_stock_realtime'), 用于事件追踪
            operation: 操作类型 ('realtime' / 'history' / 'batch' / 'probe')
            target: 目标标的 (如 'SPY', '000001'), 用于事件追踪

        返回第一个成功(非 None 且非异常)的结果;全部失败返回 None。
        熔断中的源会被直接跳过。

        Provider 可以返回:
        - 原始数据: 成功时返回非空值,失败返回 None/[]。
        - (data, http_status) 元组: data 为实际返回值或 None,
          http_status 为 HTTP 状态码(0 表示非 HTTP 错误)。
          当 http_status >= 400 时,触发硬失败立即冷却该源。
        """
        now = time.time()
        last_exc: Optional[BaseException] = None
        for name, fn in providers:
            h = self._health(name)
            if not h.available(now):
                continue
            t0 = time.perf_counter()
            try:
                result = fn()
                elapsed = (time.perf_counter() - t0) * 1000
                # 支持 (data, http_status) 元组
                http_status = 0
                if isinstance(result, tuple) and len(result) == 2:
                    data, http_status = result
                else:
                    data = result
                # HTTP 4xx/5xx: 硬失败,立即冷却,不尝试下游
                if http_status >= 400:
                    h.record_hard_failure(now, route=route_name,
                                          operation=operation, target=target,
                                          duration_ms=elapsed,
                                          error_message=f"HTTP {http_status} from {name}")
                    continue
                if data:  # 空列表/None 视为该源未提供数据,继续下一个
                    h.record_success(route=route_name, operation=operation,
                                     target=target, duration_ms=elapsed)
                    return data
                h.record_failure(now, route=route_name, operation=operation,
                                 target=target, duration_ms=elapsed,
                                 error_message=f"empty result from {name}")
            except Exception as e:  # noqa: BLE001 - 源级异常需隔离
                elapsed = (time.perf_counter() - t0) * 1000
                last_exc = e
                h.record_failure(now, route=route_name, operation=operation,
                                 target=target, duration_ms=elapsed,
                                 error_message=str(e)[:200])
        if last_exc:
            # 让调用方知道至少发生过异常(便于日志),但不抛出
            pass
        return None

    def get_states(self) -> dict[str, SourceHealth]:
        """Return all registered source health states (for monitoring)."""
        return dict(self._states)

    def circuit_breaker_status(self) -> list[dict]:
        """Return circuit-breaker status for all registered sources."""
        now = time.time()
        result = []
        for name, h in self._states.items():
            with h._lock:
                status = {
                    "name": name,
                    "state": "open" if now < h._cool_until else "closed",
                    "failure_threshold": h.failure_threshold,
                    "cooldown_secs": h.cooldown,
                    "failures_since_last_ok": h._failures,
                }
                if now < h._cool_until:
                    status["cool_until"] = h._cool_until
                result.append(status)
        return result


# 全局注册表(跨请求共享健康度)
registry = SourceRegistry()
