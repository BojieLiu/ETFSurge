from __future__ import annotations
"""
round35 §19.9 约束#4 / 验收#6: OpenRouter 中间层配额保护。

- 运行时标记：client failover 循环真实尝试 openrouter 候选时打标
  （TTL ≈ 目录刷新周期，Zen 恢复后自然过期）；
- 后台低价值调用跳过：``hub/_news.py enrich_news_summaries`` 在标记激活期间
  不发 LLM 调用、直接走规则摘要——防烧穿免费日额度挤占交互路径。

负向断言口径：旧实现（循环无打标 / enrich 无跳过接线）下本文件用例必红。
All external HTTP calls are mocked (httpx.AsyncClient) — 无真实网络。
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.analysis.llm.gates import (
    is_middle_layer_active,
    mark_middle_layer_active,
    reset_circuit,
)
from app.analysis.provider import ProviderConfig
from app.services.hub._news import NewsMixin


# ─── fixtures / helpers ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_gates():
    """隔离跨用例的全局门禁状态（含中间层标记）。"""
    reset_circuit()
    yield
    reset_circuit()


def _make_response(content: str, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}", request=MagicMock(), response=resp
        )
    return resp


def _patch_httpx(side_effects: list):
    patcher = patch("httpx.AsyncClient")
    mock_cls = patcher.start()
    inst = mock_cls.return_value.__aenter__.return_value
    inst.post = AsyncMock(side_effect=side_effects)
    return patcher


def _provider(pid: str, model: str) -> ProviderConfig:
    return ProviderConfig(
        id=pid, name=pid, api_url="https://example.invalid/chat",
        api_key="sk-test", model=model, timeout=5,
    )


def _news_item(nid: str) -> dict:
    return {
        "id": nid,
        "title": f"重要资讯{nid}",
        "content": f"{nid}的第一句内容。第二句不应出现在规则摘要。",
        "level": 4,
        "stars": 4,
        "ai_summary": None,
    }


class _FakeHub(NewsMixin):
    """最小 NewsMixin 宿主：只注入桶数据与新鲜时间戳（防懒刷新触发）。"""

    def __init__(self, buckets: dict):
        self._news_buckets = buckets
        self._news_cache_ts = time.time()


# ─── A. client 循环打标：openrouter 被尝试 → 标记激活 ───────────────


class TestMiddleLayerMarking:
    async def test_openrouter_attempt_marks_active(self):
        """负向断言核心：zen 失败 → openrouter 被真实尝试 → is_middle_layer_active() 必须为 True。

        旧实现（循环无打标）下此断言必红。
        """
        from app.analysis.llm import client as llm_client

        providers = [
            _provider("opencode_zen", "zen-free"),
            _provider("openrouter", "or-free"),
        ]
        err = httpx.HTTPStatusError(
            "HTTP 500", request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        ok = _make_response("ok")
        p1 = patch.object(llm_client, "get_configured_providers",
                          return_value=providers)
        p2 = patch.object(llm_client, "has_any_api_key", return_value=True)
        p3 = _patch_httpx([err, ok])
        p1.start()
        p2.start()
        try:
            result = await llm_client.llm_complete_with_system("sys", "prompt")
            assert result == "ok"
            assert is_middle_layer_active() is True, (
                "client 循环尝试 openrouter 候选后必须打标中间层激活"
            )
        finally:
            for p in (p1, p2, p3):
                p.stop()

    async def test_zen_only_success_leaves_flag_off(self):
        """纯 Zen 层成功（未触及中间层）→ 标记不得误激活。"""
        from app.analysis.llm import client as llm_client

        providers = [_provider("opencode_zen", "zen-free")]
        ok = _make_response("ok")
        p1 = patch.object(llm_client, "get_configured_providers",
                          return_value=providers)
        p2 = patch.object(llm_client, "has_any_api_key", return_value=True)
        p3 = _patch_httpx([ok])
        p1.start()
        p2.start()
        try:
            result = await llm_client.llm_complete_with_system("sys", "prompt")
            assert result == "ok"
            assert is_middle_layer_active() is False
        finally:
            for p in (p1, p2, p3):
                p.stop()

    async def test_deepseek_only_leaves_flag_off(self):
        """DeepSeek 兜底路径同样不激活中间层标记。"""
        from app.analysis.llm import client as llm_client

        providers = [_provider("deepseek", "deepseek-v4-flash")]
        ok = _make_response("ok")
        p1 = patch.object(llm_client, "get_configured_providers",
                          return_value=providers)
        p2 = patch.object(llm_client, "has_any_api_key", return_value=True)
        p3 = _patch_httpx([ok])
        p1.start()
        p2.start()
        try:
            await llm_client.llm_complete_with_system("sys", "prompt")
            assert is_middle_layer_active() is False
        finally:
            for p in (p1, p2, p3):
                p.stop()


# ─── B. 标记 TTL / 复位 ─────────────────────────────────────────────


class TestFlagTTLAndReset:
    def test_mark_default_activates(self):
        mark_middle_layer_active()
        assert is_middle_layer_active() is True

    def test_mark_zero_ttl_inactive(self):
        mark_middle_layer_active(ttl=0.0)
        assert is_middle_layer_active() is False

    def test_reset_circuit_clears_flag(self):
        mark_middle_layer_active()
        reset_circuit()
        assert is_middle_layer_active() is False


# ─── C. 后台调用跳过：enrich_news_summaries 配额保护 ────────────────


class TestEnrichQuotaProtection:
    async def test_enrich_skips_llm_when_middle_layer_active(self):
        """核心负向断言：标记激活期间 LLM 摘要调用次数必须为 0，直接走规则摘要。

        旧实现（无跳过接线）下 generate_news_summary 必被调用 → calls 非空且
        source=="llm"，两处断言皆红。
        """
        mark_middle_layer_active()
        hub = _FakeHub({"headlines": [_news_item("n1")], "macro": [], "global": []})
        calls: list[tuple] = []

        async def _sentinel(title, content):
            calls.append((title, content))
            return "LLM 生成的摘要"

        with patch("app.analysis.llm.generate_news_summary",
                   side_effect=_sentinel):
            enriched = await hub.enrich_news_summaries(cap=6)

        n = hub._news_buckets["headlines"][0]
        assert calls == [], "中间层激活期间后台摘要不得发起 LLM 调用"
        assert enriched == 1
        assert n["ai_summary"], "跳过 LLM 时必须以规则摘要兜底（ai_summary 非 null）"
        assert n["ai_summary_source"] == "rule"

    async def test_enrich_still_uses_llm_when_flag_off(self):
        """防过度阻断守卫：标记未激活时 LLM 路径行为不变（source=="llm"）。"""
        hub = _FakeHub({"headlines": [_news_item("n1")], "macro": [], "global": []})

        async def _fake_summary(title, content):
            return "LLM 生成的摘要"

        with patch("app.analysis.llm.generate_news_summary",
                   side_effect=_fake_summary):
            enriched = await hub.enrich_news_summaries(cap=6)

        n = hub._news_buckets["headlines"][0]
        assert enriched == 1
        assert n["ai_summary"] == "LLM 生成的摘要"
        assert n["ai_summary_source"] == "llm"

    async def test_enrich_multi_bucket_all_rule_when_active(self):
        """三桶配额场景：激活期间全部走规则摘要，零 LLM 调用。"""
        mark_middle_layer_active()
        hub = _FakeHub({
            "headlines": [_news_item("h1"), _news_item("h2"), _news_item("h3")],
            "macro": [_news_item("m1"), _news_item("m2")],
            "global": [_news_item("g1")],
        })
        calls: list[tuple] = []

        async def _sentinel(title, content):
            calls.append((title, content))
            return "LLM 摘要"

        with patch("app.analysis.llm.generate_news_summary",
                   side_effect=_sentinel):
            enriched = await hub.enrich_news_summaries(cap=6)

        assert calls == []
        # cap=6 → 分桶配额 3/2/1 全部由 rule 兜底填充
        assert enriched == 6
        for bucket in ("headlines", "macro", "global"):
            for n in hub._news_buckets[bucket]:
                assert n["ai_summary_source"] == "rule"
