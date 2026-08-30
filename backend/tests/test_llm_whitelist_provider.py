"""round40 b.ai provider 接入: 失败单测 (TDD 红)。

设计要点:
- b.ai 走白名单静态模式 (不走 model_catalog 池)
  因为 b.ai /models 无 pricing 字段, 无法纯目录字段筛免费
- 配置项: b_ai_api_key / b_ai_api_url / b_ai_proxy_url / b_ai_allowed_models
- ProviderConfig 扩 proxy 字段 (None = 不传 httpx proxy)
- 挂载条件: key 非空 + 白名单非空 + URL 非空, 三者缺一不挂载
- mark_excluded 接通: 与 round39 熔断三件套同入口 (b.ai 403 永久错误自动摘除)
- 选择序列: 与 zen_attempt_sequence 一致, 无放回随机
"""
from __future__ import annotations

import pytest

from app.analysis import provider as prov_mod
from app.analysis import llm
from app.analysis.provider import (
    LLM_API_URL,
    ProviderConfig,
    _b_ai_candidates,
    get_configured_providers,
)
from app.analysis.llm import model_catalog
from app.analysis.llm.gates import _circuit_allow, reset_circuit
from app.config import settings


# ── fixtures ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate():
    """隔离全局: 清空 catalog 排除表 + 熔断态 + 缓存原配置。"""
    saved = {
        "b_ai_api_key": settings.b_ai_api_key,
        "b_ai_api_url": settings.b_ai_api_url,
        "b_ai_proxy_url": settings.b_ai_proxy_url,
        "b_ai_allowed_models": settings.b_ai_allowed_models,
    }
    model_catalog.model_catalog._exclusions.clear()
    reset_circuit()
    yield
    # 恢复
    for k, v in saved.items():
        setattr(settings, k, v)
    model_catalog.model_catalog._exclusions.clear()
    reset_circuit()


def _set_b_ai(key="sk-test", url="https://api.b.ai/v1/chat/completions",
              proxy="http://127.0.0.1:7897", allowed="deepseek-v4-flash,qwen3.8-flash"):
    settings.b_ai_api_key = key
    settings.b_ai_api_url = url
    settings.b_ai_proxy_url = proxy
    settings.b_ai_allowed_models = allowed


# ── ProviderConfig 扩展 ───────────────────────────────────────


class TestProviderConfigProxyField:
    def test_proxy_default_is_none(self):
        """ProviderConfig 扩 proxy 字段, 默认 None (向后兼容)。"""
        cfg = ProviderConfig(
            id="x", name="x", model="m",
            api_key="k", api_url="http://x/v1/chat/completions",
        )
        assert cfg.proxy is None, "proxy 字段应默认 None, 不破坏既有 ProviderConfig 调用方"

    def test_proxy_can_be_set(self):
        """显式传 proxy 不报错。"""
        cfg = ProviderConfig(
            id="b_ai", name="b.ai", model="deepseek-v4-flash",
            api_key="sk-x", api_url="https://api.b.ai/v1/chat/completions",
            proxy="http://127.0.0.1:7897",
        )
        assert cfg.proxy == "http://127.0.0.1:7897"


# ── _b_ai_candidates 配置驱动的挂载 ──────────────────────────────


class TestBAICandidatesGating:
    def test_no_key_no_candidates(self):
        """key 为空 → 返回空列表, 不挂载。"""
        settings.b_ai_api_key = ""
        settings.b_ai_api_url = "https://api.b.ai/v1/chat/completions"
        settings.b_ai_allowed_models = "deepseek-v4-flash"
        assert _b_ai_candidates() == []

    def test_no_url_no_candidates(self):
        """url 为空 → 返回空列表。"""
        settings.b_ai_api_key = "sk-x"
        settings.b_ai_api_url = ""
        settings.b_ai_allowed_models = "deepseek-v4-flash"
        assert _b_ai_candidates() == []

    def test_no_allowed_models_no_candidates(self):
        """白名单空 → 返回空列表 (无配置白名单 = 不挂载)。"""
        _set_b_ai(allowed="")
        assert _b_ai_candidates() == []

    def test_full_config_produces_candidates(self):
        """key+url+白名单都齐 → 返回 N 个 ProviderConfig (N=白名单数)。"""
        _set_b_ai(allowed="deepseek-v4-flash,qwen3.8-flash,glm-5.3-flash")
        cands = _b_ai_candidates()
        assert len(cands) == 3
        for c in cands:
            assert c.id == "b_ai"
            assert c.proxy == "http://127.0.0.1:7897"
        models = [c.model for c in cands]
        assert "deepseek-v4-flash" in models
        assert "qwen3.8-flash" in models
        assert "glm-5.3-flash" in models

    def test_excluded_model_filtered_out(self):
        """mark_excluded 的 model 不进 candidates (与 zen_attempt_sequence is_blocked 一致)。"""
        _set_b_ai(allowed="deepseek-v4-flash,qwen3.8-flash")
        model_catalog.model_catalog.mark_excluded("b_ai", "qwen3.8-flash")
        cands = _b_ai_candidates()
        models = [c.model for c in cands]
        assert "deepseek-v4-flash" in models
        assert "qwen3.8-flash" not in models

    def test_circuit_blocked_model_filtered_out(self):
        """熔断 OPEN 态的 model 不进 candidates。"""
        from app.analysis.llm.gates import _circuit_record_failure

        _set_b_ai(allowed="deepseek-v4-flash,qwen3.8-flash")
        # 让 deepseek-v4-flash 熔断
        _circuit_record_failure("b_ai", is_quota_error=True, model="deepseek-v4-flash")
        cands = _b_ai_candidates()
        models = [c.model for c in cands]
        assert "deepseek-v4-flash" not in models
        assert "qwen3.8-flash" in models

    def test_whitespace_handling(self):
        """白名单带空格/空段应被清洗。"""
        _set_b_ai(allowed="deepseek-v4-flash, , qwen3.8-flash , ")
        cands = _b_ai_candidates()
        models = [c.model for c in cands]
        assert "deepseek-v4-flash" in models
        assert "qwen3.8-flash" in models
        assert "" not in models
        assert len(cands) == 2


# ── get_configured_providers 挂载点 ─────────────────────────────


class TestGetConfiguredProvidersMountsBAI:
    def test_no_key_not_mounted(self):
        """b_ai key 缺 → get_configured_providers 不挂载 b_ai。"""
        _set_b_ai(key="")
        providers = get_configured_providers()
        ids = [p.id for p in providers]
        assert "b_ai" not in ids

    def test_key_present_mounted_between_zen_and_deepseek(self):
        """b_ai 挂载位置: Zen 之后、DeepSeek 兜底之前 (中间层)。"""
        settings.opencode_zen_api_key = "sk-zen"
        settings.deepseek_api_key = "sk-ds"
        _set_b_ai(allowed="deepseek-v4-flash,qwen3.8-flash")
        providers = get_configured_providers()
        ids = [p.id for p in providers]
        # 期望: opencode_zen (#1) → b_ai (#2, #3) → deepseek (#4)
        assert "opencode_zen" in ids
        assert "deepseek" in ids
        # b_ai 必须在 deepseek 之前
        b_ai_idx = ids.index("b_ai")
        deepseek_idx = ids.index("deepseek")
        assert b_ai_idx < deepseek_idx, f"b_ai 应在 deepseek 之前; 实际顺序: {ids}"

    def test_no_allowed_models_means_no_mount(self):
        """白名单空 → 即使 key+url 都有也不挂载 (避免无意义请求)。"""
        _set_b_ai(allowed="")
        providers = get_configured_providers()
        ids = [p.id for p in providers]
        assert "b_ai" not in ids

    def test_no_opencode_zen_means_b_ai_still_works(self):
        """Zen 缺 key 时 b_ai 仍能挂载 (b_ai 是独立中间层, 不依赖 Zen)。"""
        settings.opencode_zen_api_key = ""
        settings.deepseek_api_key = "sk-ds"
        _set_b_ai(allowed="deepseek-v4-flash")
        providers = get_configured_providers()
        ids = [p.id for p in providers]
        assert "opencode_zen" not in ids
        assert "b_ai" in ids
        assert "deepseek" in ids
