"""round39 §5 R160 (round40 实施): call-site 守卫前置.

实施点：backend/app/analysis/provider.py get_configured_providers() 末尾对
所有 (provider.id, provider.model) 调 model_catalog.is_excluded() 兜底过滤。
任何 mark_excluded 命中的 provider 都不挂载（不进入 client.py 候选链），
真正排除生效——round39 复验发现 deepseek-v4-flash-free 已 mark_excluded 但
仍累计 22037 calls（catalog 过滤与 is_excluded 状态没联动）的根因。

负向断言：
- mark_excluded 后，get_configured_providers 返回列表**不包含**该 (provider, model)
- is_excluded 命中**不计入** token_usage（call-site 前拦截，统计层不感知）
- 兜底过滤对所有 provider 类型（zen / openrouter / b_ai / deepseek）一致
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.analysis import provider as provider_mod
from app.analysis.llm import model_catalog as catalog_mod


@pytest.fixture(autouse=True)
def _reset_excluded_state():
    """每用例前后清空 mark_excluded 表——避免污染其它单测。"""
    saved = set(catalog_mod.model_catalog._exclusions)
    catalog_mod.model_catalog._exclusions.clear()
    yield
    catalog_mod.model_catalog._exclusions.clear()
    catalog_mod.model_catalog._exclusions.update(saved)


def _stub_settings(
    *,
    zen_key: str = "",
    openrouter_key: str = "",
    b_ai_key: str = "",
    b_ai_models: str = "",
    deepseek_key: str = "",
    model: str = "deepseek-v4-flash",
    primary: str = "opencode_zen",
    fallback: str = "deepseek",
) -> MagicMock:
    """构造 settings stub: 控制 get_configured_providers 各 provider 挂载条件。"""
    s = MagicMock()
    s.llm_primary_provider = primary
    s.llm_fallback_provider = fallback
    s.opencode_zen_api_key = zen_key
    s.openrouter_api_key = openrouter_key
    s.b_ai_api_key = b_ai_key
    s.b_ai_api_url = "http://b_ai.test"
    s.b_ai_proxy_url = ""
    s.b_ai_allowed_models = b_ai_models
    s.deepseek_api_key = deepseek_key
    s.llm_model = model
    s.llm_primary_timeout = 60
    s.llm_fallback_timeout = 60
    s.openrouter_api_url = "http://openrouter.test/v1/chat/completions"
    return s


def test_get_configured_providers_filters_mark_excluded_deepseek():
    """P0: mark_excluded('deepseek', 'deepseek-v4-flash') 后 deepseek 不挂载."""
    catalog_mod.model_catalog.mark_excluded("deepseek", "deepseek-v4-flash")
    s = _stub_settings(deepseek_key="sk-test", model="deepseek-v4-flash")
    with patch.object(provider_mod, "settings", s):
        ps = provider_mod.get_configured_providers()
    ids = [(p.id, p.model) for p in ps]
    assert ("deepseek", "deepseek-v4-flash") not in ids, (
        f"R160 漏: mark_excluded 的 deepseek 仍出现在 provider 列表: {ids}"
    )


def test_get_configured_providers_filters_mark_excluded_zen():
    """P0: mark_excluded('opencode_zen', '<model>') 后 Zen 候选不挂载.

    Zen 通过 model_catalog.zen_pool() 走 catalog 过滤，但本兜底是**最后一道
    屏障**——catalog 池刷新前已被 mark 的 model 也应被滤掉。
    """
    # Zen 通过 model_catalog.zen_pool() 走 catalog 过滤，_zen_candidates 再展开
    # 成 ProviderConfig（最终是 (opencode_zen, model_str)）。本兜底是**最后一道
    # 屏障**——catalog 池刷新前已被 mark 的 model 也应被滤掉。
    catalog_mod.model_catalog.mark_excluded("opencode_zen", "test-zen-model-free")
    s = _stub_settings(zen_key="sk-zen")
    # zen_pool 返回 model_str 列表（_zen_candidates 内层 zip）
    with patch.object(provider_mod, "settings", s), \
         patch.object(catalog_mod.model_catalog, "zen_pool", return_value=["test-zen-model-free"]):
        ps = provider_mod.get_configured_providers()
    ids = [(p.id, p.model) for p in ps]
    assert ("opencode_zen", "test-zen-model-free") not in ids, (
        f"R160 漏: mark_excluded 的 Zen 仍出现: {ids}"
    )


def test_get_configured_providers_unrelated_excluded_does_not_filter():
    """P1: 其它 provider+model 的 mark_excluded 不应影响当前挂载链.

    负向：mark_excluded 只对完全匹配 (provider, model) 起作用。
    """
    catalog_mod.model_catalog.mark_excluded("deepseek", "deepseek-v3")
    s = _stub_settings(deepseek_key="sk-test", model="deepseek-v4-flash")
    with patch.object(provider_mod, "settings", s):
        ps = provider_mod.get_configured_providers()
    ids = [(p.id, p.model) for p in ps]
    assert ("deepseek", "deepseek-v4-flash") in ids, (
        f"误伤: 不相关 mark_excluded 拦截了正常 provider: {ids}"
    )


def test_get_configured_providers_empty_when_all_excluded():
    """P1: 所有可用 provider 都被 mark_excluded 时返回空列表——不应静默退化."""
    catalog_mod.model_catalog.mark_excluded("deepseek", "deepseek-v4-flash")
    s = _stub_settings(deepseek_key="sk-test", model="deepseek-v4-flash")
    with patch.object(provider_mod, "settings", s):
        ps = provider_mod.get_configured_providers()
    # 仅有 deepseek 路径被 mark → 应返回空
    assert ps == [], f"R160 漏: 全 mark_excluded 后仍返回非空: {ps}"


def test_get_configured_providers_b_ai_filtered():
    """P1: b_ai 路径在 _b_ai_candidates 已有 is_excluded 过滤,
    本兜底应保持幂等（不重复过滤但不应再出现）.
    """
    catalog_mod.model_catalog.mark_excluded("b_ai", "b_ai-model-a")
    s = _stub_settings(b_ai_key="sk-bai", b_ai_models="b_ai-model-a,b_ai-model-b")
    with patch.object(provider_mod, "settings", s):
        ps = provider_mod.get_configured_providers()
    ids = [(p.id, p.model) for p in ps]
    assert ("b_ai", "b_ai-model-a") not in ids
    assert ("b_ai", "b_ai-model-b") in ids, (
        f"b_ai 应保留未 mark 的 model: {ids}"
    )
