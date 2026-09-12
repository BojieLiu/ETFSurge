"""
LLM provider configuration and failover orchestration.

Defines the data model for a single LLM API provider and builds the
priority-ordered provider list from application settings.

Supports a primary → fallback failover chain:
  1. OpenCode Zen (deepseek-v4-flash-free — Zen catalog name, not official)
  2. DeepSeek Official (deepseek-flash, V4.1 canonical since 2026-09-10)
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
    # round40 b.ai: 直连超时需代理 (本机 b.ai 必须经 127.0.0.1:7897);
    # None = 不传 httpx proxy 参数 (其它 provider 行为不变)。
    proxy: str | None = None


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


def _b_ai_candidates() -> list[ProviderConfig]:
    """round40: b.ai 白名单静态模式候选生成。

    选型理由: b.ai /models 返回 44 个模型但无 pricing 字段, 无法纯目录字段筛
    免费; 高端模型 (gpt-5.x / claude / gemini / minimax / kimi) 实际需充值, 调
    用返 403/400。因此采用「白名单 + mark_excluded 兜底」——白名单配置 + key +
    URL 任一缺失则不挂载; mark_excluded (round39 熔断三件套接通) 自动剔除
    永久错误模型 (如 model unavailable / not supported / not available in
    your country / credit insufficient)。

    候选模型挂载顺序按白名单逗号分隔顺序 (与 Zen 的随机序列不同, 确定性
    顺序便于诊断: 同一次启动期始终尝试第一个未被熔断/排除的模型)。
    """
    from .llm.gates import _circuit_allow
    from .llm.model_catalog import model_catalog

    key = (settings.b_ai_api_key or "").strip()
    url = (settings.b_ai_api_url or "").strip()
    proxy = (settings.b_ai_proxy_url or "").strip() or None
    allowed = [s.strip() for s in (settings.b_ai_allowed_models or "").split(",") if s.strip()]

    if not key or not url or not allowed:
        return []

    out: list[ProviderConfig] = []
    for m in allowed:
        # 永久排除 (mark_excluded) 与熔断 OPEN 态都跳过, 与 zen_attempt_sequence
        # 同一模式: 由 round39 熔断三件套维护
        if model_catalog.is_excluded("b_ai", m):
            continue
        if not _circuit_allow("b_ai", m):
            continue
        out.append(ProviderConfig(
            id="b_ai", name="b.ai",
            api_url=url, api_key=key,
            model=m, timeout=settings.llm_primary_timeout,
            # b.ai 暂无强制思考模型 (与 Zen V4 不同); 留 None
            reasoning_effort=None,
            proxy=proxy,
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

    # ── 中间层: b.ai 白名单（round40: 第三方聚合, 需代理, 无 pricing 字段）──
    # 挂载位置: Zen + OpenRouter 之后, DeepSeek 兜底之前.
    # 不依赖 Zen (Zen 缺 key 时 b_ai 仍能独立工作).
    if settings.b_ai_api_key and settings.b_ai_allowed_models:
        providers.extend(_b_ai_candidates())

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
        # 官方正名（2026-09-10 V4.1）：deepseek-flash 为 canonical；
        # deepseek-v4-flash 官方暂收作别名（同模型同计费），此处归一化。
        # 'deepseek-v4-flash-free' 仅对 OpenCode Zen 有效，官方 API 用 deepseek-flash。
        if models in ("deepseek-v4-flash", "deepseek-v4-flash-free"):
            models = "deepseek-flash"
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

    # R160 (round39 §5 方案 B): call-site 守卫前置——所有 provider 在挂载前统一
    # 查 model_catalog.is_excluded() 兜底。Zen / OpenRouter 在 catalog 池刷新时
    # 已过滤（model_catalog._filter_zen/_filter_openrouter），b_ai 在 _b_ai_candidates
    # 内部过滤（line 117），但 deepseek 官方直挂 + 未来新增 provider 容易漏掉——
    # 此处一次性兜底：任何 mark_excluded 命中的 (provider, model) 都不挂载，
    # 真正排除生效。实施前 round39 复验发现 deepseek-v4-flash-free 已 mark
    # excluded 但仍累计 22037 calls（catalog 过滤与 is_excluded 状态没联动）。
    from .llm.model_catalog import model_catalog as _catalog_guard
    providers = [
        p for p in providers
        if not _catalog_guard.is_excluded(p.id, p.model)
    ]
    return providers


def has_any_api_key() -> bool:
    """Check if at least one provider has an API key configured."""
    return bool(settings.opencode_zen_api_key or settings.deepseek_api_key)


# ── R185-A (round53 §11.2 方案 A): 配置热生效 ──────────────────────────
# §11.1 脱节②③: provider 链启动期从 settings 单例构建，UI 保存 DB override 后
# 不生效（须重启）。方案 A: admin 保存后把 CONFIG_ITEMS 内 LLM/数据源 key 的
# DB override 值 patch 回 settings 单例 → 下次 get_configured_providers() 即用
# 新值（provider 链构建逻辑零改动，天然读到新 settings）。R160 语义保留: 熔断/
# mark_excluded 状态不因 key 变更重置（模型级黑名单与 key 无关）。

# CONFIG_ITEMS key → settings 字段（R185-B 补齐后的活跃 LLM key 集合）
_HOT_RELOAD_KEYS: dict[str, str] = {
    "OPENCODE_ZEN_API_KEY": "opencode_zen_api_key",
    "DEEPSEEK_API_KEY": "deepseek_api_key",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "B_AI_API_KEY": "b_ai_api_key",
    "B_AI_ALLOWED_MODELS": "b_ai_allowed_models",
    "B_AI_PROXY_URL": "b_ai_proxy_url",
}


def refresh_provider_chain(config_manager=None) -> list[str]:
    """把 ConfigManager DB override 同步到 settings 单例（热生效）。

    admin PUT /config 保存后调用。返回实际 patch 的 key 列表（无 override 的
    key 不动 .env 值）。失败逐 key 捕获（日志 + 跳过），不阻塞保存响应。
    """
    if config_manager is None:
        from ..core.config_manager import config_manager as _default_mgr
        config_manager = _default_mgr
    applied: list[str] = []
    import asyncio as _asyncio

    for cfg_key, settings_attr in _HOT_RELOAD_KEYS.items():
        try:
            # get() 是 async——运行中事件循环内嵌套跑单次查询（admin handler 上下文）
            try:
                loop = _asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                value = loop.run_until_complete(config_manager.get(cfg_key))
            else:
                value = _asyncio.run(config_manager.get(cfg_key))
        except Exception as e:
            logger.warning("[provider] hot-reload read %s failed: %s", cfg_key, e)
            continue
        if value:
            try:
                setattr(settings, settings_attr, str(value))
                applied.append(cfg_key)
                logger.info("[provider] hot-reload applied %s (settings.%s updated)",
                            cfg_key, settings_attr)
            except Exception as e:
                logger.warning("[provider] hot-reload set %s failed: %s", cfg_key, e)
    return applied

# round35 §19 GapE: 死代码 call_with_failover 已删——全后端零生产引用（failover
# 循环内联在 analysis/llm/client.py 三入口），仅历史测试引用（已随删）。
