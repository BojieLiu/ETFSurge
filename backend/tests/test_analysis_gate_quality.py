# -*- coding: utf-8 -*-
"""F7 R21/R22 + F12 R41 验收测试。

R21: symbol_analysis_stream 数据全空时不调 LLM，返回 SSE error（DATA_UNAVAILABLE）。
R22: prompt 无顿号编号（symbol/板块 prompt 均用 1. 2. 3. 编号）。
R41: _normalize_sector_code 名称包含匹配 + except 不再吞 HTTPException(404)。
"""
import pytest
from starlette.exceptions import HTTPException

from app.routers import analysis as analysis_router


def test_normalize_sector_code_partial_name_match():
    """R41: 中文名部分匹配（"半导体"命中"半导体及元件"）。"""
    industry = [
        {"sector_code": "BK1036", "sector_name": "半导体及元件"},
        {"sector_code": "BK0475", "sector_name": "银行"},
    ]
    result = analysis_router._normalize_sector_code("cls82558", industry, [], name="半导体")
    assert result == "BK1036"


def test_normalize_sector_code_exact_match_wins():
    """R41: 精确匹配优先于包含匹配。"""
    industry = [
        {"sector_code": "BK1036", "sector_name": "半导体及元件"},
        {"sector_code": "BK1111", "sector_name": "半导体"},
    ]
    result = analysis_router._normalize_sector_code("cls82558", industry, [], name="半导体")
    assert result == "BK1111"


def test_normalize_sector_code_case_insensitive():
    """R41: 英文板块名大小写不敏感。"""
    concept = [{"sector_code": "BK0800", "sector_name": "AI算力"}]
    assert analysis_router._normalize_sector_code("BK0800", [], concept, name="ai算力") == "BK0800"


def test_normalize_sector_code_concept_name_in_combined_tables():
    """R5: 概念名（芯片）在行业表缺失、概念表存在——合并表必须命中（前端固定传 industry 的兜底）。"""
    industry = [
        {"sector_code": "BK1036", "sector_name": "半导体及元件"},
        {"sector_code": "BK0475", "sector_name": "银行"},
    ]
    concept = [
        {"sector_code": "BK1035", "sector_name": "芯片"},
        {"sector_code": "BK0800", "sector_name": "AI算力"},
    ]
    # 模拟调用处合并：industry + concept 一起传（_normalize_sector_code 内部已合并两表）
    result = analysis_router._normalize_sector_code("芯片", industry, concept, name="芯片")
    assert result == "BK1035", f"概念名应从合并表命中，实际 {result}"
    # 行业名不受影响
    assert analysis_router._normalize_sector_code("cls82558", industry, concept, name="半导体") == "BK1036"


async def test_symbol_analysis_data_unavailable_no_llm(monkeypatch):
    """R21: realtime/hist 全空 → 返回 SSE error，不调 LLM。"""
    from app.routers import analysis as ar

    async def _fake_realtime(*a, **k):
        return {}

    async def _fake_history(*a, **k):
        return []

    class _FakeReq:
        symbol = "510300"
        name = ""
        asset_type = "A"
        market = "A"
        question = ""

    called = {"llm": False}

    def _fake_agent(name):
        class _A:
            def run_stream(self, prompt):
                called["llm"] = True
                return iter([])
        return _A()

    # realtime 经 market_data_hub.get_asset_realtime；hist 经 get_history（模块级 import 修复后）
    monkeypatch.setattr(ar.market_data_hub, "get_asset_realtime", _fake_realtime)
    monkeypatch.setattr(ar, "get_history", _fake_history)
    monkeypatch.setattr(ar, "get_agent", _fake_agent)

    resp = await ar.symbol_analysis_stream(_FakeReq())
    body = "".join([chunk async for chunk in resp.body_iterator])
    assert "event: error" in body
    assert "DATA_UNAVAILABLE" in body
    assert called["llm"] is False, "R21: 数据全空不得调用 LLM"


def test_symbol_prompt_no_dunhao():
    """R22: symbol_analysis prompt 无顿号编号（1. 2. 3. 编号形式）。"""
    src = analysis_router.__dict__.get("symbol_analysis_stream")
    import inspect
    body = inspect.getsource(analysis_router.symbol_analysis_stream)
    assert "1. 基本面概览" in body
    assert "5. 操作建议" in body
    assert "请输出：基本面概览、技术面分析" not in body


def test_sector_prompt_no_dunhao():
    """R22: sector_analysis prompt 同样无顿号编号。"""
    import inspect
    body = inspect.getsource(analysis_router.sector_analysis_stream)
    assert "1. 板块概况" in body
    assert "6. 核心标的推荐" in body
    assert "请输出：板块概况、资金面" not in body


def test_sector_404_not_wrapped_as_502():
    """R41 延续: 板块 404 由 _sse_stream 统一转为 DATA_UNAVAILABLE error 事件（不包装成 502）。

    R49 重构后 sector_analysis_stream 不再直接抛 HTTPException（重 I/O 延后到
    流式消费），404 → SSE `event: error` 的转换落在 _sse_stream 内——守卫该转换：
    except HTTPException 分支必须产出 DATA_UNAVAILABLE（404）而非 STREAM_ERROR。
    """
    import inspect
    src = inspect.getsource(analysis_router._sse_stream)
    assert "except HTTPException" in src, "_sse_stream 应捕获预检 HTTPException"
    segment = src.split("except HTTPException")[1].split("except Exception")[0]
    assert "DATA_UNAVAILABLE" in segment, "404 应转 DATA_UNAVAILABLE，不得包装成 502/STREAM_ERROR"
