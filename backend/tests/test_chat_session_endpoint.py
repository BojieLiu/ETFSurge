# -*- coding utf-8 -*-
"""LLM 多轮会话端点集成（round53 §9 阶段 1+2 端到端闭环）。

覆盖:
- /llm-advice/stream 新会话 → done.metadata.session_id 返回新 id（SSE 全事件流）;
- 追问（带 session_id）→ 原 id 保持 + prompt 注入「## 对话历史」;
- 无效 session_id → 自动新会话不报错;
- done 后 assistant 回复落会话（下一轮 render_history 可见）。
- valuation 意图端到端（mock LLM/上下文/估值源，无网络，并入自
  test_advice_valuation_e2e.py，F1 baseline 归位）。
契约: api-contracts/analysis/llm-chat-session.md
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.analysis.llm import _build_advice_stream_prompt as _real_prompt


# ⚠️ round58 (F1 归位): **不进入 lifespan**。
# 本文件的 8 个用例只需要路由 + SSE 装配（LLM/上下文均已 mock），不需要启动预热与
# 后台循环。而 `with TestClient(app)` 每次都会跑一遍 app lifespan：
#   ① 9 次函数级 fixture → 残留后台任务把共享 `run_in_thread(executor="long")`
#      线程池占满 → 同进程后续 mock 取数用例（test_fundamental_fetcher::
#      TestFetchFundScale）8s 超时被吞成 None，产生**跨文件假失败**；
#   ② 长驻 app 的后台循环会写运行时配置 → 污染后续读 provider 列表的用例
#      （test_llm_provider_failover 期望 deepseek，本机 fallback 实为
#      jev-1.13-free，见 docs/known-env-issues）。
# 不进 lifespan 后：无预热开销、无后台任务、无跨文件外溢（实测 177s→秒级）。
@pytest.fixture(scope="module")
def client():
    from app.main import app
    # 不用 `with`：避免 lifespan。显式 close 释放连接池即可。
    c = TestClient(app)
    yield c
    c.close()


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

    monkeypatch.setattr("app.analysis.runtime.llm_complete_stream",
                        _fake_stream)
    # round60: patch 目标必须是 app.services.llm_context，不是 app.routers.analysis。
    # analysis.py 在模块级 (:23) 和 llm_advice_stream 内部 (:599) 各 import 了一次
    # build_full_context——函数内的 import 在调用时从 app.services.llm_context 取属性，
    # **遮蔽**模块级名字，所以 patch router 模块属性对 advice 路径完全无效。
    # 实测后果：该路径一直在跑真实数据采集（akshare/东财等），这几个用例因此要
    # 30-120s、依赖网络、且行情源抖动时会假红。修后同一文件 13 passed in 18.9s。
    monkeypatch.setattr("app.services.llm_context.build_full_context", _fake_ctx)


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


# ── L1 v2 P1-4: valuation 意图端到端（并入自 test_advice_valuation_e2e.py）──
# 契约: api-contracts/analysis/advice-valuation.md §6、§8。
# - valuation 问 → prompt 含估值表 + SSE 含 fetching_valuation phase。
# - 非 valuation 问 → 不触估值源（hub mock 若被调直接抛错）。
# - 估值源异常 → 降级：prompt 含"不得下低估/高估结论"。
# - ETF 映射只出白名单码（product 子任务）。


@pytest.fixture
def valuation_mocks(monkeypatch):
    """mock LLM 流 + 上下文 + 估值源；记录喂给 prompt 的 ctx 与文本。"""
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
    # round60: patch 目标必须是 app.services.llm_context，不是 app.routers.analysis。
    # analysis.py 在模块级 (:23) 和 llm_advice_stream 内部 (:599) 各 import 了一次
    # build_full_context——函数内的 import 在调用时从 app.services.llm_context 取属性，
    # **遮蔽**模块级名字，所以 patch router 模块属性对 advice 路径完全无效。
    # 实测后果：该路径一直在跑真实数据采集（akshare/东财等），这几个用例因此要
    # 30-120s、依赖网络、且行情源抖动时会假红。修后同一文件 13 passed in 18.9s。
    monkeypatch.setattr("app.services.llm_context.build_full_context", _fake_ctx)
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


def test_valuation_query_injects_table_and_phase(client, valuation_mocks):
    events = _post_advice(client, "现在有哪些板块低估了？")
    assert valuation_mocks["ctx"]["valuation_intent"] is True
    assert len(valuation_mocks["ctx"]["index_valuation"]) == 5  # 5 个宽基
    assert valuation_mocks["ctx"]["index_valuation"][0]["symbol"] == "000300"
    assert "估值快照" in valuation_mocks["prompt"]
    assert "14.60" in valuation_mocks["prompt"]
    assert "待验" in valuation_mocks["prompt"]  # v1 无 ROE 不下结论
    phases = [e["data"].get("phase") for e in events
              if e["event"] == "progress"]
    assert "fetching_valuation" in phases


def test_non_valuation_query_skips_source(client, valuation_mocks, monkeypatch):
    from app.services.market_data_hub import market_data_hub as hub

    def _boom(*a, **k):
        raise AssertionError("非 valuation 意图不得触估值源")

    monkeypatch.setattr(hub, "get_index_valuation", _boom)
    monkeypatch.setattr(hub, "get_sector_valuation", _boom)
    _post_advice(client, "当前市场风格是成长还是价值？")
    assert valuation_mocks["ctx"]["valuation_intent"] is False
    assert valuation_mocks["ctx"]["index_valuation"] == []
    assert "估值快照" not in valuation_mocks["prompt"]


def test_valuation_source_failure_degrades(client, valuation_mocks, monkeypatch):
    from app.services.market_data_hub import market_data_hub as hub
    monkeypatch.setattr(hub, "get_index_valuation",
                        lambda sym: (_ for _ in ()).throw(Exception("down")))
    monkeypatch.setattr(hub, "get_sector_valuation",
                        lambda date=None: (_ for _ in ()).throw(Exception("down")))
    events = _post_advice(client, "哪些指数低估了？")
    assert valuation_mocks["ctx"]["valuation_intent"] is True
    assert valuation_mocks["ctx"]["index_valuation"] == []
    assert "不得下低估/高估结论" in valuation_mocks["prompt"]
    assert any(e["event"] == "done" for e in events)  # 降级不断流


def test_product_subtask_only_allowlisted_codes(client, valuation_mocks):
    _post_advice(client, "哪些板块低估？买哪只银行ETF？")
    emap = valuation_mocks["ctx"]["etf_map"]
    assert emap, "product 信号应产出映射"
    assert {"sector_or_index": "银行", "symbol": "512800",
            "name": "银行ETF"} in [
        {"sector_or_index": m["sector_or_index"], "symbol": m["symbol"],
         "name": m["name"]} for m in emap]
    assert "512800" in valuation_mocks["prompt"]
    assert "159766" not in valuation_mocks["prompt"]  # 旅游ETF 不许出现


# ── round60 D5: product_intent 标志位的接线 ──────────────────────────────
# L2 gold set (tests/test_advice_goldset_l2.py) 断言的是 prompt 组装层，那里的
# ctx 是内联的——它证明不了 router 真的把这个 flag 传下去了。以下三条补上这一段：
# 分类 → 标志位 → 守卫文案，全链路走真实端点。

def test_product_query_sets_product_intent_flag(client, valuation_mocks):
    """问一个映射表覆盖不到的品类 —— 这才是禁码守卫真正会触发的线上路径。

    注意别用「买哪只银行ETF」：银行是 SECTOR_ETF_MAP 的键，映射表非空，守卫
    按设计不出现（那是 L2-04 锁的另一条路径）。守卫只在**无表可查**时兜底。
    """
    _post_advice(client, "ETF推荐")
    ctx = valuation_mocks["ctx"]
    assert ctx["product_intent"] is True
    assert ctx["etf_map"] == [], "该问句不含任何映射表键，应为空"
    # D5 的核心：product 意图 + 空映射表 → 禁编造守卫必须出现
    assert "无 ETF 映射表" in valuation_mocks["prompt"]


def test_composite_query_sets_product_intent_flag(client, valuation_mocks):
    """复合问句里主意图是 valuation，product 仍是子任务。

    守卫与映射表用**同一个判据**（"product" in intents）。若标志位改成
    primary == "product"，这条问句会拿到 ETF 映射表却拿不到禁码守卫——
    两个标志对同一件事给出相反答案。
    """
    _post_advice(client, "哪些板块低估？买哪只银行ETF？")
    ctx = valuation_mocks["ctx"]
    assert ctx["valuation_intent"] is True      # primary = valuation
    assert ctx["product_intent"] is True        # 子任务仍然成立
    assert ctx["etf_map"], "product 子任务应产出映射"


def test_non_product_query_clears_product_intent_flag(client, valuation_mocks):
    _post_advice(client, "当前市场风格是成长还是价值？")
    assert valuation_mocks["ctx"]["product_intent"] is False
    assert "无 ETF 映射表" not in valuation_mocks["prompt"]  # 防过度触发


# ── round60 S8: 商品槽接线 ───────────────────────────────────────────────
# L2 gold set 用内联 ctx，只能证明 prompt 会渲染商品段；证明不了采集侧
# include_commodities 开关真的打开了（那是 analysis.py 的事，不在 prompt 函数里）。
# 下面两条走真实端点：一条证明开关已开且数据到得了 prompt，一条锁住空列表时
# 整段省略。复用 valuation_mocks 的 ctx/prompt 记录器，只覆盖 build_full_context。

def _commodities_ctx(rows, sink=None):
    async def _ctx(*args, **kwargs):
        if sink is not None:
            sink["kwargs"] = dict(kwargs)
        return {"index_realtime": [], "sector_momentum": [], "news": [],
                "market_regime": "range_bound", "market_sentiment": {},
                "fund_flow": {}, "commodities": rows}
    return _ctx


def test_commodities_collect_flag_is_on(client, valuation_mocks, monkeypatch):
    """断言**采集开关本身**，而不是它的下游效果。

    这条是 mutation 补出来的：把 analysis.py 的 include_commodities 改回 False，
    原有 6 条测试**全部照绿**——因为每条测试都 mock 了 build_full_context，
    而 mock 无视 kwargs。商品槽只在这一个参数上死，且死得无声无息：
    功能消失、测试全绿。因此必须直接断言 router 传下去的参数。
    """
    sink = {}
    monkeypatch.setattr("app.services.llm_context.build_full_context",
                        _commodities_ctx([], sink))
    _post_advice(client, "黄金和原油现在配哪个")
    assert sink.get("kwargs"), "fake collector never saw the kwargs"
    assert sink["kwargs"].get("include_commodities") is True


def test_commodities_reach_the_prompt(client, valuation_mocks, monkeypatch):
    monkeypatch.setattr("app.services.llm_context.build_full_context", _commodities_ctx([
        {"name": "COMEX黄金", "price": 2380.5, "change_pct": 0.62},
        {"name": "NYMEX原油", "price": 71.34, "change_pct": -1.15},
    ]))
    _post_advice(client, "黄金和原油现在配哪个")
    assert "### 商品行情" in valuation_mocks["prompt"]
    assert "黄金" in valuation_mocks["prompt"]
    assert "原油" in valuation_mocks["prompt"]


def test_empty_commodities_omit_the_section(client, valuation_mocks, monkeypatch):
    monkeypatch.setattr("app.services.llm_context.build_full_context",
                        _commodities_ctx([]))
    _post_advice(client, "黄金和原油现在配哪个")
    # 盘后/非交易时段上游允许空列表：合法空窗，必须整段省略而非填兜底数字
    assert "### 商品行情" not in valuation_mocks["prompt"]


def test_valuation_prompt_unit_table_and_empty_guard():
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
