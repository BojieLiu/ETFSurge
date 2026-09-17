# -*- coding: utf-8 -*-
"""L1 v2 P1-4: valuation 意图端到端（mock LLM/上下文/估值源，无网络）.

契约: api-contracts/analysis/advice-valuation.md §6、§8.
- valuation 问 → prompt 含估值表 + SSE 含 fetching_valuation phase.
- 非 valuation 问 → 不触估值源（hub mock 若被调直接抛错）.
- 估值源异常 → 降级：prompt 含“不得下低估/高估结论”.
- ETF 映射只出白名单码（product 子任务）.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.analysis.llm import _build_advice_stream_prompt as _real_prompt


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev["event"] = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    ev["data"] = json.loads(line[6:])
                except json.JSONDecodeError:
                    ev["data"] = line[6:]
        if ev:
            events.append(ev)
    return events


@pytest.fixture
def mocks(monkeypatch):
    """mock LLM 流 + 上下文 + 估值源；记录喂给 prompt 的 ctx 与文本."""
    seen = {}

    async def _fake_stream(*args, **kwargs):
        yield {"type": "token", "token": "测试"}
        yield {"type": "done", "full_text": "测试回复", "usage": {}}

    async def _fake_ctx(*args, **kwargs):
        return {"index_realtime": [], "sector_momentum": [], "news": [],
                "market_regime": "range_bound", "market_sentiment": {},
                "fund_flow": {}}

    def _recording_prompt(query, ctx):
        seen["ctx"] = dict(ctx)
        out = _real_prompt(query, ctx)
        seen["prompt"] = out
        return out

    from app.services.market_data_hub import market_data_hub as hub
    # AgentRuntime.run_stream 用的是 app/analysis/runtime.py:18 綁定的引用，
    # patch client 属性拦不住——必须打 runtime 命名空间（旧 fixture 同型问题）。
    monkeypatch.setattr("app.analysis.runtime.llm_complete_stream",
                        _fake_stream)
    monkeypatch.setattr("app.routers.analysis.build_full_context", _fake_ctx)
    # router 系函数内 `from ..analysis.llm import _build_advice_stream_prompt`
    # ——调用时才从包属性解析，故 patch 包级属性（router 模块级无此名）。
    monkeypatch.setattr("app.analysis.llm._build_advice_stream_prompt",
                        _recording_prompt)
    monkeypatch.setattr(
        hub, "get_index_valuation",
        lambda sym: [{"date": "2026-09-16", "pe_1": 14.6, "pe_2": 16.82,
                      "div_1": 2.63, "div_2": 2.34}])
    monkeypatch.setattr(
        hub, "get_valuation_history",
        lambda kind, key, col: [14.6, 14.5, 14.4, 14.3, 14.2])
    monkeypatch.setattr(
        hub, "get_sector_valuation",
        lambda date=None: [{"ind_code": "C39", "ind_name": "计算机",
                            "pe_wavg": 20.5, "pe_median": 35.2,
                            "pe_avg": 40.1, "as_of": "2026-09-16"}])
    return seen


def _post(client, query):
    resp = client.post("/api/v1/analysis/llm-advice/stream",
                       json={"query": query, "market": "A"})
    assert resp.status_code == 200, resp.text[:200]
    return _parse_sse(resp.text)


def test_valuation_query_injects_table_and_phase(client, mocks):
    events = _post(client, "现在有哪些板块低估了？")
    assert mocks["ctx"]["valuation_intent"] is True
    assert len(mocks["ctx"]["index_valuation"]) == 5  # 5 个宽基
    assert mocks["ctx"]["index_valuation"][0]["symbol"] == "000300"
    assert "估值快照" in mocks["prompt"]
    assert "14.60" in mocks["prompt"]
    assert "待验" in mocks["prompt"]  # v1 无 ROE 不下结论
    phases = [e["data"].get("phase") for e in events
              if e["event"] == "progress"]
    assert "fetching_valuation" in phases


def test_non_valuation_query_skips_source(client, mocks, monkeypatch):
    from app.services.market_data_hub import market_data_hub as hub

    def _boom(*a, **k):
        raise AssertionError("非 valuation 意图不得触估值源")

    monkeypatch.setattr(hub, "get_index_valuation", _boom)
    monkeypatch.setattr(hub, "get_sector_valuation", _boom)
    _post(client, "当前市场风格是成长还是价值？")
    assert mocks["ctx"]["valuation_intent"] is False
    assert mocks["ctx"]["index_valuation"] == []
    assert "估值快照" not in mocks["prompt"]


def test_valuation_source_failure_degrades(client, mocks, monkeypatch):
    from app.services.market_data_hub import market_data_hub as hub
    monkeypatch.setattr(hub, "get_index_valuation",
                        lambda sym: (_ for _ in ()).throw(Exception("down")))
    monkeypatch.setattr(hub, "get_sector_valuation",
                        lambda date=None: (_ for _ in ()).throw(Exception("down")))
    events = _post(client, "哪些指数低估了？")
    assert mocks["ctx"]["valuation_intent"] is True
    assert mocks["ctx"]["index_valuation"] == []
    assert "不得下低估/高估结论" in mocks["prompt"]
    assert any(e["event"] == "done" for e in events)  # 降级不断流


def test_product_subtask_only_allowlisted_codes(client, mocks):
    _post(client, "哪些板块低估？买哪只银行ETF？")
    emap = mocks["ctx"]["etf_map"]
    assert emap, "product 信号应产出映射"
    assert {"sector_or_index": "银行", "symbol": "512800",
            "name": "银行ETF"} in [
        {"sector_or_index": m["sector_or_index"], "symbol": m["symbol"],
         "name": m["name"]} for m in emap]
    assert "512800" in mocks["prompt"]
    assert "159766" not in mocks["prompt"]  # 旅游ETF 不许出现


def test_prompt_unit_table_and_empty_guard():
    ctx = {"market_regime": "range_bound", "market_sentiment": {},
           "market_data": [], "news": [], "sector_momentum": {},
           "fund_flow": {}, "portfolio": [], "valuation_intent": True,
           "index_valuation": [{"symbol": "000300", "name": "沪深300",
                                "pe_1": 14.6, "pe_2": None, "div_1": 2.63,
                                "pe_pct": 0.15, "verdict": "待验",
                                "as_of": "2026-09-16"}],
           "sector_valuation": [], "etf_map": []}
    out = _real_prompt("哪些低估？", ctx)
    assert "| 沪深300 | 14.60" in out
    assert "2026-09-16" in out
    out2 = _real_prompt("哪些低估？", {**ctx, "index_valuation": []})
    assert "不得下低估/高估结论" in out2
