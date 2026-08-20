from __future__ import annotations
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
    from app.core import source_registry
    patch_route, captured = _capture_route(market_service, {"price": 313.33})
    with patch_route:
        asyncio_run(market_service._route_us("AAPL"))
    assert captured["providers"] == ["twelvedata", "finnhub", "tickflow"]


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


# ===== folded from test_round19_p9.py =====
import pandas as pd
from unittest.mock import MagicMock
def _us_df(n=500):
    import datetime as dt
    rows = []
    base = dt.date(2024, 1, 1)
    for i in range(n):
        d = base + dt.timedelta(days=i)
        rows.append({"trade_date": d.strftime("%Y-%m-%d"), "open": 100 + i * 0.01,
                     "high": 101 + i * 0.01, "low": 99 + i * 0.01,
                     "close": 100.5 + i * 0.01, "volume": 1e6, "amount": 1e8})
    return pd.DataFrame(rows)
class TestTickflowKlineUsHk:
    """round19 P9-②: _tickflow_kline 支持 US/HK 分支（复用 _tickflow_symbol）。"""

    def _patch_key(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.tickflow_api_key", "tk_test")

    def test_tickflow_kline_us_returns_rows(self, monkeypatch):
        """_tickflow_kline('SPY','US') → 500 行（负向：US 分支不支持 → [] → FAIL）。
        round20 P0-4/P1-5: 输出统一英文 key（date/close...），契约对齐。"""
        from app.fetchers import china_market as cm
        self._patch_key(monkeypatch)
        df = _us_df(500)
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: df)
        rows = cm._tickflow_kline("SPY", "daily")
        assert len(rows) >= 30, f"US 应返回 ≥30 行，实得 {len(rows)}"
        assert rows[0]["close"] == pytest.approx(100.5, rel=1e-6)
        assert rows[-1]["date"]  # 日期非空
        assert "收盘" not in rows[0], "不得输出中文 key（round20 契约对齐）"

    def test_tickflow_kline_hk_symbol_mapped(self, monkeypatch):
        """港股显式后缀 00700.HK → tf_sym=00700.HK（不误映射 SZ）。"""
        from app.fetchers import china_market as cm
        self._patch_key(monkeypatch)
        captured = {}

        class _FakeKlines:
            def get(self, sym, period="1d", count=500, as_dataframe=True):
                captured["sym"] = sym
                return _us_df(30)

        class _FakeTickFlow:
            class TickFlow:
                def __init__(self, api_key):
                    self.klines = _FakeKlines()

        import sys
        monkeypatch.setitem(sys.modules, "tickflow", _FakeTickFlow)
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: fn())
        rows = cm._tickflow_kline("00700.HK", "daily")
        assert captured.get("sym") == "00700.HK", f"HK 应映射为 00700.HK，实得 {captured}"
        assert len(rows) >= 30

    def test_tickflow_kline_exception_returns_empty(self, monkeypatch):
        """TickFlow 抛异常 → []（降级链继续，负向：抛异常中断 → FAIL）。"""
        from app.fetchers import china_market as cm
        self._patch_key(monkeypatch)

        def boom(fn, **k):
            raise RuntimeError("tickflow down")

        monkeypatch.setattr(cm, "run_in_thread", boom)
        assert cm._tickflow_kline("SPY", "daily") == []


# ===== folded from test_round20_strategy_check_p05_p18.py =====
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
class TestP1_9FactorDataQuality:
    def test_degraded_when_valid_rate_low(self, monkeypatch):
        """P1-9/R96: 数据可用率 <60% → factor_data_quality.degraded=True + 降级说明。

        R96 (round31): valid_rate 口径改为「数据可用性」（字段就位率）——IC 未累积
        不再算数据缺失。本用例构造**字段缺口**（_data_source_gaps）使 30/38 因子
        数据不可用 → 可用率 <60% → 降级（负向：数据不可用仍报正常 → FAIL）。
        """
        from app.services import strategy_design as sd
        from app.factors import factor_registry as freg

        # 构造低可用率场景：38 因子，其中 30 个缺 nav 字段（数据源未接入）
        fake_factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(38)}
        fake_ic = {f"test.factor_{i}": None for i in range(38)}  # 全无 IC → no_data
        gaps = {f"test.factor_{i}": ["510300"] for i in range(30)}  # 30/38 字段缺口

        monkeypatch.setattr(freg.registry, "_factors", fake_factors)
        monkeypatch.setattr(freg.registry, "_ic_series_cache", fake_ic)
        monkeypatch.setattr(freg.registry, "_data_source_gaps", gaps)
        monkeypatch.setattr(freg.registry, "_constant_factor_codes", set())
        monkeypatch.setattr(freg.registry, "_sample_counts", {})

        report = sd._factor_data_quality_report()
        assert report["data_available"] == 8, f"可用因子应为 8，实际 {report}"
        assert report["degraded"] is True, f"数据可用率低应降级，实际 {report}"
        assert "降级" in report["note"], "降级时应含降级说明"

    def test_not_degraded_when_valid_high(self, monkeypatch):
        """valid 率 >=60% → 不降级（F25②: 260 交易日 + t≥2 + |IR|≥0.5 才计 valid）。"""
        from app.services import strategy_design as sd
        from app.factors import factor_registry as freg

        fake_factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(10)}
        # 8 个统计显著 IC 序列（均值 ~0.05、低方差 → t 高/IR 高）+ 2 个 no_data。
        # 注意不能用常量序列（std=0 → t=0 不显著），须带微小波动使 NW-t 显著。
        fake_ic = {
            f"test.factor_{i}": [0.05 + (i % 7) * 0.002 for i in range(260)]
            for i in range(8)
        }
        fake_ic.update({f"test.factor_{i}": None for i in range(8, 10)})

        monkeypatch.setattr(freg.registry, "_factors", fake_factors)
        monkeypatch.setattr(freg.registry, "_ic_series_cache", fake_ic)
        monkeypatch.setattr(freg.registry, "_data_source_gaps", {})
        monkeypatch.setattr(freg.registry, "_constant_factor_codes", set())
        # F25②: 样本 ≥ MIN_TRADING_DAYS(250) + 序列统计显著 → valid
        monkeypatch.setattr(freg.registry, "_sample_counts",
                            {f"test.factor_{i}": 260 for i in range(8)})

        report = sd._factor_data_quality_report()
        assert report["valid"] >= 8, f"显著因子数应 ≥8，实际 {report}"
        assert report["valid_rate"] >= 0.6, f"valid 率应 ≥0.6，实际 {report}"
        assert report["degraded"] is False
