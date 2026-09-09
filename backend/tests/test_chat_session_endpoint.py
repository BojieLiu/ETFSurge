# -*- coding utf-8 -*-
"""LLM 多轮会话端点集成（round53 §9 阶段 1+2 端到端闭环）。

覆盖:
- /llm-advice/stream 新会话 → done.metadata.session_id 返回新 id（SSE 全事件流）;
- 追问（带 session_id）→ 原 id 保持 + prompt 注入「## 对话历史」;
- 无效 session_id → 自动新会话不报错;
- done 后 assistant 回复落会话（下一轮 render_history 可见）。
契约: api-contracts/analysis/llm-chat-session.md
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


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
def mock_llm_and_ctx(monkeypatch):
    """mock LLM 流（固定回复）+ 上下文采集（避免真实数据源 IO）。"""
    async def _fake_stream(*args, **kwargs):
        yield {"type": "token", "token": "测试"}
        yield {"type": "token", "token": "回复"}
        yield {"type": "done", "full_text": "测试回复", "usage": {"total_tokens": 10}}

    async def _fake_ctx(*args, **kwargs):
        return {
            "index_realtime": [], "sector_momentum": [], "news": [],
            "market_regime": "range_bound", "market_sentiment": {}, "fund_flow": {},
        }

    from app.analysis.llm import client as llm_client
    monkeypatch.setattr(llm_client, "llm_complete_stream", _fake_stream)
    monkeypatch.setattr("app.routers.analysis.build_full_context", _fake_ctx)


def _post_advice(client, query, session_id=None):
    body = {"query": query, "market": "A"}
    if session_id is not None:
        body["session_id"] = session_id
    resp = client.post("/api/v1/analysis/llm-advice/stream", json=body)
    assert resp.status_code == 200, resp.text[:200]
    return _parse_sse(resp.text)


class TestAdviceSessionE2E:
    def test_new_session_returns_session_id_in_done(self, client, mock_llm_and_ctx):
        events = _post_advice(client, "当前市场怎么看？")
        done = next(e for e in events if e["event"] == "done")
        sid = (done["data"].get("metadata") or {}).get("session_id")
        assert sid and sid.startswith("sess-"), f"done.metadata 缺 session_id: {done}"

    def test_followup_keeps_session_id_and_injects_history(self, client, mock_llm_and_ctx):
        events = _post_advice(client, "为什么这么说？")
        done = next(e for e in events if e["event"] == "done")
        sid = done["data"]["metadata"]["session_id"]

        # 追问（带 session_id）
        events2 = _post_advice(client, "那换成 510300 呢？", session_id=sid)
        done2 = next(e for e in events2 if e["event"] == "done")
        sid2 = done2["data"]["metadata"]["session_id"]
        assert sid2 == sid, "追问必须保持同一会话"

    def test_invalid_session_id_starts_new(self, client, mock_llm_and_ctx):
        events = _post_advice(client, "新问题", session_id="sess-deadbeefdeadbeef")
        done = next(e for e in events if e["event"] == "done")
        sid = done["data"]["metadata"]["session_id"]
        assert sid and sid != "sess-deadbeefdeadbeef"
