# -*- coding: utf-8 -*-
"""F21 R77/R78：china_market 多源熔断降级链自动化测试。

R77 缺口 1/2/3/5/6（route 化链路）+ 缺口 4（指数链 route-ify 熔断用例）：
每类断言：① 熔断源被跳过；② 降级源输出非空且数据正确；③ 成功源 record_success、
失败源 record_failure；④ 全失败返回 []/None + 调用方兜底。
R78：provider 返回 (data, 200) 正常成功、(data, 0) 非 HTTP 成功。
"""
import pytest

from app.fetchers import china_market
from app.services import source_registry


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
    monkeypatch.setattr(china_market.registry._health("sina"), "_cool_until", 10**10)
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
    assert reg._health("sina")._cool_until > 0, "失败源应已进入冷却"
    assert reg._health("mootdx")._cool_until == 0, "成功源不应冷却"


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
    """R77 缺口4: fetch_index_realtime 走 registry.route——Sina 失败自动降级 tencent。"""
    reg = china_market.registry
    monkeypatch.setattr(china_market, "registry", reg)

    def _sina_broken(*a, **k):
        raise RuntimeError("sina 超时")

    monkeypatch.setattr(china_market, "_sina_realtime", _sina_broken)
    monkeypatch.setattr(china_market, "_tencent_realtime",
                        lambda *a, **k: [{"symbol": "000001", "price": 3200.5, "change_pct": 0.64}])

    result = china_market.fetch_index_realtime()
    assert result, "Sina 熔断后 tencent 必须兜底输出"
    assert result[0]["symbol"] == "000001"
    assert result[0]["price"] == 3200.5
    assert reg._health("sina")._cool_until > 0, "失败源应已冷却"
    assert reg._health("tencent")._cool_until == 0, "成功源不应冷却"


def test_fetch_index_realtime_all_broken_returns_empty(monkeypatch):
    """R77 缺口4: 指数链全熔断 → []（调用方兜底不崩溃）。"""
    monkeypatch.setattr(china_market, "_sina_realtime",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sina")))
    monkeypatch.setattr(china_market, "_tencent_realtime",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tencent")))
    assert china_market.fetch_index_realtime() == []


def test_fetch_index_realtime_sina_bad_price_skips(monkeypatch):
    """指数 s_sh 前缀校验：Sina 返回股票价（≤100）→ 跳过 Sina 用 tencent。"""
    monkeypatch.setattr(china_market, "_sina_realtime",
                        lambda *a, **k: [{"symbol": "000001", "price": 10.98}])
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
    assert reg._health("sina")._failures == 0


def test_route_tuple_data_0_non_http_success(monkeypatch):
    """R78: provider 返回 (data, 0) 非 HTTP 成功 → 正常成功。"""
    reg = china_market.registry
    result = reg.route([("sina", _make_provider("sina", {"ok": 2}, tuple_status=0))],
                       route_name="t78b", operation="realtime", target="T")
    assert result == {"ok": 2}
    assert reg._health("sina")._failures == 0


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
    assert reg._health("sina")._cool_until > 0, "HTTP 500 应触发硬冷却"


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
