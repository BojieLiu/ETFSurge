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
from dataclasses import dataclass

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
    # round35 feed-fix: 强制思考模型必须显式声明 reasoning_effort（low/high/max），
    # 且此类模型不支持 temperature。非 None 时请求体携带该字段并省略 temperature。
    reasoning_effort: str | None = None


# round35 feed-fix: opencode zen 把 V4 免费档 / x-preview 系列路由为
# 强制思考（cannot be disabled）——缺 reasoning_effort 会被网关 400。
# flash/-free/x-preview 系 → high，pro 系 → max（见 opencode/DeepSeek 官方契约）。
def _reasoning_effort_for_model(model: str) -> str | None:
    m = (model or "").lower()
    if m.endswith("-free") or "flash" in m or "x-preview" in m or m.startswith("x-"):
        return "high"
    if "pro" in m:
        return "max"
    return None


def _zen_candidates() -> list[ProviderConfig]:
    """§19/§19.9: 目录池可用 → Zen 层随机尝试序列（护栏 1 无放回跳过被阻 /
    护栏 4 allowed_subset 收缩随机域）；目录不可用（未刷新/空池）→ 现状静态
    单候选，诚实降级到旧行为。"""
    from .llm.gates import _circuit_allow
    from .llm.model_catalog import model_catalog, zen_attempt_sequence

    base_url = settings.opencode_zen_api_url or "https://opencode.ai/zen/v1/chat/completions"
    pool = model_catalog.zen_pool()
    if not pool:
        m = settings.opencode_zen_model or "deepseek-v4-flash-free"
        return [ProviderConfig(
            id="opencode_zen", name="OpenCode Zen",
            api_url=base_url, api_key=settings.opencode_zen_api_key,
            model=m, timeout=settings.llm_primary_timeout,
            reasoning_effort=_reasoning_effort_for_model(m),
        )]
    allowed = [s.strip() for s in (settings.llm_zen_allowed_models or "").split(",") if s.strip()]
    seq = zen_attempt_sequence(
        pool,
        is_blocked=lambda m: not _circuit_allow("opencode_zen", m),
        allowed_subset=allowed or None,
    )
    out: list[ProviderConfig] = []
    for i, m in enumerate(seq, 1):
        out.append(ProviderConfig(
            id="opencode_zen", name=f"OpenCode Zen#{i}",
            api_url=base_url, api_key=settings.opencode_zen_api_key,
            model=m, timeout=settings.llm_primary_timeout,
            reasoning_effort=_reasoning_effort_for_model(m),
        ))
    return out


def get_configured_providers() -> list[ProviderConfig]:
    """Return providers in priority order (primary first, fallback last).

    Respects settings:
      - LLM_PRIMARY_PROVIDER   — which provider is primary ("opencode_zen" by default)
      - LLM_FALLBACK_PROVIDER  — which provider is fallback ("deepseek" by default)
      - OPENCODE_ZEN_API_KEY   — if empty, primary is skipped
      - DEEPSEEK_API_KEY       — if empty, fallback is skipped

    round35 §19 Gap D 处置（2026-08-24 登记）：admin UI 经 ``core/config_manager``
    写入 DB 的 key 覆盖**不经此函数生效**——provider 配置在启动期从 settings 单例
    读取，运行时改 key 需重启。UI 改 key 后请重启后端（restart-only，显式登记
    而非静默失效）；如需热生效须把本函数改为经 ConfigManager 读值（另立项）。
    """
    providers: list[ProviderConfig] = []
    primary_id = (settings.llm_primary_provider or "").strip().lower()

    # ── Primary: OpenCode Zen ──────────────────────────────────
    if primary_id == "opencode_zen":
        if settings.opencode_zen_api_key:
            # §19: 目录池可用 → 随机候选序列；空池回退静态单候选（_zen_candidates）
            providers.extend(_zen_candidates())
        else:
            logger.info("[provider] Primary provider 'opencode_zen' skipped "
                        "(OPENCODE_ZEN_API_KEY not configured)")

    # ── 中间层: OpenRouter 免费池（§19.9：Zen 整层耗尽后的溢出层，参数量降序）──
    # 目录空（未刷新/无 key/全过滤）→ 本层不挂载，链路退回双层现状。
    if primary_id == "opencode_zen" and settings.openrouter_api_key:
        from .llm.model_catalog import model_catalog as _catalog

        or_url = settings.openrouter_api_url or "https://openrouter.ai/api/v1/chat/completions"
        for e in _catalog.openrouter_pool():
            providers.append(ProviderConfig(
                id="openrouter",
                name="OpenRouter Free",
                api_url=or_url,
                api_key=settings.openrouter_api_key,
                model=e.model,
                timeout=settings.llm_primary_timeout,
                # §19.1 探针实证：OR 标准 OpenAI 格式，无需 Zen 式 reasoning_effort 特判
                reasoning_effort=None,
            ))

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
            # round35 feed-fix: DeepSeek V4 强制思考，官方 API 亦需 reasoning_effort
            reasoning_effort=_reasoning_effort_for_model(models),
        ))
    else:
        logger.info("[provider] Fallback provider 'deepseek' skipped "
                    "(DEEPSEEK_API_KEY not configured)")

    return providers


def has_any_api_key() -> bool:
    """Check if at least one provider has an API key configured."""
    return bool(settings.opencode_zen_api_key or settings.deepseek_api_key)

# round35 §19 GapE: 死代码 call_with_failover 已删——全后端零生产引用（failover
# 循环内联在 analysis/llm/client.py 三入口），仅历史测试引用（已随删）。
