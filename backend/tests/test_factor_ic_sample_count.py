"""
O6 (docs/archived/round8-rediagnosis.md §7 P6-新): /factors/active 每条含非空 sample_count。

P2-1: /factors/ic 已删除，IC 数据并入 /factors/active（categories[].factors[] 含
sample_count）。此测试改测 get_active_factors() 的扁平化结果。
"""
import json

import pytest
from unittest.mock import patch

from app.routers import factors as factors_router


class TestFactorIcSampleCount:
    @pytest.mark.asyncio
    async def test_ic_sample_count_not_none(self):
        """/factors/active 每条 IC 记录含非空 sample_count（来自 registry._sample_counts）。"""
        fake_ic = {"technical.ma.sma_5": 0.0321, "technical.rsi.rsi_14": -0.0210}
        fake_counts = {"technical.ma.sma_5": 42, "technical.rsi.rsi_14": 37}
        factors_router._CACHE.clear()
        try:
            with patch.object(factors_router.registry, "_last_ic_batch", fake_ic), \
                 patch.object(factors_router.registry, "_sample_counts", fake_counts), \
                 patch.object(factors_router.registry, "_last_computed_at", "2026-08-07T10:00:00Z"):
                resp = await factors_router.get_active_factors()
                data = json.loads(resp.body) if isinstance(resp.body, bytes) else resp.body

            factors = [f for cat in data.get("categories", []) for f in cat.get("factors", [])]
            assert factors, "IC 列表不应为空"
            for f in factors:
                assert f["sample_count"] is not None
                assert f["sample_count"] >= 0
            sma = next(f for f in factors if f["code"] == "technical.ma.sma_5")
            assert sma["sample_count"] == 42
        finally:
            # 清除 patch 期间填充的 /factors/active 缓存，避免污染后续测试（P2-1 教训）
            factors_router._CACHE.clear()
