"""
R5-2-7: akshare 商品接口签名适配（futures_foreign_commodity_realtime 需 symbol 参数）。

旧无参调用 TypeError → 商品恒空。修复后按新签名传常用外盘品种列表。
mock akshare，无网络。
"""
import pandas as pd
from unittest.mock import patch

from app.fetchers import china_market


def test_fetch_futures_passes_symbol_to_akshare(monkeypatch):
    """R5-2-7: futures_foreign_commodity_realtime 以 symbol 列表调用（不再无参 TypeError）。"""
    captured = {}

    def _fake_ak(*args, **kwargs):
        captured["symbol"] = kwargs.get("symbol")
        return pd.DataFrame([
            {"商品": "CL", "名称": "WTI原油", "当前价": 82.5, "涨跌幅": 1.2},
            {"商品": "GC", "名称": "COMEX黄金", "当前价": 2400.0, "涨跌幅": -0.3},
        ])

    with patch.object(china_market, "run_in_thread", lambda fn, timeout=8, executor="long": fn()):
        import akshare as ak
        with patch.object(ak, "futures_foreign_commodity_realtime", side_effect=_fake_ak):
            items = china_market.fetch_futures_realtime()

    assert captured.get("symbol"), "R5-2-7 必须以 symbol 参数调用 akshare（旧无参 TypeError）"
    assert isinstance(captured["symbol"], list) and len(captured["symbol"]) >= 3, \
        f"应传常用外盘品种列表，实际 {captured['symbol']}"
    assert len(items) == 2, f"应返回 2 条商品行情: {items}"
    assert items[0]["symbol"] == "CL"
    assert items[0]["asset_type"] == "futures"
    assert items[1]["price"] == 2400.0


def test_fetch_futures_failure_returns_empty(monkeypatch):
    """失败（源不可用）→ 返回 [] 不抛异常（非交易时段允许为空）。"""
    with patch.object(china_market, "run_in_thread", side_effect=Exception("source down")):
        assert china_market.fetch_futures_realtime() == []
