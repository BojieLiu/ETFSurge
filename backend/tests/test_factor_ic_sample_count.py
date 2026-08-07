"""
O6 (docs/archived/round8-rediagnosis.md §7 P6-新): /factors/ic 每条含非空 sample_count。

现状: factors.py:359 硬编码 "sample_count": None——IC 列表无样本量/显著性信息。
registry._sample_counts 已在 compute() 填充（line 1437），端点直接读取即可。
"""

import pytest
from unittest.mock import patch

from app.routers import factors as factors_router


class TestFactorIcSampleCount:
    @pytest.mark.asyncio
    async def test_ic_sample_count_not_none(self):
        """/factors/ic 每条 IC 记录含非空 sample_count（来自 registry._sample_counts）。"""
        fake_ic = {"technical.ma.sma_5": 0.0321, "technical.rsi.rsi_14": -0.0210}
        fake_counts = {"technical.ma.sma_5": 42, "technical.rsi.rsi_14": 37}
        factors_router._CACHE.clear()
        with patch.object(factors_router.registry, "_last_ic_batch", fake_ic), \
             patch.object(factors_router.registry, "_sample_counts", fake_counts), \
             patch.object(factors_router.registry, "_last_computed_at", "2026-08-07T10:00:00Z"):
            resp = await factors_router.get_factor_ic()
            import json
            data = json.loads(resp.body) if isinstance(resp.body, bytes) else resp.body

        assert data["factors"], "IC 列表不应为空"
        for f in data["factors"]:
            assert f["sample_count"] is not None
            assert f["sample_count"] >= 0
        sma = next(f for f in data["factors"] if f["code"] == "technical.ma.sma_5")
        assert sma["sample_count"] == 42
