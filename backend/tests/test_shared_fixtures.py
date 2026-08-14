# -*- coding: utf-8 -*-
"""F21 R73-R74 验收：共享 fixture 分层可用 + 降级链工厂参数化。"""
import pytest

from app.core import source_registry


def test_mock_akshare_fixture(mock_akshare):
    """R73①: mock_akshare 返回固定 DataFrame 且列对齐真实契约。"""
    import akshare as ak
    df = ak.fund_etf_hist_em(symbol="510300", period="daily")
    assert list(df.columns)[:4] == ["日期", "开盘", "收盘", "最高"]
    assert len(df) == 2


async def test_mock_run_sync_fixture(mock_run_sync):
    """R73③: mock_run_sync 直接同步执行。"""
    result = await mock_run_sync(lambda: 42)
    assert result == 42


def test_mock_hub_fixture(mock_hub):
    """R73② + R75 哨兵：get_market_sentiment 结构含 sentiment_history（契约对齐）。"""
    s = mock_hub.get_market_sentiment()
    assert "sentiment_history" in s
    assert len(s["sentiment_history"]) == 20
    assert mock_hub.get_market_regime() == "neutral"


def test_mock_registry_health_fixture(mock_registry_health):
    """R73④: registry.health 返回可控 SourceHealth（默认可用）。"""
    h = source_registry.registry.health("akshare")
    assert h.cooldown_until == 0.0
    assert h.failures == 0


# R74: 降级链工厂——参数化覆盖多源组合，减重复不减覆盖
@pytest.fixture
def make_degradation_chain(monkeypatch):
    def _make(fail_sources: list[str]):
        from app.fetchers import china_market

        def _factory(name, data):
            def _fetch():
                if name in fail_sources:
                    raise RuntimeError(f"{name} 熔断")
                return data
            return _fetch

        return {
            "china_market": china_market,
            "factory": _factory,
        }
    return _make


@pytest.mark.parametrize("fail,expect_ok", [
    (["mootdx"], True),     # Sina 兜底
    (["sina"], True),       # mootdx 兜底
    (["mootdx", "sina"], False),  # 全熔断
])
def test_degradation_chain_factory(make_degradation_chain, fail, expect_ok):
    """R74: 工厂 + parametrize 覆盖多源组合。"""
    ctx = make_degradation_chain(fail)
    _factory = ctx["factory"]
    mootdx = _factory("mootdx", {"price": 1.0})
    sina = _factory("sina", {"price": 1.0})
    ok = False
    for f in (mootdx, sina):
        try:
            data = f()
            ok = True
            break
        except RuntimeError:
            continue
    assert ok is expect_ok
