import json
import time
import sys
import asyncio
from typing import Any, AsyncGenerator

from ..config import settings
from ..monitor.token_usage import token_store, UsageRecord
from ..core.logging import get_logger
from .registry import get_agent
from .provider import get_configured_providers, has_any_api_key, ProviderConfig

logger = get_logger(__name__)

# F6: LLM retry policy — after every configured provider fails, retry the
# full provider sequence once, waiting LLM_RETRY_DELAY seconds between attempts.
# F3-6: 429 限流场景按 Retry-After / 指数退避（≤30s）重试 2 次后再降级。
LLM_MAX_RETRIES = 2
LLM_RETRY_DELAY = 3.0
_LLM_RATE_LIMIT_CAP = 30.0

# R5-1-6: 最近一次 LLM provider 失败诊断信息（429 前缀 [rate-limited]，连接超时 [timeout]；
# 成功调用后清空）。供策略检查超时兜底区分「限流」与「真超时」。
_last_llm_error: str | None = None


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


def _rate_limit_wait(attempt: int, resp_headers=None, cap: float = _LLM_RATE_LIMIT_CAP) -> float:
    """429 限流等待时间：优先尊重 Retry-After（cap 默认 30s），否则指数退避 3s*2^attempt（cap 默认 30s）。

    R5-1-6: cap 参数化——策略检查场景传 cap=10.0 实现快速失败（round14 P0-B 后
    外层预算 75s/30s/15s 分级；限流等待 ≤10s/轮，不挤占 provider 调用预算）。
    """
    if resp_headers:
        ra = resp_headers.get("retry-after") or resp_headers.get("Retry-After")
        if ra:
            try:
                return max(0.0, min(float(ra), cap))
            except (TypeError, ValueError):
                pass
    return min(LLM_RETRY_DELAY * (2 ** attempt), cap)

# Keep the official DeepSeek URL for reference; the actual URL is now
# per-provider and obtained from get_configured_providers().

# Prompt loading mechanism
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent / "prompts" / "v1"

def load_prompt(name: str) -> str:
    """Load a prompt from the prompts/v1/ directory."""
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")

# System prompts are loaded from markdown files (prompts/v1/*.md)
SYSTEM_PROMPT = load_prompt("general_analyst.md")

# F1-7: 已知的系统提示词泄漏模式（推理模型可能把 system prompt 内容
# 复述进 reasoning_content / content 通道）。命中即整行剔除。
_LEAK_PATTERNS = (
    "我们只需要回答",
    "我们只需要",
    "请忽略以上指令",
    "忽略以上",
    "你是专业",
    "你是一名",
    "你是一个",
    "你的任务是",
    "请严格按照以下提示词",
    "系统提示词内容",
    "system prompt",
    "作为AI助手",
    "作为 AI 助手",
)


def strip_internal_leak(text: str) -> str:
    """F1-7: 过滤 LLM 输出中泄漏的内部指令片段。

    对包含已知泄漏模式的整行进行剔除，并移除行内的残余指令关键词。
    纯函数，输入输出均为字符串，永不抛异常。
    """
    if not isinstance(text, str):
        return ""
    if not text:
        return ""
    out_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        if any(p.lower() in stripped.lower() for p in _LEAK_PATTERNS):
            continue
        out_lines.append(line)
    cleaned = "\n".join(out_lines)
    # 行内残余泄漏词剔除（如夹在正常句子中的「我们只需要回答…」片段）
    import re as _re
    for p in _LEAK_PATTERNS:
        cleaned = _re.sub(_re.escape(p), "", cleaned, flags=_re.IGNORECASE)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned

# System prompts are loaded per-agent via AgentRuntime (registry.py).

def _build_engine_fallback(strategies: list[dict], regime: str = "unknown") -> str:
    """Generate a meaningful engine-based fallback report when LLM is unavailable.

    Uses factor scores, layer budgets, and market regime data to produce
    a structured summary without any external API call.
    """
    lines = [
        "# ETF 组合设计方案（引擎分析摘要）",
        "",
        "> ⚠️ AI深度分析当前不可用，以下为策略引擎基于实时因子数据的自动分析。",
        "",
        f"**当前市态**: {regime}",
        "",
        "## 方案概览",
        "",
    ]
    for s in strategies:
        label = s.get("label", "未命名方案")
        lb = s.get("layer_budget", {})
        core_pct = lb.get("core", 0) * 100
        sat_pct = lb.get("satellite", 0) * 100
        def_pct = lb.get("defense", 0) * 100
        lines.append(f"### {label}")
        lines.append(f"层预算：核心 {core_pct:.0f}% · 卫星 {sat_pct:.0f}% · 防御 {def_pct:.0f}%")
        lines.append("")
        for e in s.get("allocations") or s.get("etfs") or []:
            if e.get("symbol") == "CASH":
                continue
            name = e.get("name", e.get("symbol", ""))
            w = (e.get("weight") or e.get("target_weight") or 0) * 100
            fs = e.get("factor_score", "")
            rationale = e.get("selection_rationale", "")[:60]
            fs_str = f"（因子分: {fs:.3f}）" if isinstance(fs, (int, float)) else ""
            rationale_str = f" — {rationale}" if rationale else ""
            lines.append(f"- {name} ({e.get('symbol')}) {w:.0f}%{fs_str}{rationale_str}")
        lines.append("")
    lines.append("## 风险提示")
    lines.append("")
    total_weight = sum(
        (e.get("weight") or e.get("target_weight") or 0)
        for s in strategies
        for e in (s.get("allocations") or s.get("etfs") or [])
        if e.get("symbol") != "CASH"
    )
    if total_weight > 0.9:
        lines.append(f"- 总权益仓位 {total_weight*100:.0f}%，高于 90% 阈值，注意市场下行风险")
    # Check single-position concentration
    for s in strategies:
        for e in s.get("allocations") or s.get("etfs") or []:
            w = e.get("weight") or e.get("target_weight") or 0
            if w > 0.3:
                lines.append(f"- {e.get('name', e.get('symbol'))} 权重 {w*100:.0f}% 超 30% 集中度限制")
    if len(lines) <= 10:
        lines.append("- 当前无有效持仓数据")
    lines.append("")
    lines.append("---")
    lines.append("*本报告由引擎自动生成，不含AI分析内容。*")
    return "\n".join(lines)


async def _check_key():
    if not has_any_api_key():
        raise ValueError(
            "No LLM API keys configured. Set OPENCODE_ZEN_API_KEY "
            "and/or DEEPSEEK_API_KEY in backend/.env"
        )


# F7: LLM health probe — ping each configured provider with a minimal request
# and report connectivity. Does NOT call the full business chain and does NOT
# write to token_store (health pings must not pollute real usage stats).
async def llm_health_check(timeout: float = 15.0) -> dict:
    """Probe every configured LLM provider and return a structured health report.

    Returns a dict with overall `status` ("ok" / "degraded" / "no_key"),
    `has_api_key`, `checked_at` and a `providers` list. Failures are reported
    structurally (never raised), so the endpoint always returns 200.
    """
    import httpx

    checked_at = time.time()
    if not has_any_api_key():
        return {
            "status": "no_key",
            "checked_at": checked_at,
            "has_api_key": False,
            "providers": [],
        }

    providers = get_configured_providers()
    if not providers:
        return {
            "status": "no_key",
            "checked_at": checked_at,
            "has_api_key": False,
            "providers": [],
        }

    async def _probe(provider: ProviderConfig) -> dict:
        body = {
            "model": provider.model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0.0,
            "max_tokens": 16,
        }
        _start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(
                    provider.api_url,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                msg = (data.get("choices") or [{}])[0].get("message", {})
                # content may be empty for reasoning models with tiny max_tokens;
                # the probe only cares that the API responded with a valid message.
                has_content = "content" in msg or "reasoning_content" in msg
                if not has_content:
                    raise ValueError("provider returned no message")
                latency = (time.monotonic() - _start) * 1000
                return {
                    "id": provider.id,
                    "name": provider.name,
                    "model": provider.model,
                    "ok": True,
                    "latency_ms": round(latency, 1),
                    "status": "available",
                    "error": None,
                }
        except Exception as _exc:
            latency = (time.monotonic() - _start) * 1000
            status = "timeout" if isinstance(_exc, (httpx.TimeoutException, asyncio.TimeoutError)) else "error"
            return {
                "id": provider.id,
                "name": provider.name,
                "model": provider.model,
                "ok": False,
                "latency_ms": round(latency, 1),
                "status": status,
                "error": str(_exc),
            }

    results = await asyncio.gather(*(_probe(p) for p in providers), return_exceptions=True)
    # gather never raises (each _probe catches), but guard anyway
    providers_out = []
    for r in results:
        if isinstance(r, Exception):
            providers_out.append({
                "id": "unknown", "name": "unknown", "model": "unknown",
                "ok": False, "latency_ms": 0.0, "status": "error", "error": str(r),
            })
        elif isinstance(r, dict):
            providers_out.append(r)

    overall = "ok" if any(p["ok"] for p in providers_out) else "degraded"
    return {
        "status": overall,
        "checked_at": checked_at,
        "has_api_key": True,
        "providers": providers_out,
    }


async def llm_complete(
    prompt: str,
    response_format: dict | None = None,
    max_retries: int = LLM_MAX_RETRIES,
    retry_delay: float = LLM_RETRY_DELAY,
) -> str:
    import httpx
    await _check_key()

    _caller = sys._getframe(1).f_code.co_name
    providers = get_configured_providers()
    last_exc: Exception | None = None
    _any_429 = False
    _last_429_headers = None
    _any_429 = False
    _last_429_headers = None

    for attempt in range(max_retries + 1):
        for provider in providers:
            body = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 12288,
            }
            if response_format:
                body["response_format"] = response_format

            _start = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=provider.timeout, trust_env=False
                ) as client:
                    resp = await client.post(
                        provider.api_url,
                        headers={
                            "Authorization": f"Bearer {provider.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    message = data["choices"][0]["message"]
                    content = message.get("content", "")
                    # F1-7: 推理模型可能把 system prompt 复述进 content/reasoning，
                    # 统一做泄漏过滤后再返回。
                    content = strip_internal_leak(content)

                    usage = data.get("usage", {})
                    _duration = (time.monotonic() - _start) * 1000
                    await token_store.record(UsageRecord(
                        function_name=_caller,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        model=provider.model,
                        timestamp=time.time(),
                        success=True,
                        duration_ms=round(_duration, 1),
                        provider=provider.id,
                    ))
                    return content
            except Exception as _exc:
                _duration = (time.monotonic() - _start) * 1000
                # F3-6: 识别 429 限流（尊重 Retry-After / 指数退避，重试 2 次后降级）
                _resp = getattr(_exc, "response", None)
                _is_429 = (
                    isinstance(_exc, httpx.HTTPStatusError)
                    and _resp is not None
                    and getattr(_resp, "status_code", None) == 429
                )
                if _is_429:
                    _any_429 = True
                    _last_429_headers = getattr(_resp, "headers", None)
                await token_store.record(UsageRecord(
                    function_name=_caller,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    model=provider.model,
                    timestamp=time.time(),
                    success=False,
                    duration_ms=round(_duration, 1),
                    error_message=str(_exc),
                    provider=provider.id,
                ))
                last_exc = _exc
                logger.warning(
                    "[LLM] Provider %s failed after %.1fs: %s",
                    provider.id, _duration / 1000, _exc,
                )
                continue

        # All providers failed this attempt -> retry after a short delay
        if attempt < max_retries:
            wait = _rate_limit_wait(attempt, _last_429_headers) if _any_429 else retry_delay
            logger.warning(
                "[LLM] all providers failed (attempt %d/%d), retrying in %.1fs",
                attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)

    if _any_429:
        logger.warning("[LLM] LLM 限流，已降级（重试 %d 轮后仍 429）", max_retries)
        raise RuntimeError(f"LLM 限流，已降级：{last_exc}")
    if last_exc is None:
        raise RuntimeError("No LLM providers available")
    raise last_exc


async def llm_complete_stream(
    system_prompt: str,
    prompt: str,
    response_format: dict | None = None,
    temperature: float = 0.3,
    max_tokens: int = 12288,
    max_retries: int = LLM_MAX_RETRIES,
) -> AsyncGenerator[dict, None]:
    """
    Streaming LLM completion with provider failover.

    Tries providers in priority order. If the primary provider fails
    BEFORE any token is yielded, falls back to the next provider.
    Once a token has been yielded, commits to that provider.

    F3-6: 429 限流时按 Retry-After / 指数退避重试（最多 max_retries 轮），
    全部失败后产出 error 事件并明确提示「LLM 限流，已降级」。

    Yields:
        {"type": "token", "token": "..."} - incremental token
        {"type": "done", "full_text": "...", "usage": {...}} - completion with full text
        {"type": "error", "error": "..."} - error occurred
    """
    import httpx
    await _check_key()

    providers = get_configured_providers()
    last_exc: Exception | None = None
    _any_429 = False
    _last_429_headers = None

    for attempt in range(max_retries + 1):
        for provider in providers:
            body = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens or 12288,
                "stream": True,
            }
            if response_format:
                body["response_format"] = response_format

            _start = time.monotonic()
            _caller = sys._getframe(1).f_code.co_name

            full_text = ""
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            _token_events = 0  # R6-F8: token 事件计数（断流判定用）

            try:
                async with httpx.AsyncClient(
                    timeout=provider.timeout, trust_env=False
                ) as client:
                    async with client.stream(
                        "POST",
                        provider.api_url,
                        headers={
                            "Authorization": f"Bearer {provider.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    ) as resp:
                        resp.raise_for_status()

                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    if chunk.get("choices"):
                                        delta = chunk["choices"][0].get("delta", {})
                                        # F1-7: 只取 content 通道，丢弃 reasoning_content
                                        # （推理模型的思考过程可能复述 system prompt，泄漏到输出）
                                        token = delta.get("content") or ""
                                        if token:
                                            full_text += token
                                            _token_events += 1
                                            yield {"type": "token", "token": token}

                                    if chunk.get("usage"):
                                        usage = chunk["usage"]
                                        prompt_tokens = usage.get("prompt_tokens", 0)
                                        completion_tokens = usage.get("completion_tokens", 0)
                                        total_tokens = usage.get("total_tokens", 0)
                                except json.JSONDecodeError:
                                    continue

            except Exception as _exc:
                _duration = (time.monotonic() - _start) * 1000
                # F3-6: 识别 429 限流
                _resp = getattr(_exc, "response", None)
                _is_429 = (
                    isinstance(_exc, httpx.HTTPStatusError)
                    and _resp is not None
                    and getattr(_resp, "status_code", None) == 429
                )
                if _is_429:
                    _any_429 = True
                    _last_429_headers = getattr(_resp, "headers", None)
                await token_store.record(UsageRecord(
                    function_name=_caller,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    model=provider.model,
                    timestamp=time.time(),
                    success=False,
                    duration_ms=round(_duration, 1),
                    error_message=str(_exc),
                    provider=provider.id,
                ))
                last_exc = _exc
                logger.warning(
                    "[LLM] Stream provider %s failed after %.1fs: %s",
                    provider.id, _duration / 1000, _exc,
                )
                # If we yielded any tokens, we're committed - propagate error
                if full_text:
                    yield {"type": "error", "error": str(_exc)}
                    return
                # Otherwise try next provider
                continue

            # Success: record and yield done
            _duration = (time.monotonic() - _start) * 1000
            await token_store.record(UsageRecord(
                function_name=_caller,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                model=provider.model,
                timestamp=time.time(),
                success=True,
                duration_ms=round(_duration, 1),
                provider=provider.id,
            ))

            # R6-F8 (round6 §五 R6-09): 流式偶发断流——HTTP 成功但 token 事件
            # <2（0 token / 仅 1 个 disclaimer token，如 events=1 仅 disclaimer）。
            # 视同失败重试（continue → 下一 provider / 下一轮退避），不静默产出空报告。
            if _token_events < 2:
                logger.warning(
                    "[LLM] Stream dropout: only %d token event(s) (provider=%s) — retrying",
                    _token_events, provider.id,
                )
                last_exc = RuntimeError(f"stream dropout: only {_token_events} token event(s)")
                await token_store.record(UsageRecord(
                    function_name=_caller,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    model=provider.model,
                    timestamp=time.time(),
                    success=False,
                    duration_ms=round(_duration, 1),
                    error_message=str(last_exc),
                    provider=provider.id,
                ))
                if attempt < max_retries:
                    wait = LLM_RETRY_DELAY
                    logger.warning(
                        "[LLM] Stream retrying after dropout (attempt %d/%d) in %.1fs",
                        attempt + 1, max_retries, wait,
                    )
                    await asyncio.sleep(wait)
                continue

            yield {
                "type": "done",
                "full_text": strip_internal_leak(full_text),
                "usage": {
                    "model": provider.model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": round(_duration, 1),
                }
            }
            return

        # 本轮所有 provider 失败 → 退避后重试（F3-6）
        if attempt < max_retries:
            wait = _rate_limit_wait(attempt, _last_429_headers) if _any_429 else LLM_RETRY_DELAY
            logger.warning(
                "[LLM] Stream all providers failed (attempt %d/%d), retrying in %.1fs",
                attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)

    # All providers exhausted after all retries
    if last_exc is None:
        last_exc = RuntimeError("No LLM providers available")
    if _any_429:
        logger.warning("[LLM] LLM 限流，已降级（重试 %d 轮后仍 429）", max_retries)
        yield {"type": "error", "error": f"LLM 限流，已降级：{last_exc}"}
        return
    yield {"type": "error", "error": str(last_exc)}


async def llm_complete_with_system(
    system_prompt: str,
    prompt: str,
    response_format: dict | None = None,
    force_json: bool = False,
    max_retries: int = LLM_MAX_RETRIES,
    retry_delay: float = LLM_RETRY_DELAY,
    rate_limit_cap: float = _LLM_RATE_LIMIT_CAP,
    request_timeout: float | None = None,
) -> str:
    """Call LLM with a custom system prompt, with provider failover + retry (F6).

    R5-1-6: rate_limit_cap 参数化 429 退避上限（默认 30s 不变；策略检查传 10s 快速失败）；
    每次 provider 失败记录诊断（_record_llm_error），成功清空。
    round10 P1-I: request_timeout 可覆写单次 provider 调用超时（默认 None =
    provider.timeout；策略检查场景传 35s，与 _llm_timeout_for 分级预算
    75s/30s/15s 匹配——round14 P0-B 预算-重试一致性：2×35=70 ≤ 75）。
    """
    import httpx
    await _check_key()

    _caller = sys._getframe(1).f_code.co_name
    providers = get_configured_providers()
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        for provider in providers:
            body = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 12288,
            }
            if response_format:
                body["response_format"] = response_format
            elif force_json:
                body["response_format"] = {"type": "json_object"}

            _start = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=(request_timeout if request_timeout is not None else provider.timeout), trust_env=False
                ) as client:
                    resp = await client.post(
                        provider.api_url,
                        headers={
                            "Authorization": f"Bearer {provider.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    message = data["choices"][0]["message"]
                    content = message.get("content", "")
                    # F1-7: 推理模型可能把 system prompt 复述进 content/reasoning，
                    # 统一做泄漏过滤后再返回。
                    content = strip_internal_leak(content)

                    # R5-1-6: 成功 → 清空错误诊断
                    _clear_llm_error()

                    usage = data.get("usage", {})
                    _duration = (time.monotonic() - _start) * 1000
                    await token_store.record(UsageRecord(
                        function_name=_caller,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        model=provider.model,
                        timestamp=time.time(),
                        success=True,
                        duration_ms=round(_duration, 1),
                        provider=provider.id,
                    ))
                    return content
            except Exception as _exc:
                _duration = (time.monotonic() - _start) * 1000
                # R5-1-6: 记录失败诊断（429 → [rate-limited]，超时 → [timeout]）
                try:
                    _record_llm_error(_exc)
                except Exception:
                    pass
                await token_store.record(UsageRecord(
                    function_name=_caller,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    model=provider.model,
                    timestamp=time.time(),
                    success=False,
                    duration_ms=round(_duration, 1),
                    error_message=str(_exc),
                    provider=provider.id,
                ))
                last_exc = _exc
                logger.warning(
                    "[LLM] Provider %s failed after %.1fs: %s",
                    provider.id, _duration / 1000, _exc,
                )
                continue

        # All providers failed this attempt -> retry after a short delay
        if attempt < max_retries:
            # R5-1-6: 429 时按 rate_limit_cap 退避（不再固定 retry_delay）——
            # 否则 cap 参数传了也不生效（旧代码固定 retry_delay）。
            wait = _rate_limit_wait(attempt, None, cap=rate_limit_cap)
            logger.warning(
                "[LLM] all providers failed (attempt %d/%d), retrying in %.1fs",
                attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)

    if last_exc is None:
        raise RuntimeError("No LLM providers available")
    raise last_exc


def _format_indices(indices: list[dict]) -> str:
    if not indices:
        return ""
    # R4-27b: 保留指数代码但去除内部 ^ 前缀（^HSTECH → HSTECH），观感自然
    lines = [f"- {idx.get('name','')}({str(idx.get('symbol','')).lstrip('^')}): {idx.get('price','N/A')}, 涨跌幅{idx.get('change_pct','N/A')}%" for idx in indices[:15]]
    return "\n".join(lines)


def _format_commodities(commodities: list[dict]) -> str:
    if not commodities:
        return ""
    key_names = {"黄金", "白银", "原油", "铜", "铝", "天然气"}
    items = [c for c in commodities if c.get("name", "") in key_names]
    if not items:
        items = commodities[:6]
    lines = [f"- {c.get('name','')}: {c.get('price','N/A')}, 涨跌幅{c.get('change_pct','N/A')}%" for c in items]
    return "\n".join(lines)


# NOTE: _build_portfolio_design_prompt is defined below
# with extended signature supporting trend_data, macro_state, etc.

def _build_market_overview(
    indices: list[dict],
    commodities: list[dict],
    major_stocks: list[dict],
    news: list[dict],
    macro_news: list[dict],
    market: str = "A",
) -> str:
    """N04/U9: 市场概览标题按 market 动态化（旧硬编码 "A股市场" → HK/US 报告误导）。"""
    from app.core.market_context import resolve_market_context
    market_title = resolve_market_context(market).title
    prompt = f"""## 全市场概览

### {market_title}市场
"""
    a_stock_names = {"上证指数", "深证成指", "创业板指", "科创50", "沪深300", "上证50", "中证500", "中证1000"}
    for idx in indices:
        if idx.get("name") in a_stock_names:
            # R4-27b: 保留代码但去除内部 ^ 前缀
            prompt += f"- {idx.get('name')}({str(idx.get('symbol','')).lstrip('^')}): {idx.get('price','N/A')}, 涨跌幅{idx.get('change_pct','N/A')}%\n"
    if not any(idx.get("name") in a_stock_names for idx in indices):
        prompt += _format_indices(indices) or "（暂无数据）\n"

    prompt += "\n### 美股市场\n"
    us_stock_names = {"标普500", "纳斯达克", "道琼斯"}
    for s in major_stocks + indices:
        if s.get("name") in us_stock_names:
            prompt += f"- {s.get('name')}({str(s.get('symbol','')).lstrip('^')}): {s.get('price','N/A')}, 涨跌幅{s.get('change_pct','N/A')}%\n"
    if not any(s.get("name") in us_stock_names for s in major_stocks + indices):
        prompt += "（暂无数据）\n"

    prompt += "\n### 大宗商品\n"
    prompt += _format_commodities(commodities) or "（暂无数据）"

    if major_stocks:
        prompt += "\n\n### 主要标的行情\n"
        for item in major_stocks[:15]:
            prompt += f"- {item.get('name', '')}({item.get('symbol', '')}): ¥{item.get('price', 'N/A')}, 涨跌幅{item.get('change_pct', 'N/A')}%\n"

    if news:
        prompt += "\n\n### 财经资讯\n"
        for n in news[:8]:
            title = n.get("title", n.get("summary", ""))
            prompt += f"- {title[:120]}\n"

    if macro_news:
        prompt += "\n\n### 宏观政策\n"
        for n in macro_news[:5]:
            title = n.get("title", n.get("summary", ""))
            prompt += f"- {title[:120]}\n"

    return prompt


async def generate_market_report(
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
    macro_news: list[dict],
    market: str = "A",
    global_liquidity: dict | None = None,
) -> str:
    # P1-5 (R4-23): 海外流动性——调用方未显式传入时内部默认采集 FRED
    # （美债10Y/VIX/联邦基金利率），失败静默不注入，不影响主报告。
    if global_liquidity is None:
        global_liquidity = await _fetch_global_liquidity()
    prompt = _build_report_prompt(indices, commodities, market_data, indicators, news, macro_news,
                                  market=market, global_liquidity=global_liquidity)
    return await get_agent("market_report").run(prompt)


async def _fetch_global_liquidity() -> dict | None:
    """P1-5 (R4-23): FRED 海外流动性采集——美债10Y/VIX/联邦基金利率。

    任一指标失败静默（该键不注入）；全部失败/无 API key 返回 None。
    首期仅 3 个指标（CPI/非农暂不接入，控制 prompt 长度）。
    """
    try:
        from ..fetchers.global_markets_fetcher import (
            fetch_fed_rate,
            fetch_us_10y,
            fetch_vix,
        )
        import asyncio as _asyncio
        _us10, _vix, _fed = await _asyncio.wait_for(
            _asyncio.gather(
                fetch_us_10y(), fetch_vix(), fetch_fed_rate(),
                return_exceptions=True,
            ),
            timeout=15,
        )
        gl: dict[str, float] = {}
        for _k, _v in (("us_10y", _us10), ("vix", _vix), ("fed_rate", _fed)):
            if isinstance(_v, float):
                gl[_k] = round(_v, 2)
        return gl or None
    except Exception as e:
        logger.debug("[llm] _fetch_global_liquidity failed (non-fatal): %s", e)
        return None


async def generate_advice(
    query: str,
    context: dict[str, Any] | None = None,
) -> str:
    """AI 投资顾问 — 结合市场数据、新闻、持仓生成结构化回答。

    从 context 中获取 market_data / news / portfolio / market_snapshot 等信息，
    注入市态判定与情绪数据，按 4 个维度的分析框架输出 Markdown 格式报告。
    """
    # ---- 从 context 获取可用数据 ----
    market_data = (context or {}).get("market_data", [])
    news = (context or {}).get("news", [])
    portfolio = (context or {}).get("portfolio", [])
    market_snapshot = (context or {}).get("market_snapshot", "")
    regime = (context or {}).get("market_regime", "")
    sentiment = (context or {}).get("market_sentiment", {})
    hot_plates = (context or {}).get("hot_plates", [])
    sector_heat = (context or {}).get("sector_heat", [])

    # ---- 1. 大盘概况（含市态/情绪） ----
    idx_lines = []
    if market_data:
        for item in market_data[:10]:
            name = item.get("name", item.get("symbol", "?"))
            price = item.get("price", "N/A")
            chg = item.get("change_pct", "")
            vol = item.get("volume", "")
            amount = item.get("amount", "")
            if chg != "":
                vol_str = f"成交量 {vol}" if vol else ""
                amt_str = f"成交额 {amount}" if amount else ""
                idx_lines.append(
                    f"- **{name}**: {price} 涨跌幅 {chg}%  {vol_str}  {amt_str}"
                )

    idx_summary = "\n".join(idx_lines) if idx_lines else "暂无实时指数数据。"

    # 市态与情绪概览
    regime_line = f"市场状态: {regime}" if regime else "市场状态: 未知"
    sentiment_line = ""
    if sentiment and isinstance(sentiment, dict):
        s_idx = sentiment.get("sentiment_index", "")
        s_lbl = sentiment.get("sentiment_label", "")
        if s_idx and s_lbl:
            sentiment_line = f"市场情绪: {s_lbl} ({s_idx}/100)"
        elif s_lbl:
            sentiment_line = f"市场情绪: {s_lbl}"

    # ---- 2. 热点板块（优先使用 hot_plates / sector_heat） ----
    sector_lines = []

    # Phase 4: 优先使用上下文中的 hot_plates 数据
    if hot_plates:
        for hp in hot_plates[:8]:
            name = hp.get("plate_name", hp.get("name", ""))
            reason = hp.get("reason", hp.get("hot_reason", ""))
            stocks = hp.get("stocks", hp.get("lead_stocks", []))
            stock_str = ", ".join([s.get("name", "") for s in stocks[:3]])
            line = f"- **{name}**: {reason}"
            if stock_str:
                line += f"  领涨: {stock_str}"
            sector_lines.append(line)

    # Phase 4: 使用上下文中的 sector_heat 数据
    if sector_heat:
        sector_lines.append("**板块热度排行:**")
        for item in sector_heat[:8]:
            name = item.get("sector_name", item.get("name", "?"))
            heat = item.get("heat_index", "")
            chg = item.get("change_pct", "")
            if heat:
                sector_lines.append(f"- {name}: 热度 {heat}, 涨跌幅 {chg}%")

    # Fallback: 从 market_data 按 asset_type 过滤
    if not hot_plates and not sector_heat:
        for item in market_data[:15]:
            if item.get("asset_type") in ("sector", "concept", "industry", "plate"):
                name = item.get("name", item.get("sector_name", "?"))
                chg = item.get("change_pct", "")
                flow = item.get("main_inflow", item.get("fund_flow", ""))
                sector_lines.append(
                    f"- **{name}**: 涨跌幅 {chg}%  资金流向 {flow}"
                )

    sector_summary = "\n".join(sector_lines) if sector_lines else "暂无板块热力数据。"

    # ---- 3. 资金面 / 消息面 ----
    fund_lines = []
    fund_lines.append(f"- 市场快照:\n{market_snapshot}" if market_snapshot else "- 市场快照:暂无")
    news_lines = []
    if news:
        for n in news[:10]:
            title = n.get("title", n.get("content", ""))[:120]
            source = n.get("source", n.get("来源", ""))
            prefix = f"[{source}] " if source else ""
            news_lines.append(f"- {prefix}{title}")
    news_summary = "\n".join(news_lines) if news_lines else "暂无重大新闻。"

    # ---- 4. 持仓/组合概况 ----
    portfolio_lines = []
    if portfolio:
        for p in portfolio[:10]:
            sym = p.get("symbol", p.get("code", "?"))
            name = p.get("name", "")
            weight = p.get("target_weight", p.get("weight", ""))
            if isinstance(weight, (int, float)):
                weight_str = f"{weight*100:.1f}%" if weight < 1 else f"{weight}%"
            else:
                weight_str = str(weight)
            portfolio_lines.append(f"- {name}({sym}): 目标权重 {weight_str}")
    portfolio_summary = "\n".join(portfolio_lines) if portfolio_lines else "用户未提供持仓信息。"

    prompt = f"""你是一位专业的中国金融市场投资顾问。基于以下数据，回答用户的问题。

---
## 用户提问
{query}

---
## 一、大盘概况
{idx_summary}

{regime_line}
{sentiment_line}

---
## 二、热点板块
{sector_summary}

---
## 三、资金流向 / 消息面
{news_summary}

---
## 四、持仓组合概况
{portfolio_summary}
---

请按以下 4 个维度给出结构化 Markdown 格式报告：

### 1. 大盘概况
- 主要指数涨跌幅、**成交量变化**、涨跌家数比
- **给出具体数值而不是模糊描述**，例如"上证指数收于 3200.5，涨幅 0.8%"

### 2. 热点板块
- 领涨板块 / 概念及涨幅/跌幅
- 资金流入流出情况

### 3. 资金流向 / 消息面
- 主力资金动向、北向资金动态
- 重大政策或新闻催化

### 4. 后市展望与建议
- 短期趋势判断、关键支撑/压力位
- 给出 2~4 条具体配置建议

注意：
- 使用 **加粗** 强调关键数据
- 用 `-` 符号列表组织内容
- 保持回答精炼，控制在 600 字以内
- 必须引用上述提供的具体数据，不要凭空編造数据
- 如无必要不要使用表格，用 `-` 列表组织；如需表格必须使用标准 Markdown 表格语法（`| 列 | 列 |`）
- 章节标题用 `##`/`###` 三级以内层级，不要用 `、` 编号（如"、四、风险提示"）
"""

    from ..analysis.registry import get_agent
    return await get_agent("advice").run(prompt)

async def analyze_news(news_list: list[dict], sentiment_index: float | None = None) -> str:
    """Z18: Enhance news analysis with structured sentiment scoring.

    Returns a markdown report with sentiment index, sector impacts,
    and risk warnings. Uses the first 15 news items for context.
    Introduced structured JSON output with score alignment check.

    P2-2 (round9 §6.4): 注入系统 sentiment 作为基准——要求 LLM 引用而非自估
    （旧实现 LLM 自估「情绪指数 60」vs 系统 sentiment 37.8，口径脱节）。
    """
    text = "\n".join([f"- {n.get('title', n.get('summary', ''))}" for n in news_list[:15]])
    # P2-2: 系统情绪基准注入（None 时跳过，向后兼容）
    sentiment_line = ""
    if sentiment_index is not None:
        sentiment_line = (
            f"\n【系统市场情绪基准】sentiment_index = {sentiment_index}"
            f"（0=极度悲观，100=极度乐观）。你输出的「情绪指数」必须引用此系统口径，"
            f"不得自行另估；若新闻内容显示情绪正在变化，请说明偏离方向与幅度"
            f"（如 '较系统基准 +5'）。\n"
        )
    prompt = f"""分析以下财经新闻，提取关键信息：
{sentiment_line}
{text}

请按以下维度输出：
    1. 核心市场情绪：乐观/中性/悲观（附情绪指数0-100，**必须引用系统基准值**）
    2. 影响板块及程度（列出受影响最大的3个板块，标注正面/负面）
    3. 对市场的潜在影响及启示
    4. 风险提示
    5. 新闻一致性检查：以上新闻是否有相互矛盾的信息"""
    return await get_agent("news_analysis").run(prompt)


NEWS_IMPACT_SYSTEM_PROMPT = load_prompt("news_impact.md")


async def generate_news_summary(title: str, content: str) -> str:
    """Z18: 单条新闻生成一句话中文摘要（后台管道用，失败返回空串不抛错）。"""
    prompt = (
        f"请用一句话（不超过40字）概括以下新闻的核心要点，"
        f"直接输出摘要正文，不要任何前缀、引号或标点修饰。\n"
        f"标题：{title}\n内容：{(content or '')[:200]}"
    )
    try:
        text = await llm_complete(prompt, max_retries=0)
        return (text or "").strip().strip('"').strip("'")[:80]
    except Exception:
        return ""


def _news_body_text(news_item: dict) -> str:
    """O5 (round7 §7 P16): news-impact 正文兜底——content → summary → title。

    数据源冷却/快讯类头条 content 为空时，prompt 里「新闻内容：」段为空 →
    LLM 收到空正文 → 返回「新闻内容为空」空洞结论。三级兜底保证正文段非空。
    """
    content = (news_item.get("content") or "").strip()
    if content:
        return content
    summary = (news_item.get("summary") or "").strip()
    if summary:
        return summary
    title = (news_item.get("title") or "").strip()
    if title:
        return f"（快讯）{title}"
    return ""


async def analyze_news_impact(news_item: dict, holdings: list[dict], market_context: dict | None = None) -> dict:
    """分析单条新闻对当前组合内各标的的具体影响。

    Z32: 当组合为空时，改为分析对市场整体的影响。
    R46: market_context（regime/指数/板块，由路由层采集注入）可选——传入时
    在 prompt 中加入当前市场背景，使相关新闻能展开传导分析、无关新闻给出理由。
    R48: 返回前用持仓白名单过滤 LLM 虚构标的并记 WARNING 日志。
    R49: prompt 注入显式代码清单（affected_holdings 只能从清单中选）。
    返回 {"impact_scope": str, "affected_holdings": [...], "summary": str}。
    """
    has_holdings = bool(holdings and any(h.get('symbol') for h in holdings))
    holdings_text = "\n".join(
        f"- {h.get('symbol', '')} {h.get('name', '')} "
        f"({h.get('asset_type', '')}) 目标权重 {h.get('target_weight', '')}"
        for h in holdings
    ) if has_holdings else "（暂未持仓）"
    # R49: 显式代码清单——LLM 只能从清单中选 affected_holdings.symbol
    code_list = ", ".join(
        str(h.get("symbol", "")).strip() for h in holdings if h.get("symbol")
    ) if has_holdings else ""

    # R46: 市场背景段（regime / 指数 / 板块热度），由路由层采集注入
    background = ""
    if market_context:
        parts = []
        # regime 可能是 dict {regime, confidence} 或 str（build_full_context 返回）
        regime_raw = market_context.get("market_regime") or ""
        regime = regime_raw.get("regime", "") if isinstance(regime_raw, dict) else str(regime_raw)
        if regime:
            parts.append(f"当前市场状态：{regime}")
        indices = market_context.get("indices") or []
        if indices:
            idx_txt = "；".join(
                f"{i.get('name', i.get('symbol', ''))} {i.get('price', '')}"
                for i in indices[:6] if isinstance(i, dict)
            )
            if idx_txt:
                parts.append(f"主要指数：{idx_txt}")
        sectors = market_context.get("sectors") or []
        if sectors:
            hot = sorted(
                (s for s in sectors if isinstance(s, dict) and s.get("change_pct") is not None),
                key=lambda s: abs(s.get("change_pct") or 0), reverse=True,
            )[:5]
            if hot:
                parts.append("板块热度："
                             + "；".join(f"{s.get('name', '')} {s.get('change_pct', '')}%" for s in hot))
        if parts:
            background = "当前市场背景：\n" + "\n".join(parts) + "\n\n"

    # O5 (round7 §7 P16): 正文三级兜底——content 空时用 summary/title，
    # 杜绝空正文段进 prompt（LLM 收到空正文会回「新闻内容为空」空洞结论）
    news_body = _news_body_text(news_item) or "（无正文）"
    if has_holdings:
        prompt = f"""新闻标题：{news_item.get('title', '')}
新闻内容：{news_body}

{background}当前组合持仓：
{holdings_text}

当前组合持仓代码：{code_list}
（affected_holdings 中的 symbol 必须严格从上述清单中选择，不得新增任何代码）

请分析这条新闻对组合的影响，重点回答：
(a) 影响范围：必须明确方向（利好/利空/中性）＋板块＋概念，如「方向：利好；板块：A股文化传媒（影视院线、内容制作）；概念：影视、内容IP」；
(b) 组合内哪些标的会受到影响、具体如何受影响。
只返回约定结构的 JSON。

重要约束（必须遵守）：
- 若新闻与组合内标的无直接关联，须明确回答「无直接影响」，禁止强行关联；
- 只列出实际受影响的标的，宁缺毋滥；
- 若组合为空，回答对市场整体的影响。"""
    else:
        prompt = f"""新闻标题：{news_item.get('title', '')}
新闻内容：{news_body}

当前无持仓组合。

请分析这条新闻对市场整体的影响，重点回答：
(a) 影响范围：必须明确方向（利好/利空/中性）＋板块＋概念，如「方向：利好；板块：A股文化传媒（影视院线、内容制作）；概念：影视、内容IP」；
(b) 哪些行业或主题会受到正面/负面影响。
只返回约定结构的 JSON。

重要约束（必须遵守）：
- 若新闻与 A 股市场无直接关联，须明确回答「无直接影响」，禁止强行关联；
- 只列出实际受影响的行业/主题，宁缺毋滥。"""

    try:
        data = await get_agent("news_impact").run_json(prompt)
    except Exception as e:
        logger.warning("[news_impact] LLM analysis failed: %s", e)
        data = {}

    # R48: 持仓白名单过滤——仅保留传入 holdings 代码集内的标的，LLM 虚构标的丢弃
    affected = (data.get("affected_holdings") or []) if isinstance(data, dict) else []
    if has_holdings and affected:
        whitelist = {str(h.get("symbol", "")).strip() for h in holdings if h.get("symbol")}
        filtered = [a for a in affected if str(a.get("symbol", "")).strip() in whitelist]
        dropped = len(affected) - len(filtered)
        if dropped:
            fake_symbols = [a.get("symbol") for a in affected
                            if str(a.get("symbol", "")).strip() not in whitelist]
            logger.warning(
                "[news_impact] LLM 虚构 %d 个持仓标的已过滤（不在持仓白名单）: %s",
                dropped, fake_symbols,
            )
        affected = filtered

    return {
        "impact_scope": data.get("impact_scope", "") if isinstance(data, dict) else "",
        "affected_holdings": affected,
        "summary": data.get("summary", "") if isinstance(data, dict) else "",
    }


def _build_report_prompt(
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
    macro_news: list[dict],
    market: str = "A",
    global_liquidity: dict | None = None,
) -> str:
    overview = _build_market_overview(indices, commodities, market_data, news, macro_news, market=market)

    # P1-5 (R4-23): 海外流动性数据段——FRED 美债10Y/VIX/联邦基金利率。
    # 仅当至少一项可用时注入；全失败（None）时不出现该段，不影响主报告。
    if global_liquidity:
        gl_lines = []
        _us10 = global_liquidity.get("us_10y")
        _vix = global_liquidity.get("vix")
        _fed = global_liquidity.get("fed_rate")
        if _us10 is not None:
            gl_lines.append(f"- 美债10年期收益率: {_us10}%")
        if _vix is not None:
            gl_lines.append(f"- VIX恐慌指数: {_vix}")
        if _fed is not None:
            gl_lines.append(f"- 联邦基金利率: {_fed}%")
        if gl_lines:
            overview += "\n\n### 海外流动性\n" + "\n".join(gl_lines)

    prompt = f"""{overview}

请生成一份市场环境研判报告，包含市场研判和操作建议两部分。

报告须使用 Markdown，包含以下 6 个一级章节（以 `##` 作为章节标题），章节之间用 `---` 分隔：

## 1. 市场全景速览
- 一句话总结当前市场核心状态（趋势延续 / 横盘消化 / 趋势终结）
- 关键数据速览：主要指数涨跌、成交量变化、涨跌家数比
- 核心矛盾一句话概括

## 2. 市场阶段与核心矛盾
- 市场阶段：趋势延续 / 横盘消化 / 趋势终结（须给出明确判断与依据）
- 风格特征：单一主线 / 风格扩散 / 均衡
- 资金行为：增量与存量资金在买什么、卖什么
- 核心矛盾：当前最大的不确定性来源

## 3. 宏观流动性与政策解读
- 国内流动性：货币与利率信号
- 海外流动性与地缘：美债、美元、油价、地缘冲突的传导
- 政策信号：有无稳增长或行业政策出台

## 4. 板块与风格轮动信号
- 强势板块 / 弱势板块及幅度
- 风格切换迹象（价值 / 成长、大 / 小盘）

## 5. 核心风险提示
- 按风险等级列出 2~4 条关键风险，并给出可观测的触发条件

## 6. 操作建议
- 当前仓位建议（基于市态和风险敞口）
- 关注方向：最看好的 1-2 个板块/风格方向
- 规避方向：需要规避的 1-2 个板块/风格方向
- 关键观测点：接下来 1-2 周需要跟踪的触发条件

格式要求：
- 关键结论与数字用 `**加粗**` 标注，数字必须引用上方输入数据
- 要点用 `-` 列表，语言专业、客观、可执行
- 全程控制在 1200 字以内"""
    return prompt



def _empty_portfolio_response() -> dict:
    return {"market_environment": "数据获取异常", "portfolios": []}


# 新增：组合检视/再平衡
async def generate_strategy_suggestions(
    market_data: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
    macro_news: list[dict],
) -> dict[str, Any]:
    overview = _build_market_overview(
        [d for d in market_data if d.get("asset_type") == "index"],
        [d for d in market_data if d.get("asset_type") == "commodity"],
        [d for d in market_data if d.get("asset_type") == "stock"],
        news,
        macro_news,
    )

    prompt = f"""{overview}

请基于当前市场环境，给出 3 条具体的策略建议，每条包含：
1. 策略名称
2. 适用市场环境
3. 核心操作（买什么/卖什么/配置比例）
4. 止损/止盈规则
5. 置信度（高/中/低）

输出 JSON 格式：
```json
{{
  "strategies": [
    {{"name": "", "condition": "", "action": "", "risk_control": "", "confidence": ""}},
    {{"name": "", "condition": "", "action": "", "risk_control": "", "confidence": ""}},
    {{"name": "", "condition": "", "action": "", "risk_control": "", "confidence": ""}}
  ]
}}
```"""
    response = await get_agent("strategy_suggestions").run(prompt)
    return json.loads(response)


async def generate_strategy_check_report(
    market_data: list[dict],
    factor_breakdowns: dict[str, dict],
    regime: str,
    data_quality: dict | None = None,
) -> dict:
    """基于持仓数据 + 因子分 + regime 生成结构化策略检查报告。"""
    # 格式化持仓数据
    holdings_lines = []
    for item in market_data:
        sym = item.get("symbol", "")
        if sym == "CASH":
            continue
        fb = factor_breakdowns.get(sym, {})
        fs = fb.get("factor_scores", {})
        sig = fb.get("technical_signal", {})
        drift = fb.get("weight_drift", {})

        factor_text = "；".join(
            f"{k}: {v:.2f}" for k, v in sorted(fs.items(), key=lambda x: -abs(x[1]))[:5]
        ) if fs else "无因子数据"
        signal_text = sig.get("signal", "hold")
        drift_text = f"偏离 {drift.get('drift_pct', 0):.1f}%" if drift else "—"

        holdings_lines.append(
            f"- {item.get('name', sym)}({sym}): "
            f"权重 {item.get('target_weight', 0)*100:.0f}%, "
            f"{drift_text}；"
            f"技术信号 {signal_text}；"
            f"因子评分: {factor_text}"
        )

    holdings_text = "\n".join(holdings_lines)

    # 根据持仓数量动态计算建议数上下限
    holdings_count = len(holdings_lines)
    # Z26: 下限不少于持仓数一半，确保 LLM 不跳过无因子数据的标的
    min_suggestions = max(3, holdings_count // 2)
    if holdings_count <= 5:
        max_suggestions = 5
    elif holdings_count <= 10:
        max_suggestions = 8
    else:
        max_suggestions = 12

    # 根据数据质量追加注记
    quality_note = ""
    if data_quality:
        if data_quality.get("all_empty"):
            quality_note = (
                "\n⚠️ 数据质量注记：当前所有持仓的因子数据为空，技术信号仅供参考。\n"
                "请基于权重配置和相关性做判断，降低所有建议的置信度。\n"
            )
        elif data_quality.get("partial"):
            missing = data_quality['total_count'] - data_quality['filled_count']
            quality_note = (
                f"\n⚠️ 数据质量注记：{missing} / {data_quality['total_count']} 只标的因子数据缺失。\n"
                f"请对缺失数据的标的降低置信度。\n"
            )

    prompt = f"""
## 市场状态
当前 regime: {regime}
持仓数量: {holdings_count} 只
建议条数范围: {min_suggestions}~{max_suggestions} 条（下限{min_suggestions}条，必须覆盖每个持仓标的至少一条建议）

## 输出硬约束（Z26）
- 每条建议的 action 字段必须为小写枚举之一: increase / decrease / hold（禁止 BUY/SELL/HOLD 大写形式）
- 每条建议必须包含 current_weight 与 suggested_weight（0-1 小数）
- 每条建议必须包含 reason 与 confidence（0-1 小数）
- reason 必须为 2-3 句完整逻辑（R4-22），按「触发依据；操作节奏；风险纪律」三段式组织，
  禁止单句理由（如仅"建议增仓"）

## 持仓分析
{holdings_text}

{quality_note}
请按 strategy_check.md 要求的 JSON 格式输出分析报告。
"""
    from ..analysis.registry import get_agent
    _start_ms = time.monotonic()
    try:
        # round14 P0-B（方案 b）: 策略检查 LLM 超时根因 = provider 35s 无响应 + 预算-重试
        # 不匹配。max_retries=1 时最坏 (1+1)×2providers×35s=140s > 0.9×90s=81s——
        # 第 1 轮双 provider 失败耗时 71.5s 已耗光预算，第 2 轮开始即被外层截断
        # （CancelledError 兜底）。改为 max_retries=0（1 轮双 provider 失败立即兜底，
        # 不进入会超预算的重试），外层 _llm_timeout_for 完整档同步 90s→75s
        # （对齐 71.5s 实测最坏 + 余量）：2×35=70 ≤ 75 通过一致性断言。
        # 注释修正：旧注释「与 P0-F 的 30s 外层预算配套」过时——外层实际按
        # _llm_timeout_for(data_quality) 分级（完整 75s / partial 30s / all_empty 15s）。
        return await get_agent("strategy_check").run_json(
            prompt,
            max_retries=0,
            rate_limit_cap=10.0,
            # round10 P1-I: 单次 provider 调用 35s 超时即切 fallback；max_retries=0
            # 保证最坏 2×35=70s ≤ 75s 外层预算（round14 P0-B 预算-重试一致性）。
            request_timeout=35.0,
        )
    except BaseException as e:  # noqa: BLE001 — F1-9: 必须捕获 CancelledError（BaseException）
        # F1-9: asyncio.wait_for(20s) 超时取消内部任务时抛 CancelledError，
        # 它不是 Exception 子类，`except Exception` 捕获不到 → 失败记录写不进 usage、
        # fallback provider 从未轮到。这里捕获后立即构造规则兜底（同步操作，不允许再 await），
        # 使 wait_for 拿到兜底结果而不是让取消异常穿透。
        duration_s = time.monotonic() - _start_ms
        # R5-1-6: 追加最后 LLM 错误诊断（区分限流/超时/其他），供用户/日志定位
        _diag = ""
        try:
            from .llm import get_last_llm_error
            _last_err = get_last_llm_error()
            if _last_err:
                _diag = f"（最后错误: {_last_err}）"
        except Exception:
            pass
        logger.warning(
            "[strategy_check] LLM analysis interrupted after %.1fs (timed out or cancelled: %s) — rule fallback%s",
            duration_s, type(e).__name__, _diag,
        )
        return {
            "summary": (
                f"LLM 分析超时（{duration_s:.0f}s 未返回，已用规则引擎兜底）{_diag}"
            ),
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }


async def generate_sector_analysis(
    sector_code: str,
    sector_name: str,
    sector_stocks: list[dict],
    indices: list[dict],
    commodities: list[dict],
    market_data: list[dict],
    factor_scores: list[dict] | None = None,
) -> str:
    """行业/概念板块 AI 分析 — 包含成分股、大盘环境、资金流向、近期行情。"""
    idx_map = {idx.get("name", ""): idx for idx in indices}
    comm_map = {c.get("name", ""): c for c in commodities}

    # Extract market regime/sentiment from market_data if injected
    regime = ""
    sentiment = ""
    news_items = []
    for item in market_data:
        title = item.get("title", "")
        if title and title.startswith("【市场背景】"):
            regime = title.replace("【市场背景】", "").strip()
        elif title and title.startswith("【板块动量】"):
            pass  # handled below
        else:
            news_items.append(item)

    prompt = f"""## {sector_name}({sector_code}) 板块分析

### 成分股（近期表现）
"""
    for s in sector_stocks[:20]:
        prompt += f"- {s.get('name', '')}({s.get('symbol', '')}): 价格 {s.get('price', 'N/A')}, 涨跌幅 {s.get('change_pct', 'N/A')}%\n"

    prompt += f"""
### 大盘环境
- 上证指数: {idx_map.get('上证指数', {}).get('price', 'N/A')} ({idx_map.get('上证指数', {}).get('change_pct', 'N/A')}%)
- 沪深300: {idx_map.get('沪深300', {}).get('price', 'N/A')} ({idx_map.get('沪深300', {}).get('change_pct', 'N/A')}%)
- 创业板指: {idx_map.get('创业板指', {}).get('price', 'N/A')} ({idx_map.get('创业板指', {}).get('change_pct', 'N/A')}%)
{regime}
"""

    # Factor scores / sector momentum
    if factor_scores:
        prompt += "\n### 板块动量 / 因子得分\n"
        for fs in factor_scores[:15]:
            name = fs.get("name", fs.get("symbol", "?"))
            scores = fs.get("factor_scores", fs.get("scores", {}))
            if scores and isinstance(scores, dict):
                score_items = ", ".join(
                    f"{k}: {v:.2f}" for k, v in sorted(scores.items(), key=lambda x: -abs(x[1]))[:5]
                )
                prompt += f"- {name}: {score_items}\n"
            else:
                chg = fs.get("change_pct", "")
                if chg != "":
                    prompt += f"- {name}: 涨跌幅 {chg}%\n"

    prompt += f"""
**分析要求：**
- 针对中国市场 A 股进行专业分析，不要错误分析港股或美股数据
- **重点分析近 1-5 个交易日的板块走势、量价变化**
- 结合上述成分股表现、大盘环境和板块动量数据

请按以下框架输出 Markdown 分析报告：

### 近期走势
1. **近 5 日**该板块的涨跌幅变化、成交量变化趋势
2. **近 1 日**领涨/领跌成分股及原因

### 资金面
1. 主力资金净流入/流出情况
2. 板块成交额变化（放量/缩量）

### 催化因素
1. 政策面驱动
2. 行业基本面变化
3. 外部事件催化

### 后市研判
1. 短期技术走势判断
2. 关键支撑/压力位
3. 关注的成分股
4. 给出 3-5 个交易日的走势预判

注意：
- 使用具体数据（价格、涨跌幅、成交量等），不要模糊描述
- 控制篇幅在 600 字以内
- 用 **加粗** 标注关键数据
"""
    from ..analysis.registry import get_agent
    return await get_agent("sector_analysis").run(prompt)

async def generate_symbol_analysis(
    symbol: str,
    name: str,
    asset_type: str,
    realtime: dict,
    history: list[dict],
    indicators: dict[str, Any],
    news: list[dict],
) -> str:
    hist_text = "\n".join([
        f"- {h.get('date', '')}: 收盘 {h.get('close', 'N/A')}, 涨跌幅 {h.get('change_pct', 'N/A')}%"
        for h in history[-10:]
    ])

    ind_text = "\n".join([f"- {k}: {v}" for k, v in indicators.items() if v is not None])

    news_text = "\n".join([f"- {n.get('title', n.get('summary', ''))[:100]}" for n in news[:5]])

    prompt = f"""## {name}({symbol}) 个股/ETF 深度分析

### 实时行情
- 当前价格: {realtime.get('price', 'N/A')}
- 涨跌幅: {realtime.get('change_pct', 'N/A')}%
- 成交额: {realtime.get('turnover', 'N/A')} 万
- 换手率: {realtime.get('turnover_rate', 'N/A')}%

### 近期走势
{hist_text}

### 技术指标
{ind_text}

### 相关资讯
{news_text}

请输出：
1. 技术面研判（趋势/支撑/阻力/量能）
2. 基本面/消息面催化剂
3. 买卖信号（明确给出：买入/持有/卖出）
4. 目标价位区间
5. 止损位
6. 风险提示

  控制在 500 字以内。"""

    return await get_agent("symbol_analysis").run(prompt)

# ── 设计报告 LLM 生成 ────────────────────────────────────


async def generate_design_report(
    strategies: list[dict],
    market_sentiment: dict | None = None,
    benchmark_stocks: list[dict] | None = None,
    market_context: dict | None = None,
    plan_tables: str = "",
) -> str:
    """基于系统算法生成的组合方案，调用 LLM 撰写市场分析报告。

    Args:
        strategies: 三个方案数据（来自战略设计管道）
        market_sentiment: 市场情绪数据（可选，兼容旧调用）
        benchmark_stocks: 核心指标股数据（可选，兼容旧调用）
        market_context: 完整市场上下文（P1 增强：含 index_realtime / market_regime /
            macro_regime / sector_momentum 等），优先于上面两个单独字段

    Returns:
        Markdown 格式的分析报告
    """
    ctx = market_context or {}
    # 兼容旧调用：若未传 market_context，则回退到单独字段
    if not ctx:
        ctx = {
            "market_sentiment": market_sentiment or {},
            "benchmark_stocks": benchmark_stocks or [],
        }
    prompt = _build_design_report_prompt(
        strategies,
        ctx.get("market_sentiment", market_sentiment or {}),
        ctx.get("benchmark_stocks", benchmark_stocks or []),
        market_context=ctx, plan_tables=plan_tables,
    )

    # ── LLM call with Provider failover ────────────────────────────
    # 方案一（plan v1.2）: Provider failover 是充分的防护层，
    # 熔断器检查已移除（它会误伤正常 Provider 导致空报告）。
    # _build_engine_fallback() 作为 last-resort fallback 保留。
    try:
        # 使用"symbol_analysis" agent 的通用上下文，但传入设计报告 prompt
        result = await get_agent("symbol_analysis").run(
            prompt,
            system_override=load_prompt("design_report.md"),
        )
        return result or "报告生成失败"
    except Exception as e:
        logger.warning("[generate_design_report] LLM call failed: %s", e)
        # Return engine fallback instead of empty string
        regime = ctx.get("market_regime", "unknown")
        return _build_engine_fallback(strategies, regime)


def _build_factor_breakdown_table(strategies: list[dict]) -> str:
    """Build a markdown table of factor breakdowns from strategies' allocations.

    Returns:
        A markdown table string (may be empty if no factor data found).
    """
    seen: set[str] = set()
    all_factor_keys: set[str] = set()
    rows: list[tuple[str, str, str, list[str]]] = []

    # First pass: collect all unique factor keys across all allocations
    for s in strategies:
        for a in (s.get("allocations") or s.get("etfs") or []):
            sym = a.get("symbol", "")
            if sym and sym not in seen and sym != "CASH":
                seen.add(sym)
                fb = a.get("factor_breakdown") or a.get("factor_scores") or {}
                for k in fb:
                    all_factor_keys.add(k)

    if not all_factor_keys:
        return ""

    factor_keys = sorted(all_factor_keys)
    seen.clear()

    # Second pass: collect row data
    for s in strategies:
        for a in (s.get("allocations") or s.get("etfs") or []):
            sym = a.get("symbol", "")
            if sym and sym not in seen and sym != "CASH":
                seen.add(sym)
                name = (a.get("name", "") or "")[:20]
                fs_raw = a.get("factor_score")
                fs = f"{fs_raw:.3f}" if isinstance(fs_raw, (int, float)) else "—"
                fb = a.get("factor_breakdown") or a.get("factor_scores") or {}
                cells = []
                for k in factor_keys:
                    v = fb.get(k)
                    cells.append(f"{v:.3f}" if isinstance(v, (int, float)) else "—")
                rows.append((sym, name, fs, cells))

    # Build header
    header = ["Symbol", "Name", "Factor Score"] + list(factor_keys)
    sep = ["---"] * len(header)
    lines = [
        "## ETF Factor Breakdown",
        "",
        "Below are the detailed factor scores for each selected ETF, indicating WHY each was selected:",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for sym, name, fs, cells in rows:
        row = [sym, name, fs] + cells
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("For each ETF, the dominant factors are the ones with highest absolute scores.")
    lines.append("Use these factor details when writing the rationale for each ETF selection.")
    lines.append("")
    return "\n".join(lines)



def _build_design_report_prompt(
    strategies: list[dict],
    market_sentiment: dict,
    benchmark_stocks: list[dict],
    market_context: dict | None = None,
    plan_tables: str = "",
) -> str:
    """构建设计报告 prompt。

    P1 增强：新增「市场行情快照」（实时指数点位/涨跌幅）与「行业板块动量」两节，
    使 LLM 报告能引用实际市场数据而非仅情绪指数。
    """
    market_context = market_context or {}
    _regime = market_context.get("market_regime") or market_sentiment.get("market_regime")
    _macro = market_context.get("macro_regime") or {}
    index_realtime = market_context.get("index_realtime") or []
    sector_momentum = market_context.get("sector_momentum") or []
    hot_plates = market_context.get("hot_plates") or []

    # 数据日期标签：非交易日的行情来自上一交易日
    from ..core.market_calendar import is_trading_time as _is_trading
    from datetime import timedelta as _td
    _now = __import__('datetime', fromlist=['datetime']).datetime.now()
    if _is_trading(_now):
        data_date_label = "今日"
    else:
        _d = _now - _td(days=1)
        _d -= _td(days=(_d.weekday() - 4)) if _d.weekday() >= 5 else _td(days=0)  # 跳到周五
        data_date_label = f"{_d.month}月{_d.day}日"

    def _fmt_pct(v, as_percent: bool = False):
        """N02: 显式单位参数，不再用 abs>1 启发式（round3 N02：指数 0.72 被误判为小数
        比例 → ×100=72%）。

        - as_percent=True: v 已是百分数值（0.72 = 0.72%），直接显示。
        - as_percent=False（默认）: v 是小数比例（0.08 = 8%），×100。

        数据管道约定：change_pct 类字段（指数/板块/benchmark）统一为百分数值；
        expected_return/max_drawdown 等收益类字段为小数比例。
        """
        if v is None:
            return "—"
        if isinstance(v, (int, float)):
            return f"{v:.1f}%" if as_percent else f"{v * 100:.1f}%"
        return str(v)

    # ── P5-a: 注入预生成的方案表格（引擎直接渲染，确保与方案卡片一致） ──
    _factor_table = _build_factor_breakdown_table(strategies)

    if plan_tables:
        lines = [
            "## 注意：报告撰写范围说明",
            "",
            f"以下为引擎算法直接生成的方案详解表格，与前端「方案卡片」的数据来源完全一致。",
            "你**不需要**在报告正文中重新描述各方案的 ETF 标的、权重和入选理由。",
            "你的任务是：",
            "1. 基于「市场行情快照」「行业板块动量」「市场情绪」等输入数据，撰写「市场环境分析」；",
            "2. 说明三层设计框架（核心/卫星/防御）；",
            "3. 横向对比三种方案的特点和适用场景；",
            "4. 给出配置建议和风险提示。",
            "",
            "引擎预生成的方案表格如下（将自动嵌入报告第三部分）：",
            "",
            plan_tables,
            "",
            "---",
            "",
            # N02: prompt 防御——指数/板块涨跌幅已是百分数值，禁止 LLM 再 ×100 换算
            "注意：本文档中「市场行情快照」「行业板块动量」的涨跌幅字段已是百分数值"
            "（如 0.72 表示 0.72%），引用时直接使用，**禁止**再乘以 100 换算。",
            "",
        ]
        if _factor_table:
            lines.append(_factor_table)
            lines.append("")
        lines.append("## 输入数据")
        lines.append("")
        lines.append("### 市场情绪")
    else:
        lines = []
        if _factor_table:
            lines.append(_factor_table)
            lines.append("")
        lines.append("## 输入数据")
        lines.append("")
    lines.append("### 市场情绪")
    lines.append(f"- 情绪指数: {market_sentiment.get('sentiment_index', 'N/A')}")
    lines.append(f"- 情绪标签: {market_sentiment.get('sentiment_label', 'N/A')}")
    lines.append("")

    # ── P1 新增：市场行情快照（实时指数） ──
    if index_realtime:
        lines.append("### 市场行情快照（实时指数）")
        for idx in index_realtime:
            chg = idx.get("change_pct")
            chg_txt = _fmt_pct(chg, as_percent=True) if chg is not None else "—"
            lines.append(
                f"- {idx.get('name', idx.get('symbol', ''))}（{idx.get('symbol', '')}）: "
                f"点位 {idx.get('price', '—')}，今日 {chg_txt}"
            )
        lines.append("")

    # ── 市场状态 / 宏观（补充上下文） ──
    if _regime:
        lines.append("### 市场状态")
        lines.append(f"- 市场状态(regime): {_regime}")
        if _macro:
            eco = _macro.get("economic_phase")
            mon = _macro.get("monetary_stance")
            if eco:
                lines.append(f"- 宏观: {eco}" + (f"·{mon}" if mon else ""))
        lines.append("")

    if benchmark_stocks:
        lines.append("### 核心指标股")
        for s in benchmark_stocks[:5]:
            lines.append(f"- {s.get('name', '')}({s.get('symbol', '')}): "
                         f"涨跌{_fmt_pct(s.get('change_pct', 0), as_percent=True)}, "
                         f"信号: {s.get('signal', '')}")
        lines.append("")

    # ── P1 新增：行业板块动量 ──
    if sector_momentum:
        lines.append("### 行业板块动量（申万一级，按当日强弱排名）")
        for item in sector_momentum[:10]:
            name = item.get("sector_name") or item.get("sector") or ""
            rank = item.get("rank") or item.get("rank_current")
            total = item.get("total") or ""
            chg = item.get("change_pct")
            chg_txt = _fmt_pct(chg, as_percent=True) if chg is not None else ""
            rank_txt = f"第{rank}/{total}名" if rank is not None else ""
            lines.append(f"- {name}: {rank_txt} 当日{chg_txt}".rstrip())
        lines.append("")

    # ── Phase 4 新增：概念板块动量 ──
    concept_items = [i for i in sector_momentum if i.get("type") == "concept"]
    if concept_items:
        lines.append("### 概念板块动量（按当日涨跌幅排名）")
        for item in concept_items[:10]:
            name = item.get("sector_name") or item.get("sector") or ""
            chg = item.get("change_pct")
            chg_txt = _fmt_pct(chg, as_percent=True) if chg is not None else ""
            flow = item.get("main_inflow", "")
            flow_txt = f"  主力净流入: {flow}" if flow else ""
            lines.append(f"- {name}: {chg_txt}{flow_txt}")
        lines.append("")

    # ── Phase 4 新增：热点板块（财联社） ──
    if hot_plates:
        lines.append("### 今日热点板块（财联社）")
        for hp in hot_plates[:8]:
            name = hp.get("plate_name", hp.get("name", ""))
            reason = hp.get("reason", hp.get("hot_reason", ""))
            stocks = hp.get("stocks", hp.get("lead_stocks", []))
            stock_str = ", ".join([s.get("name", "") for s in stocks[:3]])
            lines.append(f"- **{name}**: {reason}")
            if stock_str:
                lines.append(f"  领涨: {stock_str}")
        lines.append("")

    # ── C1 资金流向 ──
    fund_flow = market_context.get("fund_flow", {})
    if fund_flow.get("total_symbols", 0) > 0:
        total = fund_flow.get("total_net_inflow", 0)
        pos = fund_flow.get("positive_flow_count", 0)
        neg = fund_flow.get("negative_flow_count", 0)
        direction = "净流入" if total > 0 else "净流出"
        intensity = "显著" if abs(total) > 1000 else "温和" if abs(total) > 100 else "微弱"
        lines.append("### 资金流向")
        lines.append(f"- 候选池 {fund_flow['total_symbols']} 只 ETF 合计主力{intensity}{direction}：{total/10000:.1f} 亿元")
        lines.append(f"- 主力资金净流入 {pos} 只，净流出 {neg} 只")
        lines.append("")

    # ── 因子评分（5.0+ 新增） ──
    if strategies:
        lines.append("### 各标的因子评分")
        lines.append("（多因子模型综合评分，0~1）")
        for s in strategies:
            label = s.get("label", "")
            lines.append(f"- {label}:")
            for e in (s.get("allocations") or s.get("etfs") or [])[:5]:
                code = e.get("symbol", "")
                name = e.get("name", "")[:10]
                fs = e.get("factor_score", None)
                if fs is not None:
                    lines.append(f"  - {name}({code}) 评分: {fs:.2f}")
                    # 取 top-3 factor_scores 子项（如有 breakdown）
                    fs_detail = e.get("factor_scores", {})
                    if isinstance(fs_detail, dict) and fs_detail:
                        top_3 = sorted(fs_detail.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
                        for f_code, f_val in top_3:
                            lines.append(f"    {f_code}: {f_val:.2f}")
        lines.append("")

    lines.append("### 组合方案")
    if not plan_tables:
        for s in strategies:
            style = s.get("style", s.get("style_label", ""))
            lines.append(f"- {style}: {s.get('portfolio_name', '')}")
            lines.append(f"  定位: {s.get('positioning', '')}")
            lines.append(f"  预期年化: {_fmt_pct(s.get('expected_return'))}, "
                         f"最大回撤: {_fmt_pct(s.get('max_drawdown'))}, "
                         f"夏普: {s.get('sharpe_ratio', 'N/A')}")
            for a in s.get("allocations", []):
                weight = a.get("target_weight", 0) * 100
                lines.append(f"  - {a.get('name', '')}({a.get('symbol', '')}) "
                             f"[{a.get('layer', '')}] {weight:.1f}% - {a.get('selection_rationale', '')}")
            lines.append("")

    return "\n".join(lines)

def _build_advice_stream_prompt(query: str, ctx: dict) -> str:
    """构建流式投资建议 prompt — 注入市场数据。"""
    lines = [f"用户提问: {query}", ""]

    regime = ctx.get("market_regime", "")
    if regime:
        lines.append(f"## 市场背景\n- 市场状态: {regime}")

    sentiment = ctx.get("market_sentiment", {})
    if sentiment and isinstance(sentiment, dict):
        s_lbl = sentiment.get("sentiment_label", "")
        s_idx = sentiment.get("sentiment_index", "")
        if s_lbl and s_idx:
            lines.append(f"- 市场情绪: {s_lbl} ({s_idx}/100)")
        elif s_lbl:
            lines.append(f"- 市场情绪: {s_lbl}")

    market_data = ctx.get("market_data", [])
    if market_data:
        lines.append("\n## 实时行情")
        for item in market_data[:8]:
            name = item.get("name", "?")
            price = item.get("price", "N/A")
            chg = item.get("change_pct", "")
            if chg != "":
                lines.append(f"- {name}: {price} ({chg:+.2f}%)")

    news = ctx.get("news", [])
    if news:
        lines.append("\n## 近期资讯")
        for n in news[:5]:
            lines.append(f"- {str(n.get('title', ''))[:80]}")

    portfolio = ctx.get("portfolio", [])
    if portfolio:
        lines.append("\n## 持仓信息")
        for p in portfolio[:5]:
            w = p.get("target_weight", 0) or 0
            name = p.get('name', '?') or '?'
            sym = p.get('symbol', '?') or '?'
            lines.append(f"- {name}({sym}): {w*100:.1f}%")

    lines.append('')
    lines.append('请按以下框架回答：')
    lines.append('1. 直接回答用户问题，引用具体数据')
    lines.append('2. 给出判断依据')
    lines.append('3. 如涉及操作，给出分析和建议（不构成投资指令）')
    lines.append('')
    lines.append('使用 Markdown 格式，控制 800 字以内。')

    # F1: sector momentum data
    sector_data = ctx.get("sector_momentum", [])
    if sector_data:
        lines.append("\n### 行业板块涨跌（当日排名）")
        for item in sector_data[:10]:
            name = item.get("sector_name") or item.get("name", "?")
            chg = item.get("change_pct")
            cht = f"({chg:+.2f}%)" if chg is not None else ""
            lines.append(f"- {name}: {cht}")
        lines.append("")

    # P0-A (round10 §4.1/§10): hot_plates / sector_heat 槽——build_full_context 已
    # 注入（include_sectors=True），补消费避免「暂无板块热力数据」回退。数据为空时
    # 引擎显式降级文案，不再凭空捏造。
    hot_plates = ctx.get("hot_plates", []) or []
    if hot_plates:
        lines.append("\n### 热点板块（涨停/封板）")
        for item in hot_plates[:8]:
            name = item.get("name") or item.get("plate_name") or "?"
            chg = item.get("change_pct")
            cht = f"({chg:+.2f}%)" if isinstance(chg, (int, float)) else ""
            reason = item.get("reason") or ""
            lines.append(f"- {name}: {cht}{(' ' + str(reason)[:60]) if reason else ''}")
        lines.append("")
    sector_heat = ctx.get("sector_heat", [])
    if sector_heat:
        lines.append("\n### 板块热力（涨幅榜）")
        for item in sector_heat[:10]:
            name = item.get("name") or item.get("sector_name") or "?"
            chg = item.get("change_pct")
            cht = f"({chg:+.2f}%)" if isinstance(chg, (int, float)) else ""
            lines.append(f"- {name}: {cht}")
        lines.append("")

    # F2: fund flow data
    fund_flow = ctx.get("fund_flow", {})
    if fund_flow.get("total_symbols", 0) > 0:
        total = fund_flow.get("total_net_inflow", 0)
        pos = fund_flow.get("positive_flow_count", 0)
        neg = fund_flow.get("negative_flow_count", 0)
        direction = "净流入" if total > 0 else "净流出"
        intensity = "显著" if abs(total) > 1000 else "温和" if abs(total) > 100 else "微弱"
        lines.append(f"### 资金流向")
        lines.append(f"- 全市场主力{intensity}{direction}：{total/10000:.1f}亿元（净流入{pos}只/净流出{neg}只）")
        lines.append("")

    # F5: industry rotation framework
    lines.append('### 行业轮动分析框架')
    lines.append('- 最强/最弱板块：优先引用行业涨跌幅排名数据')
    lines.append('- 轮动方向：分析资金从一个板块向另一个板块的趋势（短期/中期）')
    lines.append('- 交叉验证：行业涨跌幅 + 资金流向 + 新闻事件')
    lines.append('')

    return "\n".join(lines)
