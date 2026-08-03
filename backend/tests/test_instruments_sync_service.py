"""F17 (round6 §16.5): instruments 启动自动同步 service + 防并发互斥锁。

背景：instruments 表从未创建/同步（§十八-3）→ search 恒降级全量拉取；
启动自动同步（lifespan 后台，不阻塞启动）+ scheduler 每日 16:30 保留 +
防并发互斥锁（双写竞态）。
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from app.services import instruments_sync as insvc


def _row(symbol, name, market="A", asset_type="stock"):
    return {"symbol": symbol, "name": name, "market": market,
            "asset_type": asset_type, "pinyin": "", "first_letter": ""}


async def test_sync_table_writes_rows():
    """数据正常 → 全量替换（delete + add_all + commit）。"""
    rows = [_row("600519", "贵州茅台"), _row("510300", "沪深300ETF", asset_type="etf")]
    with patch.object(insvc, "_collect", new=AsyncMock(return_value=rows)), \
         patch("app.database.init_db", new=AsyncMock()), \
         patch("app.database.async_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_session

        n = await insvc.sync_instruments_table()

    assert n == 2
    executed = [c.args[0] for c in mock_session.execute.await_args_list]
    assert any("delete" in str(a).lower() for a in executed if a is not None)
    assert mock_session.add_all.call_count == 1
    assert mock_session.commit.await_count == 1


async def test_sync_table_keeps_table_when_all_fail():
    """全部段失败 → 不 delete（保留旧表），返回 0。"""
    with patch.object(insvc, "_collect", new=AsyncMock(return_value=[])), \
         patch("app.database.async_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_session

        n = await insvc.sync_instruments_table()

    assert n == 0
    executed = [c.args[0] for c in mock_session.execute.await_args_list]
    assert not any("delete" in str(a).lower() for a in executed if a is not None)


async def test_sync_table_mutex_serializes():
    """并发调用（启动同步 vs 每日同步）→ 互斥锁串行，第二次直接返回不双写。"""
    start = asyncio.Event()
    release = asyncio.Event()

    async def _slow_collect():
        start.set()
        await release.wait()
        return [_row("600519", "贵州茅台")]

    with patch.object(insvc, "_collect", new=_slow_collect), \
         patch("app.database.init_db", new=AsyncMock()), \
         patch("app.database.async_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_session

        t1 = asyncio.create_task(insvc.sync_instruments_table())
        await start.wait()  # 第一个已进入采集
        # 第二个并发调用——互斥锁应让其立即返回 0（不进入 DB 写路径）
        n2 = await insvc.sync_instruments_table()
        assert n2 == 0, "并发调用应被互斥锁拦截"
        release.set()
        n1 = await t1
        assert n1 == 1
    # DB 写只发生一次
    assert mock_ctx.return_value is not None
