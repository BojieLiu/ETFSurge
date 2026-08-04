"""
O5 (docs/round7-rediagnosis.md §7 P16): news-impact 智能分析正文兜底。

P16 根因: 数据源冷却/快讯类头条 content 为空时，prompt 里「新闻内容：」段为空
→ LLM 收到空正文 → 返回 summary="新闻内容为空" 的空洞结论（专业投资者认定
资讯智能分析不可用）。

修复: _news_body_text 三级兜底——content → summary → title（快讯），
空时显式标注「（无正文，仅标题）」，杜绝空正文段进入 prompt。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.analysis import llm as llmmod
from app.analysis.llm import _news_body_text


class TestNewsBodyText:
    def test_content_preferred(self):
        assert _news_body_text({"title": "T", "content": "C", "summary": "S"}) == "C"

    def test_summary_fallback(self):
        assert _news_body_text({"title": "T", "content": "", "summary": "S"}) == "S"
        assert _news_body_text({"title": "T", "summary": "S"}) == "S"

    def test_title_fallback(self):
        """content/summary 均空 → title 兜底（快讯类标题即正文）。"""
        body = _news_body_text({"title": "央行降准0.5个百分点", "content": ""})
        assert "央行降准0.5个百分点" in body

    def test_empty_returns_empty(self):
        assert _news_body_text({}) == ""


@pytest.mark.asyncio
async def test_analyze_news_impact_with_empty_content(monkeypatch):
    """content 空时 prompt 仍含正文（title 兜底），LLM 不收到空正文。"""
    captured = {}

    async def fake_run_json(prompt):
        captured["prompt"] = prompt
        return {"impact_scope": "A股", "affected_holdings": [], "summary": "ok"}

    mock_agent = MagicMock()
    mock_agent.run_json = AsyncMock(side_effect=fake_run_json)
    monkeypatch.setattr("app.analysis.llm.get_agent", lambda name: mock_agent)

    await llmmod.analyze_news_impact(
        {"title": "美联储宣布加息25个基点", "content": ""},
        [],
    )
    prompt = captured["prompt"]
    assert "美联储宣布加息25个基点" in prompt, "prompt 应含 title 兜底正文"
    assert "新闻内容：\n\n" not in prompt, "空正文段不应出现"
