# -*- coding: utf-8 -*-
"""F3-2 / F3-3 / F3-7: 搜索精确匹配优先 + 现金仓位收紧 + 自选美股名称。

- F3-2: 跨市场合并前全局精确匹配（SPY 首条为 SPY）；market=A 个股搜索降级到 levistock。
- F3-3: range_bound 市态 balanced 方案现金 ≤ 15%（原 22-32%）。
- F3-7: get_asset_realtime US 分支补 name（静态基座映射）。
"""
import pytest

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ── F3-2: 跨市场合并精确匹配优先 ─────────────────────────────────────────
def test_cross_market_exact_symbol_first(monkeypatch):
    """search?keyword=SPY 首条为 SPY（即使 HK/US 段内还有其他模糊命中）。"""
    from app.routers import market as market_router

    async def fake_search_etf(kw):
        return []  # SPY 非 A 股

    async def fake_search_hk_us(kw, enrich=False, include_stocks=False):
        # 模拟 US 段：模糊命中多个，SPY 不在首位（基座顺序）
        return [
            {"symbol": "SPYD", "name": "SPYD 分红ETF", "market": "US", "asset_type": "US", "type": "etf"},
            {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "market": "US", "asset_type": "US", "type": "etf"},
            {"symbol": "SPX", "name": "标普500指数", "market": "US", "asset_type": "US", "type": "etf"},
        ]

    monkeypatch.setattr(market_router.market_data_hub, "search_etf", fake_search_etf)
    monkeypatch.setattr(market_router, "search_hk_us", fake_search_hk_us)
    monkeypatch.setattr(market_router, "_search_a_stocks", lambda kw: [])

    resp = client.get("/api/v1/market/search?keyword=SPY")
    assert resp.status_code == 200
    items = resp.json()
    assert items and items[0]["symbol"] == "SPY", f"精确匹配应排首位，实际: {items[:2]}"


def test_cross_market_global_sort_applied(monkeypatch):
    """跨市场合并结果经 _sort_search_results 排序（精确代码 tier1 置顶）。"""
    from app.routers import market as market_router

    async def fake_search_etf(kw):
        return [{"symbol": "510050", "name": "上证50ETF", "market": "A", "asset_type": "etf", "type": "etf"}]

    async def fake_search_hk_us(kw, enrich=False, include_stocks=False):
        return [
            {"symbol": "0050", "name": "元大台湾50", "market": "HK", "asset_type": "HK", "type": "etf"},
            {"symbol": "510050.HK", "name": "南方A50", "market": "HK", "asset_type": "HK", "type": "etf"},
        ]

    monkeypatch.setattr(market_router.market_data_hub, "search_etf", fake_search_etf)
    monkeypatch.setattr(market_router, "search_hk_us", fake_search_hk_us)
    monkeypatch.setattr(market_router, "_search_a_stocks", lambda kw: [])

    resp = client.get("/api/v1/market/search?keyword=510050")
    items = resp.json()
    # 精确 symbol 命中（510050）应排在 HK 模糊命中之前
    assert items and items[0]["symbol"] == "510050", f"实际首位: {items[0] if items else None}"


# ── F3-2: market=A 个股降级 levistock ────────────────────────────────────
def test_market_a_stock_levistock_fallback(monkeypatch):
    """instruments 表不可用 → 降级 levistock 返回茅台（而非直接 ETF 模式）。"""
    from app.routers import market as market_router

    class _FakeSessionMaker:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(market_router, "async_session", _FakeSessionMaker())
    monkeypatch.setattr(market_router.market_data_hub, "get_all_stocks", lambda: [
        {"stock_code": "600519", "stock_name": "贵州茅台"},
        {"stock_code": "000001", "stock_name": "平安银行"},
    ])

    resp = client.get("/api/v1/market/search?keyword=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&market=A")
    items = resp.json()
    assert resp.status_code == 200
    assert any(it.get("symbol") == "600519" and it.get("name") == "贵州茅台" for it in items), f"实际: {items[:3]}"


# ── F3-3: range_bound 现金 ≤ 15% ─────────────────────────────────────────
def test_budget_cash_within_15pct():
    """STRATEGY_META 三档 layer_budget 和 ≥ 0.85（现金 ≤ 15%）。"""
    from app.engine.budgets import STRATEGY_META

    for profile, meta in STRATEGY_META.items():
        total = sum(meta["layer_budget"].values())
        cash = 1.0 - total
        assert cash <= 0.1501, f"{profile} 现金 {cash:.1%} > 15%"


def test_range_bound_balanced_cash_limit():
    """range_bound 市态 balanced 方案现金 ≤ 15%（验收：balanced 方案现金 ≤ 15%）。"""
    from app.engine.budgets import dynamic_layer_budget

    budget = dynamic_layer_budget("balanced", "range_bound")
    cash = 1.0 - sum(budget.values())
    assert cash <= 0.1501, f"balanced range_bound 现金 {cash:.1%} 超限"


# ── F3-7: 自选美股名称补全 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_us_realtime_name_filled(monkeypatch):
    """get_asset_realtime US 分支返回数据缺 name 时，从静态基座补全。"""
    from app.services import market_service as ms

    async def fake_route_us(symbol):
        return {"symbol": "SPY", "price": 500.0, "change_pct": 1.0}  # 无 name

    monkeypatch.setattr(ms, "_route_us", fake_route_us)
    data = await ms.get_asset_realtime("SPY", "US")
    assert data is not None
    assert data.get("name"), f"应补全 name，实际: {data}"
    assert "SPY" in data["name"].upper() or "S&P" in data["name"].upper()


@pytest.mark.asyncio
async def test_us_realtime_keeps_existing_name(monkeypatch):
    """US 分支已有 name 时保持原值不覆盖。"""
    from app.services import market_service as ms

    async def fake_route_us(symbol):
        return {"symbol": "AAPL", "name": "Apple Inc.", "price": 180.0}

    monkeypatch.setattr(ms, "_route_us", fake_route_us)
    data = await ms.get_asset_realtime("AAPL", "US")
    assert data["name"] == "Apple Inc."
