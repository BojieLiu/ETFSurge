"""Circuit breaker / quota gate / error diagnostics — split from analysis/llm.py (Batch 2)."""

import asyncio
import time

from app.core.logging import get_logger

logger = get_logger(__name__)

_last_llm_error: str | None = None

_CIRCUIT_TTL = 300.0
# round39 改进 (R143 改进): 429 (quota 类) TTL 30min 而非 5min，与免费模型配额窗口
# (小时级) 对齐——避免锯齿复探反复撞 429；瞬态 5xx/timeout 仍 5min（短重试以恢复）。
_CIRCUIT_TTL_QUOTA = 1800.0

_CIRCUIT_FAIL_THRESHOLD = 2

# round39 改进: 永久性错误特征文案 (供 _classify_permanent_error 用)
_PERMANENT_ERROR_PATTERNS: tuple[tuple[str, str], ...] = (
    ("400", r"Model (?:is unavailable|does not exist|is not supported)"),
    ("400", r"Upstream request failed"),
    ("401", r"is not supported|Authorization"),
    ("403", r"not available in your country|Access restricted|Deposit required|credit insufficient balance"),
)

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


# ── round35 §19 Gap B: 熔断键下沉到 model 级 + 403 门禁长冷却 ─────────
# 单免费模型不可用 ≠ provider 整层不可用（§19.1 实锤：deepseek-v4-flash-free
# 当日 400 而其余 7 个 -free 存活）。key 规约：传 model 时为 "provider:model"，
# 不传保持旧 "provider" 键——既有行为锚（test_llm_circuit_state.py 等）零修改。
#
# 403 客户端类型门禁（§19.9 约束#1，如 "agentic harness only"）：该模型服务端
# 直调永不可用 → 长冷却（等效当日跳过），不计入普通熔断阈值（否则浪费两次
# 首试才 OPEN）。TTL 至目录刷新周期量级。

_LONG_COOLDOWN_TTL = 21600.0  # 6h ≈ 当日目录生命周期

_long_cooldown: dict[str, float] = {}


def _ckey(provider_id: str, model: str | None) -> str:
    """熔断/长冷却复合键：model 级粒度（Gap B），无 model 时退回 provider 键。"""
    return f"{provider_id}:{model}" if model else provider_id


def mark_long_cooldown(provider_id: str, model: str,
                       ttl: float | None = None) -> None:
    """403 门禁类永久性不可用 → 长冷却跳过（不入普通熔断计数）。"""
    _long_cooldown[_ckey(provider_id, model)] = (
        time.monotonic() + (ttl or _LONG_COOLDOWN_TTL)
    )
    logger.warning("[circuit] %s:%s long-cooldown (client-type gate / permanent unavailability)",
                   provider_id, model)


def is_long_cooldown(provider_id: str, model: str | None = None) -> bool:
    entry_until = _long_cooldown.get(_ckey(provider_id, model))
    if entry_until is None:
        return False
    if time.monotonic() > entry_until:
        _long_cooldown.pop(_ckey(provider_id, model), None)
        return False
    return True


def _circuit_state(provider_id: str, model: str | None = None) -> str:
    """熔断态查询。

    - model 给定 → 精确复合键 ``provider:model`` 的状态；
    - 缺省 → **聚合视图**：该 provider 名下（裸键 + 全部 model 分支）任一
      OPEN 即 OPEN，其次 HALF_OPEN，否则 CLOSED。行为锚以裸键断言
      provider 级语义，生产路径一律传 model 走精确粒度（Gap B 隔离）。
    """
    if model is not None:
        return _circuit.get(_ckey(provider_id, model), {}).get("state", "CLOSED")
    worst = "CLOSED"
    prefix = f"{provider_id}:"
    for key, entry in _circuit.items():
        if key != provider_id and not key.startswith(prefix):
            continue
        st = entry.get("state", "CLOSED")
        if st == "OPEN":
            return "OPEN"
        if st == "HALF_OPEN":
            worst = "HALF_OPEN"
    return worst


def _circuit_allow(provider_id: str, model: str | None = None) -> bool:
    """本次是否允许尝试；长冷却成员直接拒绝。OPEN 且未到 TTL → 跳过；
    HALF_OPEN 允许复探。

    round39 改进 (R143 改进): TTL 按错误类别分级 (entry.is_quota)
    - quota (429): _CIRCUIT_TTL_QUOTA (30min) — 与免费模型配额窗口对齐，避免锯齿复探
    - 其它 (5xx/timeout): _CIRCUIT_TTL (5min) — 短重试以恢复
    """
    if model and is_long_cooldown(provider_id, model):
        return False
    entry = _circuit.get(_ckey(provider_id, model))
    if entry is None:
        return True  # CLOSED
    now = time.monotonic()
    if entry["state"] == "OPEN":
        ttl = _CIRCUIT_TTL_QUOTA if entry.get("is_quota") else _CIRCUIT_TTL
        if now - entry["opened_at"] >= ttl:
            entry["state"] = "HALF_OPEN"
            entry["opened_at"] = now
            return True
        return False
    # CLOSED / HALF_OPEN 均允许
    return True


def _classify_permanent_error(exc: BaseException) -> bool:
    """round39 改进 (R143 改进): 检测永久性错误（不该熔断-复探-再撞-再熔断的循环）。

    永久性错误特征: HTTP 4xx + 特征文案 (model unavailable / not supported /
    not available in your country / credit insufficient)。这些错误复探无意义，
    应直接长冷却 + 摘除 catalog 候选。
    """
    if exc is None:
        return False
    resp = getattr(exc, "response", None)
    if resp is None:
        return False
    status = getattr(resp, "status_code", None)
    if status is None or status not in (400, 401, 403):
        return False
    body = ""
    try:
        body = (resp.text or "")[:2000]
    except Exception:
        pass
    if not body:
        return False
    for _code, pat in _PERMANENT_ERROR_PATTERNS:
        if _code != str(status):
            continue
        if __import__("re").search(pat, body, __import__("re").IGNORECASE):
            return True
    return False


def _circuit_record_failure(provider_id: str, is_quota_error: bool,
                            model: str | None = None,
                            exc: BaseException | None = None) -> None:
    """记录一次失败。
    - 429/FreeUsageLimitError（额度类，持久）→ 立即 OPEN，零复试（F9c）。
      TTL 30min (round39 改进；旧 5min 导致锯齿复探)。
    - 5xx/timeout（瞬态）→ 累计达阈值才 OPEN，保留有限重试。
    - 永久性错误（400/401/403 特征文案，如 "Model is unavailable"）→ 长冷却 +
      catalog 排除 (mark_excluded)；与 429 路径**不联动** llm_quota_gate.mark_exhausted()，
      避免单 provider 下某坏模型拖累其它可用模型 (round39 改进)。
    """
    # round39 改进: 永久性错误优先处理（不走普通熔断累计逻辑）
    if exc is not None and not is_quota_error and _classify_permanent_error(exc):
        mark_long_cooldown(provider_id, model or "", ttl=_LONG_COOLDOWN_TTL)
        try:
            from .model_catalog import model_catalog as _catalog
            _catalog.mark_excluded(provider_id, model or "")
        except Exception as _e:
            logger.warning("[circuit] mark_excluded failed for %s:%s: %s",
                           provider_id, model, _e)
        # 同时开普通熔断 OPEN 防止 TTL 后复探
        key = _ckey(provider_id, model)
        now = time.monotonic()
        entry = _circuit.get(key)
        if entry is None:
            entry = {"state": "CLOSED", "fail_count": 0, "opened_at": 0.0}
            _circuit[key] = entry
        entry["state"] = "OPEN"
        entry["opened_at"] = now
        entry["fail_count"] = 0
        entry["is_quota"] = True  # round39: 永久错误用 quota TTL
        logger.warning("[circuit] %s:%s permanent error → long-cooldown + excluded + OPEN",
                       provider_id, model or "<no-model>")
        return

    key = _ckey(provider_id, model)
    now = time.monotonic()
    entry = _circuit.get(key)
    if entry is None:
        entry = {"state": "CLOSED", "fail_count": 0, "opened_at": 0.0}
        _circuit[key] = entry
    if is_quota_error:
        entry["state"] = "OPEN"
        entry["opened_at"] = now
        entry["fail_count"] = 0
        entry["is_quota"] = True  # round39: TTL 分级标记
        logger.warning("[circuit] provider %s quota-exhausted → OPEN (skip until HALF_OPEN)", provider_id)
        # round39 改进: 单 provider/model 429 **不再**触发全局 llm_quota_gate.mark_exhausted()，
        # 避免整 provider 下的其它可用模型被连坐。原行为令 provider 内多模型轮换失效
        # (只有 quota 耗尽的模型需要冷却，其它模型仍可用)。全局暂停仅在
        # _circuit_record_failure_all_models_quota() 中由 caller 显式触发。
        return
    entry["fail_count"] = entry.get("fail_count", 0) + 1
    if entry["fail_count"] >= _CIRCUIT_FAIL_THRESHOLD:
        entry["state"] = "OPEN"
        entry["opened_at"] = now
        entry["is_quota"] = False  # 5xx 累计 OPEN，按 5min TTL 复探


def _circuit_record_success(provider_id: str, model: str | None = None) -> None:
    """记录一次成功：OPEN/HALF_OPEN → CLOSED，清零计数。"""
    key = _ckey(provider_id, model)
    entry = _circuit.get(key)
    if entry is None:
        return
    if entry["state"] in ("OPEN", "HALF_OPEN"):
        logger.info("[circuit] %s recovered → CLOSED", key)
    entry["state"] = "CLOSED"
    entry["fail_count"] = 0


# ── round35 §19.9 约束#4/验收#6: 中间层激活运行时标记（配额保护）────
# OpenRouter 免费档日额度紧（RPM 20 + 约 50 次/日），仅作 Zen 故障溢出层。
# client failover 循环真实尝试 openrouter 候选时打标；后台低价值 LLM 调用
# （hub/_news.py enrich_news_summaries 新闻摘要等）查询该标记决定跳过/降级，
# 防烧穿免费日额度挤占交互路径。TTL 对齐目录刷新周期——过期视为 Zen 已恢复。

_MIDDLE_LAYER_ACTIVE_TTL = 600.0

_middle_layer_active_until: float = 0.0


def mark_middle_layer_active(ttl: float | None = None) -> None:
    """client 循环尝试 openrouter 候选时调用：打标中间层已承流（TTL 内有效）。"""
    global _middle_layer_active_until
    _middle_layer_active_until = time.monotonic() + (
        ttl if ttl is not None else _MIDDLE_LAYER_ACTIVE_TTL
    )


def is_middle_layer_active() -> bool:
    """中间层是否处于激活窗口（近期有 openrouter 候选被真实尝试）。"""
    return time.monotonic() < _middle_layer_active_until


def _circuit_record_failure_all_models_quota(provider_id: str, models: list[str]) -> None:
    """round39 改进: 整 provider 下所有 model 都 429 → 触发全局 llm_quota_gate.mark_exhausted()。

    供 client failover 循环在「provider 全 model OPEN」时显式调用——单模型 429
    不应再触发全局暂停，但「provider 整层不可用」时仍需兜底暂停避免热循环。
    """
    if not models:
        return
    all_open = all(
        _circuit.get(_ckey(provider_id, m), {}).get("state") == "OPEN"
        for m in models
    )
    if all_open:
        llm_quota_gate.mark_exhausted()
        logger.warning(
            "[circuit] provider %s ALL %d models quota-exhausted → global pause",
            provider_id, len(models),
        )


def reset_circuit() -> None:
    """测试/运维用：清空熔断状态。"""
    global _middle_layer_active_until
    _circuit.clear()
    _long_cooldown.clear()
    # round25 R39: 同步复位跨任务配额门禁（单例 _last 跨测试持久，避免冷却污染）
    llm_quota_gate._last = 0.0
    llm_quota_gate._exhausted_until = 0.0
    _middle_layer_active_until = 0.0


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
