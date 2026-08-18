"""Circuit breaker / quota gate / error diagnostics — split from analysis/llm.py (Batch 2)."""

import asyncio
import time

from app.core.logging import get_logger

logger = get_logger(__name__)

_last_llm_error: str | None = None

_CIRCUIT_TTL = 300.0

_CIRCUIT_FAIL_THRESHOLD = 2

_circuit: dict[str, dict] = {}


def get_last_llm_error() -> str | None:
    """R5-1-6: 返回最近一次 LLM 失败诊断（成功调用后为 None）。"""
    return _last_llm_error


def _record_llm_error(exc: BaseException) -> None:
    """R5-1-6: 记录 provider 失败诊断，429 → [rate-limited]，连接超时 → [timeout]。"""
    global _last_llm_error
    try:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            _last_llm_error = "[rate-limited] 429 Too Many Requests"
        elif isinstance(exc, TimeoutError) or isinstance(exc, asyncio.TimeoutError):
            _last_llm_error = "[timeout] connection timed out"
        elif "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            _last_llm_error = f"[timeout] {exc}"
        else:
            _last_llm_error = str(exc) or type(exc).__name__
    except Exception:
        _last_llm_error = str(exc) or type(exc).__name__


def _clear_llm_error() -> None:
    """R5-1-6: LLM 调用成功 → 清空错误诊断。"""
    global _last_llm_error
    _last_llm_error = None


def _circuit_state(provider_id: str) -> str:
    """返回 provider 当前熔断态（未登记即 CLOSED）。"""
    return _circuit.get(provider_id, {}).get("state", "CLOSED")


def _circuit_allow(provider_id: str) -> bool:
    """该 provider 本次是否允许尝试（OPEN 且未到 TTL → 跳过；HALF_OPEN 允许复探）。"""
    entry = _circuit.get(provider_id)
    if entry is None:
        return True  # CLOSED
    now = time.monotonic()
    if entry["state"] == "OPEN":
        if now - entry["opened_at"] >= _CIRCUIT_TTL:
            entry["state"] = "HALF_OPEN"
            entry["opened_at"] = now
            return True
        return False
    # CLOSED / HALF_OPEN 均允许
    return True


def _circuit_record_failure(provider_id: str, is_quota_error: bool) -> None:
    """记录一次失败。
    - 429/FreeUsageLimitError（额度类，持久）→ 立即 OPEN，零复试（F9c）。
    - 5xx/timeout（瞬态）→ 累计达阈值才 OPEN，保留有限重试。
    """
    now = time.monotonic()
    entry = _circuit.get(provider_id)
    if entry is None:
        entry = {"state": "CLOSED", "fail_count": 0, "opened_at": 0.0}
        _circuit[provider_id] = entry
    if is_quota_error:
        entry["state"] = "OPEN"
        entry["opened_at"] = now
        entry["fail_count"] = 0
        logger.warning("[circuit] provider %s quota-exhausted → OPEN (skip until HALF_OPEN)", provider_id)
        # round25 R39: 额度耗尽 → 跨任务配额门禁全局暂停（后续 LLM 调用直落兜底不硬撞）
        llm_quota_gate.mark_exhausted()
        return
    entry["fail_count"] = entry.get("fail_count", 0) + 1
    if entry["fail_count"] >= _CIRCUIT_FAIL_THRESHOLD:
        entry["state"] = "OPEN"
        entry["opened_at"] = now


def _circuit_record_success(provider_id: str) -> None:
    """记录一次成功：OPEN/HALF_OPEN → CLOSED，清零计数。"""
    entry = _circuit.get(provider_id)
    if entry is None:
        return
    if entry["state"] in ("OPEN", "HALF_OPEN"):
        logger.info("[circuit] provider %s recovered → CLOSED", provider_id)
    entry["state"] = "CLOSED"
    entry["fail_count"] = 0


def reset_circuit() -> None:
    """测试/运维用：清空熔断状态。"""
    _circuit.clear()
    # round25 R39: 同步复位跨任务配额门禁（单例 _last 跨测试持久，避免冷却污染）
    llm_quota_gate._last = 0.0
    llm_quota_gate._exhausted_until = 0.0


class LLMQuotaGate:
    inter_call_cooldown = 8.0   # 任意两次 LLM 调用最小间隔（跨任务，秒）
    quota_cooldown = 60.0       # 429 后全局暂停时长（秒）
    _last = 0.0
    _exhausted_until = 0.0

    async def acquire(self, min_gap: float | None = None) -> None:
        gap = min_gap or self.inter_call_cooldown
        now = time.monotonic()
        wait = max(0.0, self._last + gap - now, self._exhausted_until - now)
        if wait > 0:
            logger.info("[llm_quota_gate] throttling LLM call by %.1fs", wait)
            await asyncio.sleep(wait)
        self._last = time.monotonic()

    def mark_exhausted(self, secs: float | None = None) -> None:
        self._exhausted_until = time.monotonic() + (secs or self.quota_cooldown)
        logger.warning(
            "[llm_quota_gate] LLM quota exhausted → global pause for %.1fs",
            self._exhausted_until - time.monotonic(),
        )


llm_quota_gate = LLMQuotaGate()
