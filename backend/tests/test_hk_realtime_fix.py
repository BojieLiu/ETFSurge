"""TDD: F1-1/F1-2 — 港股/单只 A 股 realtime 降级链修复。

覆盖：
  1. _sina_realtime HK 分支用 rt_hk 前缀（此前 sz00700 恒空）
  2. _tencent_realtime HK 分支用 hk 前缀 + 返回符号与请求一致（含 .HK）
  3. _em_hk_realtime 匹配带 .HK 后缀的请求
  4. fetch_hk_stock_realtime tencent 返回空结构 → 继续降级 dongfang
  5. fetch_a_stock_realtime 降级链含 tencent（mootdx→tencent→sina）
"""
import pytest
from unittest.mock import patch, MagicMock


# ── 1. _sina_realtime HK 前缀 ──────────────────────────────────

def test_sina_realtime_hk_prefix(monkeypatch):
    """HK 请求应拼 rt_hk00700（而非 sz00700）。"""
    from app.fetchers import china_market

    captured = {}

    class _FakeResp:
        text = (
            'var hq_str_rt_hk00700="腾讯控股,320.000,319.800,321.000,'
            '323.000,318.600,321.400,322.000,50000000,16000000000,'
            '0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0";'
        )

    class _FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=10):
            captured["url"] = url
            return _FakeResp()

    monkeypatch.setattr(china_market, "_session", lambda: _FakeSession())
    result = china_market._sina_realtime(["00700.HK"], "HK")
    assert "rt_hk00700" in captured["url"], f"URL 应为 rt_hk 前缀: {captured['url']}"
    assert result and result[0]["symbol"] == "00700.HK"
    assert result[0]["price"] > 0


# ── 2. _tencent_realtime HK 前缀与符号归一化 ───────────────────

def test_tencent_realtime_hk_prefix_and_symbol(monkeypatch):
    """HK 请求应拼 hk00700，返回 symbol 与请求一致（00700.HK）。"""
    from app.fetchers import china_market

    captured = {}

    class _FakeResp:
        text = (
            'v_hk00700="200~腾讯控股~00700~320.000~319.800~321.000~'
            '50000000~0~16000000000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
            '0~0~0~0~0~0~0~0~1.000~0.313~0~0~320.000~0~0~0";'
        )

    class _FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=10):
            captured["url"] = url
            return _FakeResp()

    monkeypatch.setattr(china_market, "_session", lambda: _FakeSession())
    result = china_market._tencent_realtime(["00700.HK"], "HK")
    assert "hk00700" in captured["url"], f"URL 应为 hk 前缀: {captured['url']}"
    assert result and result[0]["symbol"] == "00700.HK", f"symbol 应与请求一致: {result}"
    assert result[0]["price"] > 0


def test_tencent_realtime_a_prefix_unchanged(monkeypatch):
    """A 股 tencent 前缀不受影响（sh/sz 逻辑保持）。"""
    from app.fetchers import china_market

    captured = {}

    class _FakeResp:
        text = (
            'v_sh600519="1~贵州茅台~600519~1500.000~1490.000~1505.000~'
            '3000000~0~4500000000~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
            '0~0~0~0~0~0~0~0~0.670~0.450~0~0~1500.000~0~0~0";'
        )

    class _FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=10):
            captured["url"] = url
            return _FakeResp()

    monkeypatch.setattr(china_market, "_session", lambda: _FakeSession())
    result = china_market._tencent_realtime(["600519"], "A")
    assert "sh600519" in captured["url"]
    assert result and result[0]["symbol"] == "600519"


# ── 3. _em_hk_realtime 匹配 .HK 请求 ───────────────────────────

def test_em_hk_realtime_matches_dot_hk(monkeypatch):
    """东方财富 fallback 应匹配带 .HK 后缀的请求。"""
    from app.fetchers import china_market

    hk_rows = [
        {"代码": "00700", "名称": "腾讯控股", "最新价": 320.0, "涨跌幅": 0.31,
         "成交量": 5e7, "成交额": 1.6e10},
        {"代码": "02800", "名称": "盈富基金", "最新价": 20.0, "涨跌幅": -0.5,
         "成交量": 1e7, "成交额": 2e8},
    ]
    monkeypatch.setattr(china_market.sync_memory_cache, "get", lambda k: None)
    monkeypatch.setattr(china_market.sync_memory_cache, "set", lambda *a, **k: None)
    monkeypatch.setattr(china_market, "run_in_thread", lambda fn, *a, **k: None)
    # 让 _p() 直接返回 DataFrame
    import pandas as pd
    monkeypatch.setattr(
        china_market, "run_in_thread",
        lambda fn, *a, **k: pd.DataFrame(hk_rows),
    )
    result = china_market._em_hk_realtime(["00700.HK", "02800"])
    syms = [r["symbol"] for r in result]
    assert "00700.HK" in syms, f"应匹配 .HK 请求: {syms}"
    assert "02800" in syms


# ── 4. fetch_hk_stock_realtime 降级到 dongfang ─────────────────

@pytest.mark.asyncio
async def test_fetch_hk_stock_realtime_falls_back_to_dongfang(monkeypatch):
    """tencent 返回空结构（价格 0）→ 继续降级 dongfang。"""
    from app.fetchers import china_market

    monkeypatch.setattr(china_market, "_sina_realtime", lambda s, t: [])
    monkeypatch.setattr(china_market, "_tencent_realtime",
                        lambda s, t: [{"symbol": s[0], "price": 0, "name": ""}])
    monkeypatch.setattr(china_market, "_em_hk_realtime",
                        lambda s: [{"symbol": s[0], "price": 88.8, "name": "腾讯控股",
                                    "change_pct": 1.2, "asset_type": "HK"}])
    monkeypatch.setattr(china_market.registry, "route",
                        lambda routes, **kw: next(
                            (r for name, fn in routes if (r := fn()) and any(
                                isinstance(i, dict) and i.get("price", 0) > 0 for i in r
                            )), None))
    result = china_market.fetch_hk_stock_realtime("00700.HK")
    assert result and result[0]["price"] == 88.8
    assert result[0]["symbol"] == "00700.HK"


# ── 5. fetch_a_stock_realtime 含 tencent 降级 ──────────────────

def test_fetch_a_stock_realtime_has_tencent_branch(monkeypatch):
    """单只 A 股降级链应含 tencent（mootdx→tencent→sina）。"""
    from app.fetchers import china_market

    seen = []

    def _fake_route(routes, **kw):
        for name, fn in routes:
            seen.append(name)
        return None

    monkeypatch.setattr(china_market.registry, "route", _fake_route)
    china_market.fetch_a_stock_realtime("510300")
    assert "tencent" in seen, f"降级链应含 tencent: {seen}"
    assert seen.index("mootdx") < seen.index("tencent") < seen.index("sina")


def test_normalize_hk_symbol():
    """_normalize_hk_symbol 去后缀转大写。"""
    from app.fetchers.china_market import _normalize_hk_symbol
    assert _normalize_hk_symbol("00700.HK") == "00700"
    assert _normalize_hk_symbol("02800.hk") == "02800"
    assert _normalize_hk_symbol("00700") == "00700"
