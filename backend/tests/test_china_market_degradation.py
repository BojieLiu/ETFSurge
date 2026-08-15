from __future__ import annotations
# -*- coding: utf-8 -*-
"""F21 R77/R78：china_market 多源熔断降级链自动化测试。

R77 缺口 1/2/3/5/6（route 化链路）+ 缺口 4（指数链 route-ify 熔断用例）：
每类断言：① 熔断源被跳过；② 降级源输出非空且数据正确；③ 成功源 record_success、
失败源 record_failure；④ 全失败返回 []/None + 调用方兜底。
R78：provider 返回 (data, 200) 正常成功、(data, 0) 非 HTTP 成功。
"""
import pytest

from app.fetchers import china_market
from app.core import source_registry


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    """每个用例独立 registry，避免熔断状态串扰。"""
    reg = source_registry.SourceRegistry()
    monkeypatch.setattr(china_market, "registry", reg)
    return reg


def _make_provider(name, data, fail=False, tuple_status=None):
    def _fn():
        if fail:
            raise RuntimeError(f"{name} 熔断")
        if tuple_status is not None:
            return (data, tuple_status)
        return data
    _fn.__name__ = f"provider_{name}"
    return _fn


def test_route_skips_broken_source_and_uses_next(monkeypatch):
    """R77 缺口1: 熔断源被 route 跳过（不被调用），降级源输出。"""
    called = {"sina": 0, "mootdx": 0}
    orig = china_market.registry

    def _sina():
        called["sina"] += 1
        return [{"symbol": "000001", "price": 3200.0}]

    def _mootdx():
        called["mootdx"] += 1
        return [{"symbol": "000001", "price": 3200.1}]

    # 手动让 sina 进入 cooldown（模拟已熔断）
    monkeypatch.setattr(china_market.registry.health("sina"), "_cool_until", 10**10)
    result = china_market.registry.route(
        [("sina", _sina), ("mootdx", _mootdx)],
        route_name="test_skip", operation="realtime", target="X",
    )
    assert called["sina"] == 0, "熔断源不得被调用"
    assert called["mootdx"] == 1
    assert result[0]["price"] == 3200.1


def test_route_records_success_and_failure(monkeypatch):
    """R77 缺口3: 成功源 record_success、失败源 record_failure。"""
    reg = china_market.registry
    _sina = _make_provider("sina", None, fail=True)
    _mootdx = _make_provider("mootdx", {"ok": 1})
    result = reg.route([("sina", _sina), ("mootdx", _mootdx)],
                       route_name="t3", operation="realtime", target="Y")
    assert result == {"ok": 1}
    # 快失败检测：duration_ms<500ms 自动转硬失败 → 直接冷却（_failures 重置为 0）
    assert reg.health("sina")._cool_until > 0, "失败源应已进入冷却"
    assert reg.health("mootdx")._cool_until == 0, "成功源不应冷却"


def test_route_all_fail_returns_none(monkeypatch):
    """R77 缺口5/6: 全链熔断 → None（调用方自行兜底）。"""
    reg = china_market.registry
    result = reg.route(
        [("sina", _make_provider("sina", None, fail=True)),
         ("mootdx", _make_provider("mootdx", None, fail=True))],
        route_name="t4", operation="realtime", target="Z",
    )
    assert result is None


def test_fetch_index_realtime_routeified(monkeypatch):
    """R77 缺口4: fetch_index_realtime 走 registry.route——Sina 失败自动降级 mootdx。"""
    reg = china_market.registry
    monkeypatch.setattr(china_market, "registry", reg)

    def _sina_broken(*a, **k):
        raise RuntimeError("sina 超时")

    def _mootdx_ok(*a, **k):
        import pandas as pd
        return pd.DataFrame([
            {"code": "000001", "price": 3200.5, "last_close": 3180.0,
             "volume": 1000, "open": 3190.0, "high": 3210.0, "low": 3185.0},
        ])

    monkeypatch.setattr(china_market, "_sina_realtime", _sina_broken)
    monkeypatch.setattr(china_market, "_mootdx", lambda: type("C", (), {"index": _mootdx_ok})())
    monkeypatch.setattr(china_market, "_tencent_realtime", lambda *a, **k: [])

    result = china_market.fetch_index_realtime()
    assert result, "Sina 熔断后 mootdx 必须兜底输出"
    assert result[0]["symbol"] == "000001"
    assert result[0]["price"] == 3200.5
    assert reg.health("sina")._cool_until > 0, "失败源应已冷却"
    assert reg.health("mootdx")._cool_until == 0, "成功源不应冷却"


def test_fetch_index_realtime_all_broken_returns_empty(monkeypatch):
    """R77 缺口4: 指数链全熔断 → []（调用方兜底不崩溃）。"""
    monkeypatch.setattr(china_market, "_sina_realtime",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sina")))
    monkeypatch.setattr(china_market, "_mootdx",
                        lambda: (_ for _ in ()).throw(RuntimeError("mootdx")))
    monkeypatch.setattr(china_market, "_tencent_realtime",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tencent")))
    assert china_market.fetch_index_realtime() == []


def test_fetch_index_realtime_sina_bad_price_skips(monkeypatch):
    """指数 s_sh 前缀校验：Sina 返回股票价（≤100）→ 跳过 Sina 用 mootdx。"""
    monkeypatch.setattr(china_market, "_sina_realtime",
                        lambda *a, **k: [{"symbol": "000001", "price": 10.98}])
    monkeypatch.setattr(china_market, "_mootdx",
                        lambda: type("C", (), {"index": lambda **k: None})())
    monkeypatch.setattr(china_market, "_tencent_realtime",
                        lambda *a, **k: [{"symbol": "000001", "price": 3200.0}])
    result = china_market.fetch_index_realtime()
    assert result[0]["price"] == 3200.0, "Sina 假指数价应被跳过"


# ── R78: 硬冷却分支补全 ──────────────────────────────────────────
def test_route_tuple_data_200_success(monkeypatch):
    """R78: provider 返回 (data, 200) → 正常成功，不计失败。"""
    reg = china_market.registry
    result = reg.route([("sina", _make_provider("sina", {"ok": 1}, tuple_status=200))],
                       route_name="t78a", operation="realtime", target="T")
    assert result == {"ok": 1}
    assert reg.health("sina")._failures == 0


def test_route_tuple_data_0_non_http_success(monkeypatch):
    """R78: provider 返回 (data, 0) 非 HTTP 成功 → 正常成功。"""
    reg = china_market.registry
    result = reg.route([("sina", _make_provider("sina", {"ok": 2}, tuple_status=0))],
                       route_name="t78b", operation="realtime", target="T")
    assert result == {"ok": 2}
    assert reg.health("sina")._failures == 0


def test_route_tuple_data_500_hard_failure(monkeypatch):
    """R78: (None, 500) → 硬失败冷却该源，继续下游。"""
    reg = china_market.registry
    result = reg.route(
        [("sina", _make_provider("sina", None, tuple_status=500)),
         ("mootdx", _make_provider("mootdx", {"ok": 3}))],
        route_name="t78c", operation="realtime", target="T",
    )
    assert result == {"ok": 3}
    # (None, 500) → record_hard_failure：直接冷却（_failures 重置为 0）
    assert reg.health("sina")._cool_until > 0, "HTTP 500 应触发硬冷却"


async def test_get_asset_realtime_index_not_stock_misresolved(monkeypatch):
    """R5: get_asset_realtime('000001','index') 走指数源——不得被 A 股路径
    解析成深市股票（平安银行 11.63）导致指数分析错位数据。"""
    from app.services import market_service
    idx_rows = [{"symbol": "000001", "name": "上证指数", "price": 3832.26,
                 "change_pct": 0.72, "asset_type": "index"}]

    async def _fake_call(fn, *args, timeout=8):
        return idx_rows

    monkeypatch.setattr(market_service, "_call", _fake_call)
    result = await market_service.get_asset_realtime("000001", "index")
    assert result is not None
    assert result["price"] == 3832.26, "指数应返回上证指数点位，而非深市股票价格"
    assert result["name"] == "上证指数"


# ===== folded from test_round19_p4.py =====
import json
import logging
class TestFetchSectorHeatEmPriority:
    """round19 P4-①: fetch_sector_heat_em push2delay 优先 → akshare 兜底。"""

    def test_push2delay_first_akshare_fallback(self, monkeypatch):
        import app.fetchers.sector_fetcher as sf

        em_rows = [
            {"sector_code": "BK1", "sector_name": "半导体", "change_pct": 2.3,
             "amount": 1e9, "lead_stock_code": "", "lead_stock_name": "",
             "lead_stock_chg": None},
        ]
        ak_rows = [{"sector_code": "BK2", "sector_name": "白酒", "change_pct": -1.2,
                    "amount": 5e8, "lead_stock_code": "600519",
                    "lead_stock_name": "茅台", "lead_stock_chg": 1.0}]
        calls = []

        def fake_em(limit=None):
            calls.append("em")
            return em_rows

        def fake_ak():
            calls.append("ak")
            return ak_rows

        monkeypatch.setattr(sf, "fetch_em_industry_sectors", fake_em)
        monkeypatch.setattr(sf, "_ak_industry_sectors", fake_ak)
        # 绕过 cached() 60s TTL（测试内连续两次调用独立场景）
        monkeypatch.setattr(sf, "cached", lambda key, fn, ttl_key: fn())
        out = sf.fetch_sector_heat_em(limit=5)
        assert calls == ["em"], "push2delay 有数据时不应调 akshare"
        assert out and out[0]["name"] == "半导体" and out[0]["change_pct"] == 2.3

        # push2delay 空 → akshare 兜底
        calls.clear()

        def fake_em_empty(limit=None):
            calls.append("em")
            return []

        monkeypatch.setattr(sf, "fetch_em_industry_sectors", fake_em_empty)
        out2 = sf.fetch_sector_heat_em(limit=5)
        assert calls == ["em", "ak"], "push2delay 空时应走 akshare 兜底"
        assert out2[0]["name"] == "白酒"
        assert out2[0]["lead_stocks"][0]["symbol"] == "600519", "akshare 路径保留领涨股"

    def test_both_empty_logs_error(self, monkeypatch, caplog):
        """push2delay + akshare 均空 → ERROR 日志（负向：静默 → FAIL）。"""
        import app.fetchers.sector_fetcher as sf

        monkeypatch.setattr(sf, "fetch_em_industry_sectors", lambda limit=None: [])
        monkeypatch.setattr(sf, "_ak_industry_sectors", lambda: None)
        with caplog.at_level(logging.ERROR, logger="app.fetchers.sector_fetcher"):
            out = sf.fetch_sector_heat_em(limit=5)
        assert out == []
        assert any("均无数据" in r.message for r in caplog.records), "双源均空应打 ERROR 日志"
class TestSectorHeatMapNullChangePct:
    """round19 P4-③: 前端 SectorHeatMap change_pct=null 显示「—」不冒充 0%。"""

    def _src(self):
        import os
        p = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                         "components", "market", "SectorHeatMap.vue")
        if not os.path.exists(p):
            p = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src",
                             "components", "market", "SectorHeatMap.vue")
        return open(p, encoding="utf-8").read()

    def test_null_change_pct_shows_dash(self):
        src = self._src()
        assert "row-change--na" in src, "null 涨跌幅应有「—」占位样式"
        assert "涨跌幅数据源异常" in src, "「—」应有 tooltip 说明"

    def test_degraded_banner_consumed(self):
        src = self._src()
        assert 'v-if="degraded && activeTab === \'heat\'"' in src, "degraded=true 应有提示条"
