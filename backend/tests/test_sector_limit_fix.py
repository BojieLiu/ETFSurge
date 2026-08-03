"""R6-F3 (round6 §十 R6-04): sector/concept 分析 limit 截断修复。

背景：sector_analysis_stream 用 get_sector_industry/concept(200) 截断——当日
跌幅大的板块（如半导体 BK1036）排名 >200 → 404「板块映射失败」。
修复：limit 200 → 500（与 /market/sectors 端点对齐），按名称二次查找覆盖。
"""
import json

import pytest


def _make_sectors(n: int, target_pos: int, target_code: str, target_name: str) -> list[dict]:
    """构造 n 条行业数据，把目标板块放在 target_pos 位（0-based）。"""
    rows = []
    for i in range(n):
        if i == target_pos:
            rows.append({"sector_code": target_code, "sector_name": target_name,
                         "price": 1000.0, "change_pct": -5.0, "amount": 1e9})
        else:
            rows.append({"sector_code": f"BK{i:04d}", "sector_name": f"板块{i}",
                         "price": 100.0, "change_pct": 0.0, "amount": 1e8})
    return rows


async def _collect_sse(response):
    """迭代 StreamingResponse 收集完整 SSE 文本。"""
    body = ""
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="replace")
    return body


@pytest.mark.asyncio
async def test_sector_analysis_semiconductor_beyond_200(monkeypatch):
    """半导体（BK1036）排名 250（>200 截断位）时仍能命中——limit 提至 500。"""
    from app.routers import analysis as an
    from app.services import market_data_hub as mdh

    sectors = _make_sectors(500, 250, "BK1036", "半导体")

    async def fake_concept(limit):
        return [{"sector_code": "BK1001", "sector_name": "概念", "price": 10.0,
                 "change_pct": 0.0, "amount": 1e8}] * 500

    monkeypatch.setattr(mdh.market_data_hub, "get_sector_industry", lambda limit: sectors[:limit])
    # get_sector_concept 在 hub 上是同步函数（analysis.py 用 asyncio.to_thread 调用）
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_concept",
                        lambda limit: [{"sector_code": "BK1001", "sector_name": "概念",
                                        "price": 10.0, "change_pct": 0.0, "amount": 1e8}] * 500)
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_stocks",
                        lambda code: [{"symbol": "688001", "name": "中芯国际"}])
    monkeypatch.setattr(mdh.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(mdh.market_data_hub, "get_news_macro", lambda: [])

    def _fake_stream(prompt):
        async def gen():
            yield {"event": "token", "data": {"token": "半导体"}}
            yield {"event": "done", "data": {"full_text": "半导体板块分析报告（mock）"}}
        return gen()

    # mock LLM agent：直接产出含板块名的报告（get_agent 返回实例）
    fake_agent = type("FakeAgent", (), {"run_stream": lambda self, prompt: _fake_stream(prompt)})
    monkeypatch.setattr(an, "get_agent", lambda name: fake_agent())

    from fastapi import HTTPException
    req = an.SectorAnalysisRequest(
        sector_code="BK1036", sector_type="industry", sector_name="半导体", market="A",
    )
    response = await an.sector_analysis_stream(req)
    text = await _collect_sse(response)
    # 不应出现 404「板块映射失败」；应产出 done 事件（成功路径）
    assert "板块映射失败" not in text
    assert "event: done" in text
    assert "\\u534a\\u5bfc" in text  # "半导体" 的 json 转义形式


@pytest.mark.asyncio
async def test_sector_analysis_still_404_for_unknown(monkeypatch):
    """真实不存在的板块代码仍应 404（回归防护）。"""
    from app.routers import analysis as an
    from app.services import market_data_hub as mdh

    sectors = _make_sectors(500, 0, "BK1036", "半导体")
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_industry", lambda limit: sectors[:limit])
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_concept", lambda limit: [])
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_stocks", lambda code: [])
    monkeypatch.setattr(mdh.market_data_hub, "get_news_headlines", lambda: [])

    from fastapi import HTTPException
    req = an.SectorAnalysisRequest(
        sector_code="BK9999", sector_type="industry", sector_name="不存在的板块", market="A",
    )
    with pytest.raises(HTTPException) as exc_info:
        await an.sector_analysis_stream(req)
    assert exc_info.value.status_code == 404
