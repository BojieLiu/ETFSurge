# -*- coding: utf-8 -*-
"""F2-9: 资讯 AI 分析质量约束（§9.9.4 后端 3 用例）。

prompt 硬约束「无直接关联须明确声明『无直接影响』，禁止强行关联」。
"""
import pytest

from app.analysis import llm


# ── 1. 无直接关联须明确声明 ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_direct_link_explicitly_says(monkeypatch):
    """prompt 含硬约束；LLM 返回含「无直接影响」时透传。"""
    captured = {}

    def fake_run_json(prompt):
        captured["prompt"] = prompt
        return {
            "impact_scope": "无直接影响",
            "affected_holdings": [],
            "summary": "该新闻与组合内标的无直接影响。",
        }

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    res = await llm.analyze_news_impact(
        {"title": "某地出台自然保护条例", "content": "与金融市场无直接关联。"},
        [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3}],
    )
    # 硬约束文案必须在 prompt 中
    assert "无直接影响" in captured["prompt"]
    assert "禁止强行关联" in captured["prompt"]
    # LLM 声明透传
    assert res["impact_scope"] == "无直接影响"


# ── 2. 无关新闻不强行塞满持仓 ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_irrelevant_news_not_forced_into_holdings(monkeypatch):
    """LLM 只列 1 只相关标的 → affected_holdings 不强行覆盖全部持仓。"""
    holdings = [
        {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3},
        {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.2},
        {"symbol": "159516", "name": "半导体ETF", "target_weight": 0.15},
    ]

    def fake_run_json(prompt):
        return {
            "impact_scope": "半导体板块",
            "affected_holdings": [
                {"symbol": "159516", "name": "半导体ETF", "impact_reason": "直接相关"}
            ],
            "summary": "仅半导体产业链受直接冲击。",
        }

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    res = await llm.analyze_news_impact(
        {"title": "某半导体工厂停产", "content": "影响芯片供给。"}, holdings
    )
    assert len(res["affected_holdings"]) == 1
    assert res["affected_holdings"][0]["symbol"] == "159516"


# ── 3. 组合为空 → 市场整体分析（回归） ───────────────────────────────────
@pytest.mark.asyncio
async def test_empty_portfolio_market_scope(monkeypatch):
    """portfolio 为空 → impact_scope 为市场整体（Z32 分支不回归）。"""
    captured = {}

    def fake_run_json(prompt):
        captured["prompt"] = prompt
        return {
            "impact_scope": "对市场整体影响有限",
            "affected_holdings": [],
            "summary": "市场整体影响分析。",
        }

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    res = await llm.analyze_news_impact(
        {"title": "央行降准", "content": "释放流动性。"}, []
    )
    assert "无持仓" in captured["prompt"]
    assert res["impact_scope"].startswith("对市场整体")


class _FakeAgent:
    def __init__(self, run_json):
        self._run_json = run_json

    async def run_json(self, prompt):
        return self._run_json(prompt)


# ── F14 R48/R49: LLM 幻觉持仓过滤 + prompt 代码清单 ────────────────────
@pytest.mark.asyncio
async def test_whitelist_filters_fabricated_holdings(monkeypatch, caplog):
    """R48: 返回前过滤 affected_holdings——仅保留 symbol ∈ 传入 holdings 代码集。

    LLM 虚构 512880/512800（组合外）→ 被过滤并记 WARNING 日志。
    """
    import logging

    holdings = [{"symbol": "159338", "name": "中证A500ETF", "target_weight": 0.4}]

    def fake_run_json(prompt):
        return {
            "impact_scope": "银行/证券板块",
            "affected_holdings": [
                {"symbol": "159338", "name": "中证A500ETF", "impact_reason": "宽基受益"},
                {"symbol": "512880", "name": "证券ETF", "impact_reason": "幻觉标的"},
                {"symbol": "512800", "name": "银行ETF", "impact_reason": "幻觉标的"},
            ],
            "summary": "利好宽基。",
        }

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    with caplog.at_level(logging.WARNING, logger="app.analysis.llm"):
        res = await llm.analyze_news_impact(
            {"title": "四部门发文", "content": "严禁金融机构向股东利益输送。"}, holdings
        )

    assert [h["symbol"] for h in res["affected_holdings"]] == ["159338"]
    assert any("虚构" in r.message and "2" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_whitelist_no_holdings_no_filter(monkeypatch):
    """R48: 组合为空 → 不过滤（affected_holdings 原样透传）。"""
    def fake_run_json(prompt):
        return {
            "impact_scope": "市场整体",
            "affected_holdings": [],
            "summary": "市场影响有限。",
        }

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    res = await llm.analyze_news_impact({"title": "t", "content": "c"}, [])
    assert res["affected_holdings"] == []


@pytest.mark.asyncio
async def test_prompt_contains_explicit_code_list(monkeypatch):
    """R49: prompt 含显式代码清单（affected_holdings 只能从清单选）。"""
    captured = {}

    def fake_run_json(prompt):
        captured["prompt"] = prompt
        return {"impact_scope": "x", "affected_holdings": [], "summary": "y"}

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    await llm.analyze_news_impact(
        {"title": "t", "content": "c"},
        [{"symbol": "159338", "name": "A500", "target_weight": 0.4},
         {"symbol": "518880", "name": "黄金", "target_weight": 0.2}],
    )
    assert "当前组合持仓代码" in captured["prompt"]
    assert "159338, 518880" in captured["prompt"]
    assert "不得新增任何代码" in captured["prompt"]


# ── F13 R46: prompt 注入市场上下文（regime/指数/板块） ──────────────────
@pytest.mark.asyncio
async def test_market_context_injected_when_provided(monkeypatch):
    """R46: 传入 market_context → prompt 含市场背景段。"""
    captured = {}

    def fake_run_json(prompt):
        captured["prompt"] = prompt
        return {"impact_scope": "x", "affected_holdings": [], "summary": "y"}

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    await llm.analyze_news_impact(
        {"title": "t", "content": "c"},
        [{"symbol": "159338", "name": "A500", "target_weight": 0.4}],
        market_context={
            "market_regime": {"regime": "震荡市", "confidence": "中"},
            "indices": [{"symbol": "000300", "name": "沪深300", "price": 3800.5}],
        },
    )
    assert "当前市场背景" in captured["prompt"]
    assert "震荡市" in captured["prompt"]
    assert "3800.5" in captured["prompt"]


@pytest.mark.asyncio
async def test_market_context_omitted_no_background(monkeypatch):
    """R46: 不传 market_context → prompt 无市场背景段（纯函数回归）。"""
    captured = {}

    def fake_run_json(prompt):
        captured["prompt"] = prompt
        return {"impact_scope": "x", "affected_holdings": [], "summary": "y"}

    monkeypatch.setattr(llm, "get_agent", lambda name: _FakeAgent(fake_run_json))
    await llm.analyze_news_impact(
        {"title": "t", "content": "c"},
        [{"symbol": "159338", "name": "A500", "target_weight": 0.4}],
    )
    assert "当前市场背景" not in captured["prompt"]
