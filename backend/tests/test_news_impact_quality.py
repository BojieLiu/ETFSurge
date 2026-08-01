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
