"""
round13 §3.2: TickFlow 实时行情尾环。

契约: api-contracts/market/realtime-tickflow.md

- _tickflow_quotes: 字段映射（last_price→price、ext.change_pct→change_pct）
- 无 key 短路返回 []；>5 只拒绝返回 []
- A/HK/US symbol 映射
- 三条降级链尾环: fetch_a_stock_realtime / fetch_hk_stock_realtime / market_service._route_us

mock tickflow 库 + SourceRegistry.route，无网络。
"""
import pytest
from unittest.mock import patch

from app.fetchers import china_market
from app.services import market_service


from app.config import settings as app_settings


def _quote(symbol, last=4.751, prev=4.72, ext=None):
    e = {"change_pct": 0.66, "change_amount": 0.031, "name": "沪深300ETF", "turnover_rate": 0.5}
    if ext is None:
        ext = e
    else:
        ext = dict(ext)  # 调用方显式传 ext（含空 dict = 无扩展字段，完全替换默认）
    return {
        "symbol": symbol, "name": "沪深300ETF", "region": "CN",
        "last_price": last, "prev_close": prev,
        "open": 4.73, "high": 4.76, "low": 4.71,
        "volume": 123456, "amount": 1234567.8,
        "timestamp": 1700000000000, "session": "CLOSED", "ext": ext,
    }


def _patch_quotes(quotes_list):
    class _FakeQuotes:
        def get(self, **kw):
            return quotes_list
    class _FakeClient:
        quotes = _FakeQuotes()
    return patch("tickflow.TickFlow", return_value=_FakeClient())


# ── _tickflow_quotes ──────────────────────────────────────────
def test_tickflow_quotes_field_mapping(monkeypatch):
    """字段映射：last_price→price、ext.change_pct 小数比例→百分比、ext.name→name。"""
    monkeypatch.setattr(app_settings, "tickflow_api_key", "tk_test")
    # ext.change_pct 是小数比例（0.0089 = 0.89%），输出统一百分比
    with _patch_quotes([_quote("510300.SH", ext={"change_pct": 0.0089, "change_amount": 0.031,
                                                 "name": "沪深300ETF", "turnover_rate": 0.5})]), \
         patch.object(china_market, "run_in_thread", lambda fn, timeout=8, executor="long": fn()):
        rows = china_market._tickflow_quotes(["510300"])
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "510300", "返回 symbol 与请求一致"
    assert r["price"] == 4.751
    assert r["previous_close"] == 4.72
    assert r["change_pct"] == pytest.approx(0.89, abs=0.01), "小数比例 ×100 转百分比"
    assert r["change_amount"] == pytest.approx(0.03, abs=0.001)
    assert r["name"] == "沪深300ETF"
    assert r["asset_type"] == "A"


def test_tickflow_quotes_change_pct_fallback(monkeypatch):
    """ext 缺 change_pct → (price-prev_close)/prev_close*100 兜底。"""
    monkeypatch.setattr(app_settings, "tickflow_api_key", "tk_test")
    with _patch_quotes([_quote("AAPL.US", last=100.0, prev=90.0, ext={})]), \
         patch.object(china_market, "run_in_thread", lambda fn, timeout=8, executor="long": fn()):
        rows = china_market._tickflow_quotes(["AAPL"])
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["change_pct"] == pytest.approx(11.11, abs=0.1)
    assert rows[0]["change_amount"] == pytest.approx(10.0)
    assert rows[0]["asset_type"] == "US"


def test_tickflow_quotes_no_key_short_circuit(monkeypatch):
    """无 key → 短路返回 []（不触源）。"""
    monkeypatch.setattr(app_settings, "tickflow_api_key", "")
    with patch("tickflow.TickFlow") as mock_tf:
        rows = china_market._tickflow_quotes(["510300"])
    assert rows == []
    mock_tf.assert_not_called()


def test_tickflow_quotes_batch_over5_rejected(monkeypatch):
    """>5 只 → 拒绝返回 []（免费层 5 只/次上限，诚实降级不拆分）。"""
    monkeypatch.setattr(app_settings, "tickflow_api_key", "tk_test")
    with patch("tickflow.TickFlow") as mock_tf:
        rows = china_market._tickflow_quotes([str(i) for i in range(6)])
    assert rows == []
    mock_tf.assert_not_called()


def test_tickflow_symbol_mapping():
    """symbol 映射：A 5/6→SH、其余→SZ（剥 sh/sz/bj 前缀）；HK→.HK；US→.US。"""
    assert china_market._tickflow_symbol("510300") == "510300.SH"
    assert china_market._tickflow_symbol("159915") == "159915.SZ"
    assert china_market._tickflow_symbol("sh510300") == "510300.SH", "剥 sh 前缀后按 5 开头 → SH"
    assert china_market._tickflow_symbol("00700.HK") == "00700.HK", "显式 .HK 后缀直接使用"
    assert china_market._tickflow_symbol("AAPL") == "AAPL.US"
    assert china_market._tickflow_symbol("spy") == "SPY.US"


# ── 三条降级链尾环 ────────────────────────────────────────────
def _capture_route(module, result):
    captured = {}

    def fake_route(providers, **kw):
        captured["providers"] = [name for name, _ in providers]
        return result

    return patch.object(module.registry, "route", side_effect=fake_route), captured


def test_a_stock_realtime_has_tickflow_tail():
    """fetch_a_stock_realtime 链尾含 tickflow（mootdx → tencent → sina → tickflow）。"""
    patch_route, captured = _capture_route(china_market, None)
    with patch_route:
        china_market.fetch_a_stock_realtime("510300")
    assert captured["providers"][-1] == "tickflow", f"链尾应为 tickflow: {captured['providers']}"
    assert captured["providers"] == ["mootdx", "tencent", "sina", "tickflow"]


def test_hk_stock_realtime_has_tickflow_tail():
    """fetch_hk_stock_realtime 链尾含 tickflow（sina → tencent → dongfang → tickflow）。"""
    patch_route, captured = _capture_route(china_market, None)
    with patch_route:
        china_market.fetch_hk_stock_realtime("00700")
    assert captured["providers"] == ["sina", "tencent", "dongfang", "tickflow"]


def test_route_us_has_tickflow_tail():
    """market_service._route_us 链尾含 tickflow（twelvedata → finnhub → tickflow）。"""
    from app.services import source_registry
    patch_route, captured = _capture_route(market_service, {"price": 313.33})
    with patch_route:
        asyncio_run(market_service._route_us("AAPL"))
    assert captured["providers"] == ["twelvedata", "finnhub", "tickflow"]


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
