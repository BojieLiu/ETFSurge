# -*- coding: utf-8 -*-
"""F2-3 / F2-6(步骤A) / F2-7(步骤F): 热点板块/板块热度/热门个股字段归一化 + cls 代码归一化。

对应方案 §9.8 专项 TDD 计划（后端 5 用例）。
"""
import asyncio

import pytest

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _fake_hot_plate_row():
    return {
        "secu_name": "AI智能体",
        "up_reason": "大模型催化",
        "plate_stock_up_num": 6,
        "stock_list": '[{"secu_code": "688825", "secu_name": "海光信息"}]',
    }


# ── 1. GET /market/sectors/heat 路由（F2-3，§9.8.4 用例1） ─────────────
def test_sectors_heat_route(monkeypatch):
    """GET /market/sectors/heat?limit=20 → 200，items 含 name/heat_index/rank_change。"""
    from app.services import market_data_hub as hub_mod

    fake = [{
        "plate_code": "cls82558", "rank": 1, "cur_heat": 13501.4,
        "rank_change": 5, "is_new": 0, "plate_name": "AI智能体",
    }]
    monkeypatch.setattr(hub_mod.market_data_hub, "get_sector_heat", lambda limit=None, market="A": fake)
    resp = client.get("/api/v1/market/sectors/heat?limit=20")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["name"] == "AI智能体"
    assert items[0]["heat_index"] == 13501.4
    assert items[0]["rank_change"] == 5
    assert resp.json()["total"] == 1


# ── 2. hot_plates 字段归一化（F2-6 步骤A，§9.8.4 用例2） ────────────────
def test_hot_plates_normalized(monkeypatch):
    """原始字段 secu_name/up_reason/stock_list → name/reason/lead_stocks 数组。"""
    from app.services import market_data_hub as hub_mod

    monkeypatch.setattr(hub_mod.sector_fetcher, "fetch_hot_plates", lambda limit=None: [_fake_hot_plate_row()])
    out = hub_mod.market_data_hub.get_hot_plates(15)
    assert out and out[0]["name"] == "AI智能体"
    assert out[0]["reason"] == "大模型催化"
    assert out[0]["stock_count"] == 6
    lead = out[0]["lead_stocks"]
    assert isinstance(lead, list) and lead[0]["secu_name"] == "海光信息"
    assert "stock_list" not in out[0]


# ── 3. stock_list 非法字符串安全解析（§9.8.4 用例3） ─────────────────────
def test_stock_list_parse_safe(monkeypatch):
    """stock_list 为非法字符串 → lead_stocks=[] 不抛错。"""
    from app.services import market_data_hub as hub_mod

    bad = dict(_fake_hot_plate_row())
    bad["stock_list"] = "not-a-list{{{"
    monkeypatch.setattr(hub_mod.sector_fetcher, "fetch_hot_plates", lambda limit=None: [bad])
    out = hub_mod.market_data_hub.get_hot_plates(15)
    assert out and out[0]["lead_stocks"] == []


# ── 4. 热门个股 concept_tags 解析（F2-6 步骤A，§9.8.4 用例4） ────────────
def test_stock_hot_rank_concept_tags(monkeypatch):
    """enrich 后含 concept_tags 数组（tag 字符串安全解析）。"""
    from app.services import market_data_hub as hub_mod

    raw = [
        {"code": "688825", "name": "海光信息", "change_pct": 5.2,
         "tag": '["半导体", "国产替代", "AI芯片"]'},
        {"code": "002415", "name": "海康威视", "change_pct": -1.1,
         "tag": "bad-tag{{{"},
    ]
    monkeypatch.setattr(hub_mod.sector_fetcher, "fetch_stock_hot_rank", lambda limit=50: raw)
    import app.fetchers.china_market as cm
    monkeypatch.setattr(cm, "fetch_a_stock_batch", lambda codes: [])
    monkeypatch.setattr(hub_mod.sector_fetcher, "get_stock_industry_map", lambda codes: {})
    out = hub_mod.market_data_hub.get_stock_hot_rank(50)
    assert out[0]["concept_tags"] == ["半导体", "国产替代", "AI芯片"]
    assert out[1]["concept_tags"] == []
    # 非法 tag 不抛错且原行保留
    assert out[1]["symbol"] == "002415"


# ── 5. cls 前缀代码归一化（F2-7 步骤F，§9.8.4 用例5） ─────────────────────
def test_normalize_sector_code_matches_bk():
    """cls 前缀代码归一化：名称优先，数字段精确匹配 BK。"""
    from app.routers.analysis import _normalize_sector_code

    industry = [
        {"sector_code": "BK0447", "sector_name": "半导体"},
        {"sector_code": "BK8255", "sector_name": "AI智能体"},
    ]
    # 名称优先：显式名称直接命中
    assert _normalize_sector_code("cls82558", industry, [], name="半导体") == "BK0447"
    # 数字段精确匹配 BK 代码
    assert _normalize_sector_code("cls8255", industry, []) == "BK8255"
    # 已是 BK 代码原样返回
    assert _normalize_sector_code("BK0447", industry, []) == "BK0447"
    # 归一化失败保持原值
    assert _normalize_sector_code("cls99999", industry, []) == "cls99999"


def test_sector_analysis_cls_entry(monkeypatch):
    """入口带 cls 代码 → 归一化后查询成功（mock agent SSE）。"""
    import json

    from app.routers import analysis as analysis_mod

    def fake_get_sector_industry(limit=200):
        return [{"sector_code": "BK8255", "sector_name": "AI智能体"}]

    def fake_get_sector_stocks(code):
        return [{"code": "688825", "name": "海光信息"}]

    def fake_get_sector_concept(limit=200):
        return []

    def fake_agent_run_stream(prompt):
        async def gen():
            yield {"event": "token", "data": {"token": "ok"}}
            yield {"event": "done", "data": {"full_text": "分析完成", "usage": {}}}
        return gen()

    class _FakeAgent:
        def run_stream(self, prompt):
            return fake_agent_run_stream(prompt)

    class _FakeAgentReg:
        def get_agent(self, name):
            return _FakeAgent()

    monkeypatch.setattr(analysis_mod.market_data_hub, "get_sector_industry", fake_get_sector_industry)
    monkeypatch.setattr(analysis_mod.market_data_hub, "get_sector_concept", fake_get_sector_concept)
    monkeypatch.setattr(analysis_mod.market_data_hub, "get_sector_stocks", fake_get_sector_stocks)
    monkeypatch.setattr(analysis_mod, "get_agent", _FakeAgentReg().get_agent)

    resp = client.post("/api/v1/analysis/sector-analysis/stream", json={
        "sector_code": "cls82558", "sector_name": "AI智能体", "sector_type": "industry", "market": "A",
    })
    assert resp.status_code == 200
    assert "event: done" in resp.text
    assert "\\u5206\\u6790\\u5b8c\\u6210" in resp.text
