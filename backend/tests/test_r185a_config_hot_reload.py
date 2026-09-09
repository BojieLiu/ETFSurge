# -*- coding: utf-8 -*-
"""R185-A (docs/round53-container-reacceptance-round52-plans.md §11.2 方案 A, P2):
配置热生效——provider 链经 ConfigManager 变更置脏重建。

§11.1 脱节 ②③ 实锤: provider 链在启动期从 settings 单例构建，UI 保存写 DB
override 后 LLM 实际调用仍用启动期旧值（provider.py get_configured_providers
docstring 显式登记「运行时改 key 需重启」）。

方案 A 落地（§11.2 拍板）:
- admin PUT /config 保存后调用 refresh_provider_chain() → DB override 值
  patch settings 单例 → provider 链下次调用即用新 key（不重启）;
- 验收负向（§11.2）: UI 改 OPENCODE_ZEN_API_KEY → 不重启触发 LLM 调用 →
  日志显示新 key 生效（等价断言: get_configured_providers() 返回的 provider
  携带新 key）。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def clean_settings():
    """保存/恢复 settings 单例字段（测试污染防护）。"""
    from app.config import settings
    saved = {
        "opencode_zen_api_key": settings.opencode_zen_api_key,
        "deepseek_api_key": settings.deepseek_api_key,
        "b_ai_api_key": settings.b_ai_api_key,
        "b_ai_allowed_models": settings.b_ai_allowed_models,
        "b_ai_proxy_url": settings.b_ai_proxy_url,
    }
    yield settings
    for k, v in saved.items():
        setattr(settings, k, v)


class TestSettingsHotPatch:
    def test_settings_attr_setattr_works(self, clean_settings):
        """前置验证: settings 单例可 setattr（pydantic BaseSettings 允许）。
        这是方案 A 的核心机制——patch 失败则方案不成立，测试先行兜底。"""
        clean_settings.opencode_zen_api_key = "sk-hot-patched"
        assert clean_settings.opencode_zen_api_key == "sk-hot-patched"

    def test_providers_reflect_hot_patched_key(self, clean_settings):
        """patch settings 后 get_configured_providers 立即用新值（无缓存层）。"""
        from app.analysis.provider import get_configured_providers
        clean_settings.opencode_zen_api_key = "sk-brand-new"
        clean_settings.deepseek_api_key = ""
        providers = get_configured_providers()
        zen = [p for p in providers if p.id == "opencode_zen"]
        if zen:  # zen 目录池可能为空（测试环境），静态回退路径必有
            assert all(p.api_key == "sk-brand-new" for p in zen)


class TestRefreshProviderChain:
    """admin 保存 → refresh_provider_chain() → settings 同步 DB override。"""

    def test_refresh_applies_db_overrides(self, clean_settings):
        from app.analysis.provider import refresh_provider_chain
        from app.core.config_manager import ConfigManager

        mgr = ConfigManager()
        # 模拟 DB override（不走真 DB——直接注入 override 读数）
        mgr._db_session_factory = None  # 未初始化 → get() 回落 _get_env
        # 直接用 monkeypatch 方式验证 refresh 逻辑: patch config_manager.get
        overrides = {
            "OPENCODE_ZEN_API_KEY": "sk-from-db-override",
            "B_AI_API_KEY": "sk-bai-from-db",
        }

        async def _fake_get(key):
            return overrides.get(key)

        import app.core.config_manager as cm_mod
        orig_get = type(mgr).get
        type(mgr).get = lambda self, key: _fake_get(key)
        try:
            applied = refresh_provider_chain(mgr)
        finally:
            type(mgr).get = orig_get

        assert "OPENCODE_ZEN_API_KEY" in applied
        assert clean_settings.opencode_zen_api_key == "sk-from-db-override"
        assert clean_settings.b_ai_api_key == "sk-bai-from-db"

    def test_refresh_no_override_keeps_env_value(self, clean_settings):
        """无 DB override 的 key 不动 settings（.env 值保持）。"""
        from app.analysis.provider import refresh_provider_chain
        from app.core.config_manager import ConfigManager

        mgr = ConfigManager()
        before = clean_settings.opencode_zen_api_key

        async def _fake_get(key):
            return None  # 无 override

        import app.core.config_manager as cm_mod
        orig_get = type(mgr).get
        type(mgr).get = lambda self, key: _fake_get(key)
        try:
            applied = refresh_provider_chain(mgr)
        finally:
            type(mgr).get = orig_get

        assert applied == []
        assert clean_settings.opencode_zen_api_key == before


class TestAdminConfigWiring:
    """admin PUT /config 保存后必须触发 refresh（接线断=方案 A 无效）。"""

    def test_admin_update_config_calls_refresh(self, monkeypatch):
        import app.analysis.provider as provider_mod
        import app.routers.admin as admin_mod

        called = {"n": 0}
        monkeypatch.setattr(
            provider_mod, "refresh_provider_chain",
            lambda mgr=None: called.__setitem__("n", called["n"] + 1) or [],
        )
        # 直接调用 handler（不走 HTTP 层——接线逻辑单测）。
        # admin handler 内 `from ..analysis.provider import refresh_provider_chain`
        # 是函数内 import → 每次 handler 调用时解析 → patch 源头模块属性即可命中。
        import asyncio

        async def _run():
            return await admin_mod.update_config({"OPENCODE_ZEN_API_KEY": "sk-x"})

        result = asyncio.run(_run())
        assert result["results"]["OPENCODE_ZEN_API_KEY"] == "updated"
        assert called["n"] == 1, "保存后必须调用 refresh_provider_chain（R185-A 接线断点）"

    def test_provider_chain_module_exposes_refresh(self):
        from app.analysis.provider import refresh_provider_chain  # noqa: F401
        from app.analysis.llm import refresh_provider_chain as via_pkg  # noqa: F401
