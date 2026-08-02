"""
P1-5 (R4-23): 海外流动性数据接入（FRED 接线）。

- _fetch_global_liquidity: 采集美债10Y/VIX/联邦基金利率；任一失败静默、全失败 None。
- _build_report_prompt: 有 global_liquidity 时注入「### 海外流动性」段；
  无数据时不出现该段（不影响主报告）。
- generate_market_report: 未显式传入时内部默认采集。
- llm_context.build_full_context: context["global_liquidity"] 采集。

mock FRED fetcher，无网络。
"""

import pytest

from app.analysis import llm
from app.analysis.llm import (
    _build_report_prompt,
    _fetch_global_liquidity,
    generate_market_report,
)


@pytest.mark.asyncio
async def test_fetch_global_liquidity_all_available(monkeypatch):
    """P1-5: 三个 FRED 指标全部可用 → dict。"""

    async def _fake_10y():
        return 4.68

    async def _fake_vix():
        return 17.09

    async def _fake_fed():
        return 3.63

    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_us_10y", _fake_10y)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_vix", _fake_vix)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_fed_rate", _fake_fed)

    gl = await _fetch_global_liquidity()
    assert gl == {"us_10y": 4.68, "vix": 17.09, "fed_rate": 3.63}


@pytest.mark.asyncio
async def test_fetch_global_liquidity_partial_failure(monkeypatch):
    """P1-5: 单指标失败静默（该键不注入），其余保留。"""

    async def _fake_10y():
        return 4.68

    async def _fake_vix():
        raise RuntimeError("FRED down")

    async def _fake_fed():
        return 3.63

    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_us_10y", _fake_10y)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_vix", _fake_vix)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_fed_rate", _fake_fed)

    gl = await _fetch_global_liquidity()
    assert gl == {"us_10y": 4.68, "fed_rate": 3.63}
    assert "vix" not in gl


@pytest.mark.asyncio
async def test_fetch_global_liquidity_all_failed_none(monkeypatch):
    """P1-5: 全失败 → None（不注入，不影响主报告）。"""

    async def _fail():
        raise RuntimeError("FRED down")

    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_us_10y", _fail)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_vix", _fail)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_fed_rate", _fail)

    assert await _fetch_global_liquidity() is None


def test_build_report_prompt_injects_liquidity_section():
    """P1-5: prompt 注入「### 海外流动性」段（含真实数值）。"""
    gl = {"us_10y": 4.68, "vix": 17.09, "fed_rate": 3.63}
    prompt = _build_report_prompt([], [], [], {}, [], [], market="A",
                                  global_liquidity=gl)
    assert "### 海外流动性" in prompt
    assert "美债10年期收益率: 4.68%" in prompt
    assert "VIX恐慌指数: 17.09" in prompt
    assert "联邦基金利率: 3.63%" in prompt


def test_build_report_prompt_no_liquidity_section_when_none():
    """P1-5: global_liquidity=None 时不出现海外流动性段。"""
    prompt = _build_report_prompt([], [], [], {}, [], [], market="A",
                                  global_liquidity=None)
    assert "### 海外流动性" not in prompt


@pytest.mark.asyncio
async def test_generate_market_report_default_fetch(monkeypatch):
    """P1-5: generate_market_report 未传时内部默认采集并注入 prompt。"""
    captured = {}

    async def _fake_fetch():
        return {"us_10y": 4.68, "vix": 17.09, "fed_rate": 3.63}

    class _FakeAgent:
        async def run(self, prompt):
            captured["prompt"] = prompt
            return "OK"

    monkeypatch.setattr(llm, "_fetch_global_liquidity", _fake_fetch)
    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent())

    await generate_market_report([], [], [], {}, [], [], market="A")
    assert "### 海外流动性" in captured["prompt"]
    assert "美债10年期收益率: 4.68%" in captured["prompt"]


@pytest.mark.asyncio
async def test_build_full_context_collects_liquidity(monkeypatch):
    """P1-5: build_full_context 采集 context['global_liquidity']（失败静默）。"""
    from app.services import llm_context

    async def _fake_10y():
        return 4.68

    async def _fake_vix():
        return 17.09

    async def _fake_fed():
        return 3.63

    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_us_10y", _fake_10y)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_vix", _fake_vix)
    monkeypatch.setattr("app.fetchers.global_markets_fetcher.fetch_fed_rate", _fake_fed)

    class _Hub:
        async def get_all_realtime(self):
            return []

        def get_market_regime(self, market="A"):
            return "range_bound"

        def get_market_sentiment(self):
            return {}

        def get_index_realtime(self):
            return []

        def get_news_headlines(self):
            return []

        def get_news_macro(self):
            return []

        def get_commodities(self):
            return []

    ctx = await llm_context.build_full_context(
        _Hub(), market="A",
        include_indices=False, include_sectors=False, include_news=False,
        include_fund_flow=False, include_commodities=False,
    )
    assert ctx.get("global_liquidity") == {"us_10y": 4.68, "vix": 17.09, "fed_rate": 3.63}
