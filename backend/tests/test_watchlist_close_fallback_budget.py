"""Round34-B4 / known-env-issues §3 修复：watchlist 收盘兜底段加共享截止线。

背景（2026-08-26 深夜降级窗实测）：enrich 主波被外层 wait_for 截断（设计内
5-8s），超时后走 `_watchlist_close_fallback`——Semaphore(3) + 每项 wait_for 3s，
死源日每项烧满 3s → ceil(N/3)×3s ≈ N=15 时 ~15s，且该段无总预算（外层超时
只罩 enrich 不罩兜底）→ 实测 14.5-16.4s。

修复语义：给兜底段传共享截止线；预算耗尽后剩余项**跳过网络等待**直接落
「维护中」诚实行（realtime=None + 显式标注），快路径缓存读取不受限。
"""
import asyncio
import time
from datetime import datetime
from types import SimpleNamespace

import pytest


def _fake_item(i: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=i,
        symbol=f"51030{i}",
        name=f"测试ETF{i}",
        asset_type="A",
        notes="",
        created_at=datetime(2026, 8, 26, 1, 0, 0),
        updated_at=datetime(2026, 8, 26, 1, 0, 0),
    )


@pytest.mark.asyncio
async def test_close_fallback_deadline_bounds_wall_time(monkeypatch):
    """负向断言：12 只标的 × 死源（每项 3s）在旧实现 ≈ ceil(12/3)×3 = 12s；
    预算化后总耗时必须受截止线约束（< 5s），且每行都存在、未拉到行情的行
    落「维护中」语义（realtime=None 或显式标注）而非挂起。"""
    from app.routers import market as market_mod

    async def dead_source(symbol, asset_type):  # 模拟死源：每次烧满 3s
        await asyncio.sleep(3)
        return None

    monkeypatch.setattr(
        "app.services.market_service._last_close_fallback", dead_source
    )

    items = [_fake_item(i) for i in range(12)]
    t0 = time.monotonic()
    rows = await market_mod._watchlist_close_fallback(items, budget_s=2.0)
    elapsed = time.monotonic() - t0

    assert len(rows) == 12, "预算截断不得丢行"
    assert elapsed < 5.0, (
        f"兜底段必须受截止线约束（实际 {elapsed:.1f}s ≥ 旧实现 ~12s 量级）"
    )
    # 未拉到收盘的行：realtime 为 None 或带维护中显式标注（诚实降级，不冒充）
    for r in rows:
        rt = r.get("realtime")
        assert rt is None or rt.get("estimate_source") in (
            "last_close", "last_good", "last_close_cache", "maintenance",
        )


@pytest.mark.asyncio
async def test_close_fallback_fast_source_all_rows_get_realtime(monkeypatch):
    """正路径回归：源健康（立即返回收盘）时全部行拿到 realtime——
    截止线不得误伤正常窗口。"""
    from app.routers import market as market_mod

    async def fast_source(symbol, asset_type):
        return {"price": 4.5, "change_pct": 1.2, "estimate_source": "last_close"}

    monkeypatch.setattr(
        "app.services.market_service._last_close_fallback", fast_source
    )

    items = [_fake_item(i) for i in range(6)]
    rows = await market_mod._watchlist_close_fallback(items, budget_s=8.0)
    assert len(rows) == 6
    for r in rows:
        rt = r.get("realtime")
        assert rt is not None, "健康源下所有行应有收盘数据"
        assert rt.get("price") == 4.5
