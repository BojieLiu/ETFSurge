"""round25 Q2/Q3 (round26 关联): 港股 K 线一致性校验收紧——不误删真实数据。

问题（round26 §1 Q2/Q3 实证）：HK chart 部分标的 0 行（00700/09988/03690/01810）、
部分 320 行（02318/00939）。market_service.get_history 的 HK 一致性校验（O2）在
close 或 high 任一与实时价差 >50% 时**整链丢弃**——实时源返 stale/错位价时把真实
K 线一并误删。

修复（round25 §12.1 Q2/Q3）：close 与 high **双双**偏离 >50% 才判源错误丢弃；
单字段漂移不再整链误杀；剔除前必打 WARNING 日志（可查）。
"""

from unittest.mock import AsyncMock, patch

import pytest


def _rows(closes=(470.0, 480.0, 485.0), highs=(472.0, 481.0, 486.0)):
    """构造 K 线行；默认最后一根 close=485 / 全序列 max high=486。"""
    out = []
    for i, (c, h) in enumerate(zip(closes, highs)):
        out.append({"date": f"2026-08-{12 + i}", "open": c - 10.0, "close": c,
                    "high": h, "low": c - 12.0})
    return out


class TestHkConsistencyGuard:
    """Q2/Q3: 一致性校验仅双双偏离才丢弃。"""

    @pytest.mark.asyncio
    async def test_both_close_and_high_off_discards(self):
        """close 与 high 均差 >50%（9.49 vs 492.2 类符号错位）→ 丢弃（真源错误）。"""
        from app.services import market_service as ms

        rows = _rows(closes=(9.1, 9.3, 9.49), highs=(9.2, 9.4, 9.6))
        with patch.object(ms, "_call", new=AsyncMock(
                side_effect=[rows, [{"symbol": "X", "price": 492.2}]])), \
             patch("app.services.market_data_hub.market_data_hub.get_kline_rows", return_value=None):
            out = await ms.get_history("X", "HK", "daily")
        assert out == [], "双双偏离 >50% 应丢弃（防符号错位失真 K 线）"

    @pytest.mark.asyncio
    async def test_close_only_off_keeps_rows(self):
        """仅 close 偏离 >50%（max high 界内，实时价 stale）→ 保留（Q2/Q3 不误删）。"""
        from app.services import market_service as ms

        # last_close=485 vs realtime 300 → 61.7% 超；max high=440 vs 300 → 46.7% 不超
        rows = _rows(highs=(430.0, 435.0, 440.0))
        with patch.object(ms, "_call", new=AsyncMock(
                side_effect=[rows, [{"symbol": "X", "price": 300.0}]])), \
             patch("app.services.market_data_hub.market_data_hub.get_kline_rows", return_value=None):
            out = await ms.get_history("X", "HK", "daily")
        assert len(out) == 3, "仅 close 偏离（max high 界内）→ 保留真实 K 线（Q2/Q3）"

    @pytest.mark.asyncio
    async def test_high_only_off_keeps_rows(self):
        """仅 high 偏离（close 界内）→ 保留。"""
        from app.services import market_service as ms

        # last_close=200 vs realtime 300 → 33.3% 不超；max high=486 vs 300 → 62% 超
        rows = _rows(closes=(195.0, 198.0, 200.0), highs=(470.0, 480.0, 486.0))
        with patch.object(ms, "_call", new=AsyncMock(
                side_effect=[rows, [{"symbol": "X", "price": 300.0}]])), \
             patch("app.services.market_data_hub.market_data_hub.get_kline_rows", return_value=None):
            out = await ms.get_history("X", "HK", "daily")
        assert len(out) == 3, "仅 high 偏离（close 界内）→ 保留真实 K 线"

    @pytest.mark.asyncio
    async def test_realtime_missing_keeps_rows(self):
        """实时价取不到 → 跳过校验，保留 K 线（旧行为不变）。"""
        from app.services import market_service as ms

        with patch.object(ms, "_call", new=AsyncMock(
                side_effect=[_rows(), []])), \
             patch("app.services.market_data_hub.market_data_hub.get_kline_rows", return_value=None):
            out = await ms.get_history("X", "HK", "daily")
        assert len(out) == 3, "实时源缺失不得误删 K 线"

    @pytest.mark.asyncio
    async def test_discard_logs_warning(self):
        """剔除时必打 WARNING 日志（验收口径：一致性校验剔除时有日志可查）。"""
        import logging
        from app.services import market_service as ms

        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r.getMessage())
        logger = logging.getLogger("app.services.market_service")
        logger.addHandler(handler)
        try:
            rows = _rows(closes=(9.1, 9.3, 9.49), highs=(9.2, 9.4, 9.6))
            with patch.object(ms, "_call", new=AsyncMock(
                    side_effect=[rows, [{"symbol": "X", "price": 492.2}]])), \
                 patch("app.services.market_data_hub.market_data_hub.get_kline_rows", return_value=None):
                await ms.get_history("X", "HK", "daily")
        finally:
            logger.removeHandler(handler)
        assert any("inconsistent" in r for r in records), "剔除必须留 WARNING 日志（Q2/Q3 验收）"