# -*- coding: utf-8 -*-
"""F10 R32: indicators/signal 端点 K 线不足时显式 data_available=false。

无网络，mock market_data_hub.get_market_history。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import market as market_router


@pytest.mark.asyncio
async def test_indicators_empty_kline_marked_unavailable(monkeypatch):
    """R32: hist 为空 → data_available=false + reason。"""
    monkeypatch.setattr(market_router.market_data_hub, "get_market_history",
                        AsyncMock(return_value=[]))
    result = await market_router.indicators("688833", "A", "daily")
    assert result["data_available"] is False
    assert "K线数据不足" in result["reason"]


@pytest.mark.asyncio
async def test_indicators_short_kline_marked_unavailable(monkeypatch):
    """R32: hist <30 根 → data_available=false。"""
    hist = [{"date": f"2026-01-{i:02d}", "close": 1.0 + i * 0.01,
             "high": 1.1, "low": 0.9, "volume": 1000} for i in range(10)]
    monkeypatch.setattr(market_router.market_data_hub, "get_market_history",
                        AsyncMock(return_value=hist))
    result = await market_router.indicators("688833", "A", "daily")
    assert result["data_available"] is False


@pytest.mark.asyncio
async def test_indicators_enough_kline_available(monkeypatch):
    """R32: hist >=30 → data_available=true 且含指标。"""
    hist = [{"date": f"2026-01-{i:02d}", "close": 1.0 + i * 0.01,
             "high": 1.1, "low": 0.9, "volume": 1000} for i in range(40)]
    monkeypatch.setattr(market_router.market_data_hub, "get_market_history",
                        AsyncMock(return_value=hist))
    result = await market_router.indicators("510300", "A", "daily")
    assert result["data_available"] is True


@pytest.mark.asyncio
async def test_signal_empty_kline_marked_unavailable(monkeypatch):
    """R32: signal 端点 hist 空 → data_available=false（不输出误导 hold）。"""
    monkeypatch.setattr(market_router.market_data_hub, "get_market_history",
                        AsyncMock(return_value=[]))
    result = await market_router.signal("688833", "A", "daily")
    assert result["data_available"] is False
    assert result.get("signal") is None, "空数据不得输出 hold 信号"
