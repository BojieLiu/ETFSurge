"""
N09 (round3-diagnosis-and-optimization-plan.md N09): 拼音搜索无数据。

- collect_all: 失败段打 ERROR 日志 + 每段行数统计（旧仅 WARN print）。
- sync: 全量替换前校验至少一段成功——全部段失败时保留旧表
  （旧代码无条件 delete+add_all：akshare 熔断 → instruments 表被清空只剩 0 行）。

无网络，mock 数据源。
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from scripts import sync_instruments as si


def _row(symbol, name, market="A", asset_type="stock"):
    return {"symbol": symbol, "name": name, "market": market,
            "asset_type": asset_type, "pinyin": "", "first_letter": ""}


class TestCollectAllSegments:
    @pytest.mark.asyncio
    async def test_partial_segment_failure_logs_error(self, caplog):
        """N09: 部分段失败打 ERROR，成功段数据保留。"""
        call_n = {"n": 0}

        async def _side(*a, **kw):
            call_n["n"] += 1
            if call_n["n"] == 2:
                raise ConnectionError("akshare down")
            # 段1 返回 A 股个股、段3 返回港股（不同 symbol 避免去重合并）
            return [_row("600519", "贵州茅台")] if call_n["n"] == 1 \
                else [_row("00700", "腾讯控股", market="HK")]

        # 3 段：段1/段3 成功、段2 失败
        with patch.object(si, "_fetch_akshare_list", side_effect=_side):
            with caplog.at_level(logging.ERROR):
                rows = await si.collect_all()

        assert len(rows) == 2, "成功段数据应保留（段1+段3）"
        syms = {r["symbol"] for r in rows}
        assert syms == {"600519", "00700"}, f"两段数据都应保留: {syms}"
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("segment" in m and "FAILED" in m for m in error_msgs), \
            "失败段必须打 ERROR 日志（N09）"

    @pytest.mark.asyncio
    async def test_all_segments_fail_returns_empty(self):
        """N09: 全部段失败 → 返回空（sync 据此保留旧表）。"""
        async def _fail(*a, **kw):
            raise ConnectionError("all down")

        with patch.object(si, "_fetch_akshare_list", side_effect=_fail):
            rows = await si.collect_all()
        assert rows == []


class TestSyncKeepTable:
    @pytest.mark.asyncio
    async def test_sync_keeps_table_when_all_fail(self):
        """N09: 全部段失败 → 不执行 delete(Instrument)（保留旧表）。"""
        with patch.object(si, "collect_all", new=AsyncMock(return_value=[])), \
             patch("app.database.init_db", new=AsyncMock()), \
             patch("app.database.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_ctx.return_value = mock_session

            await si.sync()

        # delete 不应被调用（保留旧表）
        executed = [c.args[0] for c in mock_session.execute.await_args_list]
        assert not any("delete" in str(a).lower() for a in executed if a is not None), \
            "全部段失败时不得执行 delete（旧 bug：表被清空）"

    @pytest.mark.asyncio
    async def test_sync_replaces_when_data_ok(self):
        """N09 回归: 数据正常时仍全量替换。"""
        rows = [_row("600519", "贵州茅台"), _row("510300", "沪深300ETF", asset_type="etf")]
        with patch.object(si, "collect_all", new=AsyncMock(return_value=rows)), \
             patch("app.database.init_db", new=AsyncMock()), \
             patch("app.database.async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_ctx.return_value = mock_session

            await si.sync()

        executed = [c.args[0] for c in mock_session.execute.await_args_list]
        assert any("delete" in str(a).lower() for a in executed if a is not None), \
            "数据正常时应全量替换（delete + add_all）"
        assert mock_session.add_all.call_count == 1
        assert len(mock_session.add_all.call_args[0][0]) == 2
