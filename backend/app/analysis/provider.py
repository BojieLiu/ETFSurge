"""
LLM provider configuration and failover orchestration.

Defines the data model for a single LLM API provider and builds the
priority-ordered provider list from application settings.

Supports a primary → fallback failover chain:
  1. OpenCode Zen (deepseek-v4-flash-free)
  2. DeepSeek Official (deepseek-v4-flash)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from ..config import settings

logger = logging.getLogger(__name__)

# Fallback API URL (official DeepSeek)
LLM_API_URL = "https://api.deepseek.com/chat/completions"


@dataclass
class ProviderConfig:
    """Configuration for a single LLM API provider."""

    id: str                        # unique identifier e.g. "opencode_zen"
    name: str                      # human-readable name
    api_url: str                   # full chat/completions URL
    api_key: str                   # Bearer token
    model: str                     # model identifier sent in request body
    timeout: int = 120             # request timeout in seconds


def get_configured_providers() -> list[ProviderConfig]:
    """Return providers in priority order (primary first, fallback last).

    Respects settings:
      - LLM_PRIMARY_PROVIDER   — which provider is primary ("opencode_zen" by default)
      - LLM_FALLBACK_PROVIDER  — which provider is fallback ("deepseek" by default)
      - OPENCODE_ZEN_API_KEY   — if empty, primary is skipped
      - DEEPSEEK_API_KEY       — if empty, fallback is skipped
    """
    providers: list[ProviderConfig] = []
    primary_id = (settings.llm_primary_provider or "").strip().lower()

    # ── Primary: OpenCode Zen ──────────────────────────────────
    if primary_id == "opencode_zen":
        if settings.opencode_zen_api_key:
            providers.append(ProviderConfig(
                id="opencode_zen",
                name="OpenCode Zen",
                api_url=settings.opencode_zen_api_url
                           or "https://opencode.ai/zen/v1/chat/completions",
                api_key=settings.opencode_zen_api_key,
                model=settings.opencode_zen_model or "deepseek-v4-flash-free",
                timeout=settings.llm_primary_timeout,
            ))
        else:
            logger.info("[provider] Primary provider 'opencode_zen' skipped "
                        "(OPENCODE_ZEN_API_KEY not configured)")

    # ── Fallback: DeepSeek Official ────────────────────────────
    # F7b: LLM_FALLBACK_PROVIDER 必须真正生效（旧代码从不读取，属死配置）。
    # 仅当 fallback 配置为 deepseek（或空=默认）时才挂载官方 DeepSeek。
    fallback_id = (settings.llm_fallback_provider or "deepseek").strip().lower()
    if fallback_id and fallback_id != "deepseek":
        logger.warning(
            "[provider] LLM_FALLBACK_PROVIDER=%r 不受支持（仅 'deepseek'），已忽略",
            settings.llm_fallback_provider,
        )
    if settings.deepseek_api_key and fallback_id in ("", "deepseek"):
        models = str(settings.llm_model or "")
        # deepseek-chat/deepseek-reasoner 已于 2026/07/24 废弃，统一使用 deepseek-v4-flash
        # 'deepseek-v4-flash-free' 仅对 OpenCode Zen 有效，官方 API 用 deepseek-v4-flash
        if models == "deepseek-v4-flash-free":
            models = "deepseek-v4-flash"
        providers.append(ProviderConfig(
            id="deepseek",
            name="DeepSeek Official",
            api_url=LLM_API_URL,
            api_key=settings.deepseek_api_key,
            model=models,
            timeout=settings.llm_fallback_timeout,
        ))
    else:
        logger.info("[provider] Fallback provider 'deepseek' skipped "
                    "(DEEPSEEK_API_KEY not configured)")

    return providers


def has_any_api_key() -> bool:
    """Check if at least one provider has an API key configured."""
    return bool(settings.opencode_zen_api_key or settings.deepseek_api_key)


async def call_with_failover(
    request_fn: Callable,
    providers: list[ProviderConfig],
    **kwargs,
) -> tuple:
    """Iterate providers in priority order, calling request_fn for each.

    Args:
        request_fn: Async callable that takes (provider, **kwargs) and
                    returns (response_body_str, usage_dict).
        providers: Priority-ordered list of ProviderConfig.

    Returns:
        (response_body_str, used_provider)

    Raises:
        The last exception if all providers fail.
    """
    if not providers:
        raise ValueError("No LLM providers configured")

    last_error: Exception | None = None
    for idx, provider in enumerate(providers):
        start = time.monotonic()
        try:
            result = await request_fn(provider, **kwargs)
            elapsed = time.monotonic() - start
            logger.info(
                "[LLM] Provider %s succeeded in %.1fs (model=%s)",
                provider.id, elapsed, provider.model,
            )
            return result
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.warning(
                "[LLM] Provider %s failed after %.1fs: %s",
                provider.id, elapsed, exc,
            )
            last_error = exc
            # Log fallback intent if there are more providers
            if idx < len(providers) - 1:
                logger.warning(
                    "[LLM] Falling back to %s", providers[idx + 1].id,
                )
            continue

    # All providers exhausted
    if last_error is None:
        raise RuntimeError("No LLM providers available")
    raise last_error
