"""LLM client (complete / stream) — split from analysis/llm.py (Batch 2)."""

import asyncio
import json
import ssl
import sys
import time
from typing import AsyncGenerator

from app.analysis.llm.cache import get_cached_report, put_cached_report
from app.analysis.llm.gates import (
    _circuit_allow,
    _circuit_record_failure,
    _circuit_record_failure_all_models_quota,
    _circuit_record_success,
    _circuit_state,
    _clear_llm_error,
    _record_llm_error,
    llm_quota_gate,
    mark_middle_layer_active,
)
from app.analysis.llm.prompts import SYSTEM_PROMPT, strip_internal_leak
from app.analysis.provider import (
    ProviderConfig,
    get_configured_providers,
    has_any_api_key,
)
from app.core.logging import get_logger
from app.monitor.token_usage import UsageRecord, token_store

logger = get_logger(__name__)

# F6: LLM retry policy — after every configured provider fails, retry the
# full provider sequence once, waiting LLM_RETRY_DELAY seconds between attempts.
# F3-6: 429 限流场景按 Retry-After / 指数退避（<=30s）重试 2 次后再降级。
LLM_MAX_RETRIES = 2
LLM_RETRY_DELAY = 3.0
_LLM_RATE_LIMIT_CAP = 30.0


def _apply_provider_body(body: dict, provider: ProviderConfig) -> None:
    """round35 feed-fix: 强制思考模型（opencode zen 的 deepseek-V4 / x-preview
    免费档等）必须显式声明 reasoning_effort（low/high/max），缺失会被网关 400
    「This model always engages in thinking and cannot be disabled」。
    此类模型也不支持 temperature——一并移除，避免被拒或静默忽略。
    """
    if getattr(provider, "reasoning_effort", None):
        body["reasoning_effort"] = provider.reasoning_effort
        body.pop("temperature", None)


# ── round36 §8-A2: 共享 SSL 上下文（py-spy 现行取证）──────────────────
# 三个入口此前每次调用每候选都 `httpx.AsyncClient(...)` 新建 → httpx 内部
# create_default_context() 在事件循环上同步执行（ssl.py:707 py-spy 实录，
# Windows 证书加载可达百 ms 级）× failover 链 × 重试 × 并发调用叠加成可感冻结。
# 进程级缓存一个 SSLContext 传入 verify= → httpx 直接复用，零行为差异。
_SSL_CONTEXT: ssl.SSLContext | None = None


def _shared_ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


async def llm_complete(
    prompt: str,
    response_format: dict | None = None,
    max_retries: int = LLM_MAX_RETRIES,
    retry_delay: float = LLM_RETRY_DELAY,
) -> str:
    import httpx
    await _check_key()
    # round25 R39: 跨任务配额门禁——任意两次 LLM 调用间隔 ≥ inter_call_cooldown
    await llm_quota_gate.acquire()

    _caller = sys._getframe(1).f_code.co_name
    providers = get_configured_providers()
    last_exc: Exception | None = None
    _saw_empty = False
    _any_429 = False
    _last_429_headers = None
    _any_429 = False
    _last_429_headers = None

    for attempt in range(max_retries + 1):
        _attempted_any = False
        for provider in providers:
            # F8: 熔断 OPEN 态直接跳过（零探测）
            if not _circuit_allow(provider.id, provider.model):
                continue
            _attempted_any = True
            if provider.id == "openrouter":
                # §19.9 约束#4/验收#6: 中间层承流即打标——后台低价值调用（新闻摘要等）
                # 据此跳过，防烧穿免费日额度；TTL 过期视为 Zen 已恢复。
                mark_middle_layer_active()
            body = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 12288,
            }
            _apply_provider_body(body, provider)
            if response_format:
                body["response_format"] = response_format

            _start = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=provider.timeout, trust_env=False, verify=_shared_ssl_context()
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
                    if not (content or "").strip():
                        # §19.9 约束#2: 200-空内容=假完成（reasoning 型烧尽 max_tokens 实测）
                        # → 计失败触发按序重选，不得返回空串冒充成功。
                        _saw_empty = True
                        _circuit_record_failure(provider.id, False, model=provider.model)
                        logger.warning("[LLM] %s 200-empty content -> next candidate", provider.model)
                        last_exc = RuntimeError(f"{provider.model}: empty content")
                        continue

                    # F8: 成功 → 熔断恢复
                    _circuit_record_success(provider.id, provider.model)

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
                # F8/F9: 429→立即 OPEN；其它异常→累计失败；round39 永久错误检测需要 exc
                _circuit_record_failure(provider.id, _is_429, model=provider.model, exc=_exc)
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

        # 本轮所有 provider 均被熔断跳过 → 直接跳出
        if not _attempted_any:
            break
        # 所有 provider 均已 OPEN（熔断）→ 下一轮也全跳过，避免白等退避。
        # round39 改进: 若某 provider 名下所有 model 都 OPEN（429 quota 累计），触发
        # _circuit_record_failure_all_models_quota → 全局 llm_quota_gate 兜底暂停，
        # 防热循环继续撞墙（单模型 429 已不触发全局暂停，避免其它可用模型被连坐）。
        if all(_circuit_state(p.id, p.model) == "OPEN" for p in providers):
            _by_pid: dict[str, list[str]] = {}
            for _p in providers:
                _by_pid.setdefault(_p.id, []).append(_p.model)
            for _pid, _models in _by_pid.items():
                _circuit_record_failure_all_models_quota(_pid, _models)
            break
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
    if _saw_empty and not _any_429:
        # F5 契约保留（§19.9#2 折中）：按序重选已在链内完成，全链仅空内容时
        # 诚实返回空串而非抛新异常类型——调用方既有 falsy 处理不受影响。
        logger.warning("[LLM] all candidates returned empty content — returning empty (honest)")
        return ""
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
    # round25 R39: 跨任务配额门禁——任意两次 LLM 调用间隔 ≥ inter_call_cooldown
    await llm_quota_gate.acquire()

    providers = get_configured_providers()
    last_exc: Exception | None = None
    _any_429 = False
    _last_429_headers = None

    for attempt in range(max_retries + 1):
        _attempted_any = False
        for provider in providers:
            # F8: 熔断 OPEN 态直接跳过（零探测）
            if not _circuit_allow(provider.id, provider.model):
                continue
            _attempted_any = True
            if provider.id == "openrouter":
                # §19.9 约束#4/验收#6: 中间层承流即打标（同 llm_complete）
                mark_middle_layer_active()
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
            _apply_provider_body(body, provider)
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
                    timeout=provider.timeout, trust_env=False, verify=_shared_ssl_context()
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
                # F8/F9: 429→立即 OPEN；其它异常→累计失败；round39 永久错误检测需要 exc
                _circuit_record_failure(provider.id, _is_429, model=provider.model, exc=_exc)
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

            # §19.9 约束#2: 流式全空 = 假完成 → 计失败换下一候选（不 yield done）
            if not (full_text or "").strip():
                _circuit_record_failure(provider.id, False, model=provider.model)
                logger.warning("[LLM] Stream %s 200-empty stream -> next candidate", provider.model)
                last_exc = RuntimeError(f"{provider.model}: empty stream")
                continue
            # Success: record and yield done
            _duration = (time.monotonic() - _start) * 1000
            # F8: 成功 → 熔断恢复
            _circuit_record_success(provider.id, provider.model)
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

        # 本轮所有 provider 均被熔断跳过 → 直接跳出
        if not _attempted_any:
            break
        # 所有 provider 均已 OPEN（熔断）→ 下一轮也全跳过，避免白等退避。
        # round39 改进: 全 provider OPEN 触发 _circuit_record_failure_all_models_quota
        # → 全局 llm_quota_gate 兜底暂停（防热循环撞墙）。
        if all(_circuit_state(p.id, p.model) == "OPEN" for p in providers):
            _by_pid: dict[str, list[str]] = {}
            for _p in providers:
                _by_pid.setdefault(_p.id, []).append(_p.model)
            for _pid, _models in _by_pid.items():
                _circuit_record_failure_all_models_quota(_pid, _models)
            break
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
    # round25 R39: 跨任务配额门禁——任意两次 LLM 调用间隔 ≥ inter_call_cooldown
    await llm_quota_gate.acquire()

    _caller = sys._getframe(1).f_code.co_name
    providers = get_configured_providers()
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        _attempted_any = False
        for provider in providers:
            # F8: 模块级 TTL 熔断——OPEN 态直接跳过该 provider（零探测零过路费）。
            if not _circuit_allow(provider.id, provider.model):
                continue
            _attempted_any = True
            if provider.id == "openrouter":
                # §19.9 约束#4/验收#6: 中间层承流即打标（同 llm_complete）
                mark_middle_layer_active()
            body = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 12288,
            }
            _apply_provider_body(body, provider)
            if response_format:
                body["response_format"] = response_format
            elif force_json:
                body["response_format"] = {"type": "json_object"}

            _start = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=(request_timeout if request_timeout is not None else provider.timeout),
                    trust_env=False, verify=_shared_ssl_context()
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
                    if not (content or "").strip():
                        # §19.9 约束#2: 200-空内容=假完成 → 计失败换下一候选
                        _circuit_record_failure(provider.id, False, model=provider.model)
                        logger.warning("[LLM] %s 200-empty content -> next candidate", provider.model)
                        last_exc = RuntimeError(f"{provider.model}: empty content")
                        continue

                    # R5-1-6: 成功 → 清空错误诊断
                    _clear_llm_error()
                    # F8: 成功 → 熔断恢复（OPEN/HALF_OPEN → CLOSED）
                    _circuit_record_success(provider.id, provider.model)

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
                # F8/F9: 429/FreeUsageLimitError（额度类，持久）→ 立即 OPEN 零复试；
                # 其它异常（5xx/timeout，瞬态）→ 累计失败达阈值才 OPEN。
                _resp = getattr(_exc, "response", None)
                _is_429 = (
                    isinstance(_exc, httpx.HTTPStatusError)
                    and _resp is not None
                    and getattr(_resp, "status_code", None) == 429
                )
                if _is_429:
                    _circuit_record_failure(provider.id, True, model=provider.model, exc=_exc)
                else:
                    _circuit_record_failure(provider.id, False, model=provider.model, exc=_exc)
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

        # 本轮所有 provider 均被熔断跳过（如全部 OPEN）→ 无重试意义，直接跳出
        if not _attempted_any:
            break
        # 所有 provider 均已 OPEN（熔断）→ 下一轮也全跳过，避免白等退避。
        # round39 改进: 全 provider OPEN 触发 _circuit_record_failure_all_models_quota
        # → 全局 llm_quota_gate 兜底暂停（防热循环撞墙）。
        if all(_circuit_state(p.id, p.model) == "OPEN" for p in providers):
            _by_pid: dict[str, list[str]] = {}
            for _p in providers:
                _by_pid.setdefault(_p.id, []).append(_p.model)
            for _pid, _models in _by_pid.items():
                _circuit_record_failure_all_models_quota(_pid, _models)
            break
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
async def _check_key():
    if not has_any_api_key():
        raise ValueError(
            "No LLM API keys configured. Set OPENCODE_ZEN_API_KEY "
            "and/or DEEPSEEK_API_KEY in backend/.env"
        )
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
def run_stream_with_cache(
    agent_runtime,
    prompt: str,
    query: str | None = None,
    data_as_of: str | None = None,
    **kwargs,
) -> AsyncGenerator[dict, None]:
    """R49: 带交易日内结果缓存的流式包装（返回 async generator）。

    设计为普通函数（非 async 生成器），以便 ``agent_runtime.run_stream`` 在
    端点函数执行期被**立即调用**（同步副作用，如单测捕获 prompt），而非推迟到
    流式消费时。缓存命中判定同样在调用期同步完成。

    - 命中缓存：直接回放 done（带 ``cached=true`` 标记），不调用 LLM，秒级返回。
    - 未命中：透传 ``agent_runtime.run_stream``，累积全文并在 done 时写入缓存。

    首字节前的 ``progress`` 进度事件由 ``_sse_stream`` 负责发出，缓存命中路径
    同样保留该契约（先 progress 后 done），前端可见「命中缓存」前的瞬时进度。
    """
    cached = get_cached_report(query, data_as_of, prompt)
    if cached is not None:
        async def _cached_stream():
            yield {
                "event": "done",
                "data": {
                    "type": "done",
                    "full_text": cached["text"],
                    "usage": cached.get("usage", {}),
                    "cached": True,
                },
            }
        return _cached_stream()

    # 立即调用 agent.run_stream（同步副作用在端点执行期发生）
    ag = agent_runtime.run_stream(prompt, **kwargs)

    async def _wrap_stream():
        chunks: list[str] = []
        async for ev in ag:
            if ev.get("event") == "token":
                chunks.append(ev.get("data", {}).get("token", ""))
            yield ev
            if ev.get("event") == "done":
                full = "".join(chunks)
                # 空文不缓存：agent 若 done 前未产任何 token（异常路径/mock），
                # 缓存空文本会毒化 8h 窗口内同 (query, prompt) 请求（空报告）。
                if full:
                    put_cached_report(query, data_as_of, prompt, full, ev.get("data", {}).get("usage", {}))

    return _wrap_stream()
