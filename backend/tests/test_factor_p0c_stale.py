# -*- coding: utf-8 -*-
"""round10 P0-C: factor_registry.compute K 线多级降级 + stale 兜底 + data_source 标注。

验收口径（docs/round10-container-rediagnosis.md §10 P0-C）：
- 容器弱源下 filled 不再骤降（有 stale 缓存时走缓存兜底，data_source='stale'）
- 无缓存冷启动全空 → 明示「数据源不可用」（data_source='unavailable'）
"""
import pytest
from unittest.mock import patch, AsyncMock

import app.factors.factor_registry as fr
from app.factors.factor_registry import FactorRegistry


@pytest.fixture(autouse=True)
def _clean_kline_cache():
    fr._kline_cache.clear()
    fr._kline_cache_ts = 0.0
    yield
    fr._kline_cache.clear()


def _kline_cols():
    """30 根日线的列式 dict（与 _fetch_market_data 输出一致）。"""
    import time
    dates = [f"2026-06-{i+1:02d}" for i in range(30)]
    closes = [1.0 + i * 0.01 for i in range(30)]
    return {
        "date": dates,
        "close": closes,
        "open": closes,
        "high": [c + 0.05 for c in closes],
        "low": [c - 0.05 for c in closes],
        "volume": [1000] * 30,
        "date_int": [int(time.mktime(time.strptime(d, "%Y-%m-%d"))) for d in dates],
    }


@pytest.mark.asyncio
async def test_compute_stale_fallback_when_live_empty():
    """live 空 → 走 _kline_cache 缓存兜底，结果带 data_source='stale'。"""
    reg = FactorRegistry()
    fr._set_kline_cache({"510300": _kline_cols()})

    with patch.object(
        reg, "_fetch_market_data", new_callable=AsyncMock, return_value={}
    ):
        out = await reg.compute(["510300"], codes=["technical.ma.sma_5"])

    assert out["510300"]["data_source"] == "stale"
    # 缓存兜底后 sma_5 应为真实正值（close 单调递增 → sma_5 > 0）
    assert out["510300"].get("technical.ma.sma_5", 0) > 0


@pytest.mark.asyncio
async def test_compute_stale_fallback_when_live_fetch_error():
    """live 为 _fetch_error dict（非空但不可用）→ 同样走 stale 兜底。"""
    reg = FactorRegistry()
    fr._set_kline_cache({"518880": _kline_cols()})

    with patch.object(
        reg, "_fetch_market_data", new_callable=AsyncMock,
        return_value={"518880": {"_fetch_error": "EM TLS blocked"}},
    ):
        out = await reg.compute(["518880"], codes=["technical.ma.sma_5"])

    assert out["518880"]["data_source"] == "stale"


@pytest.mark.asyncio
async def test_compute_unavailable_when_no_cache():
    """live 空 + 无缓存冷启动 → data_source='unavailable'（明示数据源不可用）。"""
    reg = FactorRegistry()

    with patch.object(
        reg, "_fetch_market_data", new_callable=AsyncMock, return_value={}
    ):
        out = await reg.compute(["159915"], codes=["technical.ma.sma_5"])

    assert out["159915"]["data_source"] == "unavailable"


@pytest.mark.asyncio
async def test_compute_live_data_no_stale_marker():
    """live 数据正常时不标注 stale/unavailable。"""
    reg = FactorRegistry()

    with patch.object(
        reg, "_fetch_market_data", new_callable=AsyncMock,
        return_value={"510300": _kline_cols()},
    ):
        out = await reg.compute(["510300"], codes=["technical.ma.sma_5"])

    assert "data_source" not in out["510300"]
    assert out["510300"].get("technical.ma.sma_5", 0) > 0