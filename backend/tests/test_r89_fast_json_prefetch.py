# -*- coding: utf-8 -*-
"""round30 R89: 冷路径预热 + ETF_FAST_JSON 默认启用。

修复（§14.6）：
  ⑤ ETF_FAST_JSON=1 默认启用（main.py 激活点默认 on，保留 env 显式关闭）；
  ② concept/industry 冷首呼 → 就绪后后台异步预拉（不占 startup 关键路径）；
  ① R85 联动——因子/设计冷路径读 hub 缓存（见 test_r85_factor_hub_cache.py）。

无网络：纯逻辑断言（env 读取 / 任务注册）。
"""
import os
import pytest


class TestFastJsonDefaultOnR89:
    def _fresh_module(self):
        import importlib
        import app.main as main
        importlib.reload(main)
        return main

    def test_default_on_without_env(self, monkeypatch):
        """ETF_FAST_JSON 未设置 → 默认启用。"""
        from app.main import _fast_json_enabled
        monkeypatch.delenv("ETF_FAST_JSON", raising=False)
        assert _fast_json_enabled() is True

    def test_explicit_off(self, monkeypatch):
        """ETF_FAST_JSON=0 → 显式关闭。"""
        from app.main import _fast_json_enabled
        monkeypatch.setenv("ETF_FAST_JSON", "0")
        assert _fast_json_enabled() is False

    def test_explicit_on(self, monkeypatch):
        """ETF_FAST_JSON=1 → 启用。"""
        from app.main import _fast_json_enabled
        monkeypatch.setenv("ETF_FAST_JSON", "1")
        assert _fast_json_enabled() is True


class TestSectorListPrefetchR89:
    @pytest.mark.asyncio
    async def test_prefetch_task_warms_concept_and_industry(self, monkeypatch):
        """后台预拉任务调用 fetch_concept_sectors + fetch_industry_sectors。"""
        from app.main import _warmup_sector_lists

        calls = []
        async def _fake_run_sync_long(call, *args, **kwargs):
            calls.append(call.__name__)
            return [{"sector_code": "BK1", "sector_name": "AI"}]

        # _warmup_sector_lists 内部 `from .core.async_utils import run_sync_long`
        monkeypatch.setattr("app.core.async_utils.run_sync_long", _fake_run_sync_long)
        await _warmup_sector_lists()
        assert "fetch_concept_sectors" in calls
        assert "fetch_industry_sectors" in calls

    @pytest.mark.asyncio
    async def test_prefetch_failure_silent(self, monkeypatch):
        """预拉失败静默（首呼回源兜底，不崩溃）。"""
        from app.main import _warmup_sector_lists

        async def _fake_run_sync_long(call, *args, **kwargs):
            raise RuntimeError("source down")
        monkeypatch.setattr("app.core.async_utils.run_sync_long", _fake_run_sync_long)
        await _warmup_sector_lists()  # 不应抛异常
