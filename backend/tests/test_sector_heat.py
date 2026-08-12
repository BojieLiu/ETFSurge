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


def test_sectors_heat_change_pct_backfilled_by_em(monkeypatch):
    """O19 补充：东财板块涨跌幅按名称回填 change_pct；未命中保持 0 兜底。"""
    from app.services import market_data_hub as hub_mod
    import app.fetchers.sector_fetcher as sector_fetcher

    fake = [
        {"plate_code": "cls1", "rank": 1, "cur_heat": 100, "rank_change": 0,
         "is_new": 0, "plate_name": "AI智能体"},
        {"plate_code": "cls2", "rank": 2, "cur_heat": 90, "rank_change": -1,
         "is_new": 0, "plate_name": "CRO/CMO"},
        {"plate_code": "cls3", "rank": 3, "cur_heat": 80, "rank_change": 0,
         "is_new": 0, "plate_name": "无东财数据板块"},
    ]
    monkeypatch.setattr(hub_mod.market_data_hub, "get_sector_heat", lambda limit=None, market="A": fake)
    monkeypatch.setattr(sector_fetcher, "fetch_em_sector_changes", lambda: {"AI智能体": 3.25, "CRO": 2.5})
    resp = client.get("/api/v1/market/sectors/heat?limit=20")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["change_pct"] == 3.25, "东财精确命中应回填真实涨跌幅"
    assert items[1]["change_pct"] == 2.5, "「/」分割首段（CRO/CMO → CRO）应回填"
    # round19 P4-③: 未命中兜底从 0 改 None（涨跌幅未知不冒充 0%）
    assert items[2]["change_pct"] is None, "未命中板块保持 null 兜底（不冒充 0%）"


def test_match_em_change_three_levels():
    """_match_em_change 三级匹配：精确 / 包含 / 斜杠首段。"""
    from app.routers.market import _match_em_change

    em = {"印制电路板": 8.31, "CRO": 2.5, "AI智能体": 3.25, "创新药": -1.2}
    assert _match_em_change("AI智能体", em) == 3.25          # 精确
    assert _match_em_change("CRO/CMO", em) == 2.5            # 斜杠首段
    assert _match_em_change("PCB", {"印制电路板": 8.31}) is None  # 无别名映射不误配
    assert _match_em_change("不存在板块", em) is None         # 未命中
    assert _match_em_change("", em) is None                  # 空名


# ── P0-17 (round16 3.19): EM 源切换 + 非零率监控 + lead_stocks 透传 ──
def test_sectors_heat_em_source_nonzero_ratio(monkeypatch):
    """P0-17①/③: A股热度走东财行业 spot——自带真实涨跌幅，非零率 ≥50%；
    全 0（源失败/回退链断裂）时 degraded=True（负向：全 0 不报 degraded → FAIL）。"""
    from app.services import market_data_hub as hub_mod

    fake = [
        {"plate_code": "BK1", "rank": i + 1, "cur_heat": 100 - i, "rank_change": 0,
         "is_new": 0, "plate_name": f"板块{i}", "change_pct": chg,
         "lead_stocks": [{"symbol": "600000", "name": "领涨股", "change_pct": 2.0}] if chg else []}
        for i, chg in enumerate([3.2, -1.5, 2.1, 0.8, -0.4, 1.1, 2.2, -0.9, 0.5, 1.8,
                                 0.6, -0.3, 1.2, 0.9, 0.4, -0.2, 0.7, 0.3, 0.1, 0.2])
    ]
    monkeypatch.setattr(hub_mod.market_data_hub, "get_sector_heat", lambda limit=None, market="A": fake)
    resp = client.get("/api/v1/market/sectors/heat?limit=20")
    assert resp.status_code == 200
    body = resp.json()
    nonzero = sum(1 for it in body["items"] if it.get("change_pct"))
    assert nonzero >= 10, f"非零率应 ≥50%（20 条至少 10 条非零），实际 {nonzero}"
    assert body.get("degraded") is False
    # P0-18: lead_stocks 透传
    assert body["items"][0]["lead_stocks"][0]["symbol"] == "600000"


def test_sectors_heat_degraded_flag_when_all_zero(monkeypatch):
    """P0-17③: 全部涨跌幅 0（回退链断裂）→ degraded=True + 告警。"""
    from app.services import market_data_hub as hub_mod

    fake = [
        {"plate_code": f"BK{i}", "rank": i + 1, "cur_heat": 50, "rank_change": 0,
         "is_new": 0, "plate_name": f"板块{i}", "change_pct": 0, "lead_stocks": []}
        for i in range(20)
    ]
    monkeypatch.setattr(hub_mod.market_data_hub, "get_sector_heat", lambda limit=None, market="A": fake)
    resp = client.get("/api/v1/market/sectors/heat?limit=20")
    assert resp.status_code == 200
    assert resp.json().get("degraded") is True, "全 0 时应显式标记 degraded 而非静默"


def test_get_sector_heat_em_first_then_cls_fallback(monkeypatch):
    """P0-17①: hub.get_sector_heat A 股优先 EM 源；EM 空 → 回退财联社。"""
    import app.fetchers.sector_fetcher as sector_fetcher
    from app.services.market_data_hub import MarketDataHub

    hub = MarketDataHub()
    hub._test_mode = True
    em_rows = [{"rank": 1, "name": "半导体", "heat_index": 100, "rank_change": 0,
                "is_new": 0, "plate_code": "BK0447", "change_pct": 2.3,
                "lead_stocks": [{"symbol": "688825", "name": "海光信息", "change_pct": 5.1}]}]
    cls_rows = [{"rank": 1, "cur_heat": 90, "plate_name": "财联社板块"}]

    monkeypatch.setattr(sector_fetcher, "fetch_sector_heat_em", lambda limit=20: em_rows)
    monkeypatch.setattr(sector_fetcher, "fetch_sector_heat", lambda limit=20: cls_rows)
    out = hub.get_sector_heat(20)
    assert out == em_rows, "EM 源有数据时应优先返回（非财联社）"
    assert out[0]["lead_stocks"], "EM 条目应带 lead_stocks（P0-18 依赖）"

    # EM 空 → 回退财联社
    monkeypatch.setattr(sector_fetcher, "fetch_sector_heat_em", lambda limit=20: [])
    out2 = hub.get_sector_heat(20)
    assert out2 == cls_rows, "EM 空时应回退财联社热度"


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
