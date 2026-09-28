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

    monkeypatch.setattr(llm.reports, "_fetch_global_liquidity", _fake_fetch)
    monkeypatch.setattr(llm.reports, "get_agent", lambda name: _FakeAgent())

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

# ── R07 (round58 §1 M6): 商品名别名映射（油价整段丢失修复）──────────────────
# M6 根因：fetch_futures_realtime 经 akshare 外盘返回英文/代码名（WTI/布伦特/CL…），
# _format_commodities 旧实现只按中文名过滤 6 品种 → 全部对不上 → 油价缺失。


def test_r07_wti_maps_to_crude_line():
    """R07 核心：WTI 英文名输入 → 渲染为「原油」行（旧实现会整段丢失）。"""
    from app.analysis.llm.reports import _format_commodities
    out = _format_commodities([
        {"name": "WTI", "price": 70.5, "change_pct": 1.2},
        {"name": "GC", "price": 2650.0, "change_pct": -0.3},
    ])
    assert "原油" in out and "70.5" in out
    assert "黄金" in out and "2650.0" in out
    assert "WTI" not in out, "英文原始名未归一（下游 LLM 认不出品种）"


def test_r07_alias_covers_brent_cl_si_hg():
    """R07: 布伦特/CL/SI/HG 均须归一到规范中文名。"""
    from app.analysis.llm.reports import _format_commodities
    out = _format_commodities([
        {"name": "布伦特", "price": 74.0, "change_pct": 0.5},
        {"name": "CL", "price": 71.0, "change_pct": 0.4},
        {"name": "SI", "price": 31.0, "change_pct": 2.0},
        {"name": "HG", "price": 4.5, "change_pct": -0.8},
    ])
    for canon in ("原油", "白银", "铜"):
        assert canon in out, f"{canon} 未归一：{out}"


def test_r07_unmatched_names_fall_back_to_first_six():
    """R07 兼容：对不上任何别名时回退前 6 条（旧行为，不丢数据）。"""
    from app.analysis.llm.reports import _format_commodities
    rows = [{"name": f"品种{i}", "price": float(i), "change_pct": 0.0} for i in range(9)]
    out = _format_commodities(rows)
    assert out.count("- ") == 6
    assert "品种5" in out and "品种6" not in out


def test_r07_empty_commodities_returns_empty_string():
    """R07 负向：空列表 → 空串（调用方渲染「（暂无数据）」，不抛异常）。"""
    from app.analysis.llm.reports import _format_commodities
    assert _format_commodities([]) == ""


def test_r07_market_report_not_blocked_when_all_empty():
    """R07 负向验收：商品全空时主报告 prompt 仍正常生成（不阻断主报告）。"""
    from app.analysis.llm import _build_report_prompt
    p = _build_report_prompt(
        indices=[], commodities=[], market_data=[], indicators={},
        news=[], macro_news=[],
    )
    assert "大宗商品" in p
    assert "（暂无数据）" in p
    assert "请生成一份市场环境研判报告" in p
