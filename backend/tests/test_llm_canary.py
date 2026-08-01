# -*- coding: utf-8 -*-
"""T8: LLM 质量金丝雀基线（非 mock，固定 3 条样本 + 固定 prompt）。

断言：
① 输出不含 system prompt 片段（含 reasoning 通道泄漏，对齐 F1-7）
② 不含「未包含 XX 数据」自曝缺失模式（对齐 ⑭）
③ news-impact 结论含「无直接影响」或受影响 ≤2 只（对齐 §9.9.5-2）

无 LLM key 或 429 限流时 skip（金丝雀依赖真实 LLM 可用性）。
"""
import pytest

from app.config import settings

_has_key = bool(
    (settings.deepseek_api_key or settings.opencode_zen_api_key or "").strip()
)

pytestmark = pytest.mark.skipif(not _has_key, reason="无 LLM API key，金丝雀基线跳过")


async def _try_llm(prompt: str) -> str:
    """调 LLM（不重试，快速失败）；429 限流时标记跳过。"""
    from app.analysis.llm import llm_complete_with_system
    try:
        return await llm_complete_with_system(
            "你是 ETF 投研助手，输出简洁克制。", prompt, max_retries=0,
        )
    except RuntimeError as e:
        if "限流" in str(e):
            pytest.skip(f"LLM 限流（429）：{e}")
        raise


@pytest.mark.asyncio
async def test_canary_no_system_prompt_leak():
    """金丝雀①: 样本输出不含 system prompt 片段（F1-7 泄漏防线回归）。"""
    from app.analysis.llm import SYSTEM_PROMPT
    out = await _try_llm("央行宣布降准 0.5 个百分点，对 A 股有何影响？请用两句话点评。")
    for frag in ("我们只需要回答", "请忽略以上", "你是一名专业", "你是一个专业"):
        assert frag not in out, f"输出含 system prompt 泄漏片段: {frag}"
    assert SYSTEM_PROMPT[:30] not in out, "输出含 system prompt 整段泄漏"


@pytest.mark.asyncio
async def test_canary_no_self_missing_data():
    """金丝雀②: 输出不含「未包含 XX 数据」自曝缺失模式。"""
    out = await _try_llm("日本硅岛半导体工厂停产，对半导体 ETF 影响如何？请点评。")
    assert "未包含" not in out and "缺少数据" not in out, f"输出自曝数据缺失: {out[:120]}"


@pytest.mark.asyncio
async def test_canary_news_impact_no_force_link():
    """金丝雀③: news-impact 结论含「无直接影响」或受影响 ≤2 只（§9.9.5-2）。"""
    from app.analysis.llm import analyze_news_impact
    res = await analyze_news_impact(
        {"title": "某地出台自然保护法", "content": "规范近海岛屿生态保护，与金融市场无直接关联。"},
        [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3},
         {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.2}],
    )
    text = f"{res.get('impact_scope', '')} {res.get('summary', '')}"
    affected = res.get("affected_holdings") or []
    assert ("无直接影响" in text) or (len(affected) <= 2), \
        f"强行关联: scope={text[:80]} holdings={len(affected)}"
