"""round51 方案 D (R167/R164): openrouter error-envelope 结构化错误 + 文案分类.

背景 (round51 §4.1):
- R167: client.py:127 `data["choices"]` 直取——openrouter 返 200-with-error-
  envelope 时 KeyError 被外层 `except Exception` 吞为 WARNING（日志仅
  `failed after 2.8s: 'choices'` 无上下文）。
- R164: reports.py:649-651 失败分类只认 429/json 关键字, KeyError('choices')
  落 else → 用户看到「LLM 分析超时」——真因被伪装, strategy_check 62 实际
  因它触发规则兜底。

修复 (方案 D):
- client.py 前置 `if "error" in data` → raise ProviderEnvelopeError
  （消息带 [envelope] 前缀, 进正常 provider 失败链: 熔断计数 + usage 记录）
- reports.py 分类逻辑抽 `_classify_llm_failure_cause` + envelope 分支
  （文案「LLM 网关返回错误信封」, 不得报「超时」）

验收负向 (文档 §4.2): mock envelope → 不得 KeyError, 需返回结构化
provider_error; summary 含「错误信封」不含「超时」。
"""
from __future__ import annotations

import json

import pytest


class _FakeResp:
    """httpx.Response 替身: 200 + 可定制的 json body。"""

    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code
        self.headers: dict = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None)

    def json(self) -> dict:
        return self._body


_ENVELOPE_BODY = {
    "error": {
        "message": "Rate limit exceeded: free-models-per-day",
        "code": 429,
    },
}


def _install_fake_httpx(monkeypatch, resp: _FakeResp) -> list[dict]:
    """把 httpx.AsyncClient.post 替换为返回固定 resp 的假客户端。

    返回 captures 列表（记录每次 post 的 url），供断言请求确实发出。
    """
    import httpx

    captures: list[dict] = []

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            captures.append({"url": url, **{k: v for k, v in kw.items()
                                            if k in ("json", "headers")}})
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return captures


def _stub_llm_env(monkeypatch):
    """隔离 llm_complete 外围: key 检查 / 配额门 / 熔断 / usage 记录。"""
    import app.analysis.llm.client as cl

    monkeypatch.setattr(cl, "has_any_api_key", lambda: True)
    monkeypatch.setattr(cl.llm_quota_gate, "acquire",
                        _async_noop, raising=False)
    monkeypatch.setattr(cl, "_circuit_allow", lambda *a, **kw: True)
    monkeypatch.setattr(cl, "_circuit_record_failure", lambda *a, **kw: None)
    monkeypatch.setattr(cl, "_circuit_record_success", lambda *a, **kw: None)
    monkeypatch.setattr(cl, "_record_llm_error", lambda *a, **kw: None)
    monkeypatch.setattr(cl, "mark_middle_layer_active", lambda *a, **kw: None)
    monkeypatch.setattr(cl.token_store, "record", _async_noop)


async def _async_noop(*a, **kw):
    return None


def _fake_provider(monkeypatch):
    import app.analysis.llm.client as cl

    p = cl.ProviderConfig(
        id="openrouter",
        name="OpenRouter",
        api_url="https://openrouter.test/api/v1/chat/completions",
        api_key="sk-test",
        model="deepseek/deepseek-v4-free",
        timeout=5,
    )
    monkeypatch.setattr(cl, "get_configured_providers", lambda: [p])
    return p


class TestEnvelopeStructuredError:
    """R167: 200+error-envelope → ProviderEnvelopeError（非裸 KeyError）。"""

    @pytest.mark.asyncio
    async def test_envelope_raises_provider_envelope_error(self, monkeypatch):
        import app.analysis.llm.client as cl

        _stub_llm_env(monkeypatch)
        _fake_provider(monkeypatch)
        _install_fake_httpx(monkeypatch, _FakeResp(_ENVELOPE_BODY))

        with pytest.raises(cl.ProviderEnvelopeError) as ei:
            await cl.llm_complete("hi", max_retries=0)

        # 错误消息含可分类标记与 provider/model 上下文（旧实现仅 'choices'）
        msg = str(ei.value)
        assert "[envelope]" in msg
        assert "openrouter" in msg
        assert "Rate limit exceeded" in msg

    @pytest.mark.asyncio
    async def test_normal_response_still_works(self, monkeypatch):
        """正向回归: 正常 shape（choices[0].message.content）不受影响。"""
        import app.analysis.llm.client as cl

        _stub_llm_env(monkeypatch)
        _fake_provider(monkeypatch)
        body = {"choices": [{"message": {"content": "hello world"}}],
                "usage": {"total_tokens": 5}}
        _install_fake_httpx(monkeypatch, _FakeResp(body))

        out = await cl.llm_complete("hi", max_retries=0)
        assert out == "hello world"

    @pytest.mark.asyncio
    async def test_envelope_with_choices_key_not_treated_as_envelope(self):
        """shape 既有 error 又有 choices（理论上不存在）——不误判, 走原逻辑。"""
        from app.analysis.llm.client import _is_error_envelope

        assert _is_error_envelope({"error": {}, "choices": []}) is False
        assert _is_error_envelope({"error": {}}) is True
        assert _is_error_envelope({"choices": []}) is False
        assert _is_error_envelope("not a dict") is False


class TestGateRecordsEnvelope:
    """gates._record_llm_error 对 envelope 异常记 [envelope] 前缀（供分类）。"""

    def test_record_llm_error_envelope_prefix(self):
        from app.analysis.llm import gates
        from app.analysis.llm.client import ProviderEnvelopeError

        exc = ProviderEnvelopeError(
            "[envelope] openrouter: Rate limit exceeded")
        gates._record_llm_error(exc)
        assert (gates.get_last_llm_error() or "").startswith("[envelope]")


class TestR186EnvelopeFallbackRecognition:
    """R186 (round55 §4.1 方案A): strategy_check F1-9 兜底识别器必须认出
    envelope 前缀——check108 实证 summary 明写「已用规则引擎兜底」而
    is_fallback=False/quality=full（识别器仅匹配旧 3 前缀，漏网）。

    负向断言：旧实现跑本用例必 FAIL（无 envelope 分支）。
    """

    def test_envelope_summary_recognized_as_fallback(self):
        import inspect

        from app.core.llm_fallback_prefixes import is_llm_fallback_summary
        from app.services.portfolio import strategy_check as sc

        # check108 同形态 summary（含网关信封 + 最后错误 + 市态后缀）
        summary = (
            "LLM 网关返回错误信封（30s，已用规则引擎兜底）"
            "（最后错误: [envelope] openrouter/nvidia/nemotron-3-ultra-550b"
            "-a55b:free: Upstream error from Nvidia (code=502)）"
            "（市态：震荡；因子覆盖 33.3%）"
        )
        assert is_llm_fallback_summary(summary) is True
        # 接线守卫：识别器必须走收敛 helper（防改 helper 不改调用点）
        assert "is_llm_fallback_summary" in inspect.getsource(sc)

    def test_legacy_three_prefixes_still_recognized(self):
        from app.core.llm_fallback_prefixes import is_llm_fallback_summary

        for prefix in ("LLM 分析超时", "LLM 分析配额耗尽", "LLM 分析结果解析失败"):
            assert is_llm_fallback_summary(prefix + "（30s，已用规则引擎兜底）") is True
        # 正常报告不得误判
        assert is_llm_fallback_summary("本组合攻守兼备，建议维持现状。") is False
        assert is_llm_fallback_summary("") is False


class TestR186PrefixConvergence:
    """R186 (round55 §4.2 方案B): 分类器全分支输出前缀 ∈ FALLBACK_PREFIXES。

    长治断言：任一新增文案分支不同步到常量集必红（R163→R177→R186 第四次复发口子）。
    """

    def test_classifier_outputs_within_prefix_set(self):
        from app.analysis.llm.reports import _classify_llm_failure_cause
        from app.core.llm_fallback_prefixes import FALLBACK_PREFIXES

        cases = [
            "[envelope] openrouter: Rate limit exceeded",
            "429 Too Many Requests",
            "expecting value: line 1 column 1",
            "connection reset by peer",
        ]
        assert len(FALLBACK_PREFIXES) >= 4
        for raw in cases:
            out = _classify_llm_failure_cause(raw, 30.0)
            assert out.startswith(tuple(FALLBACK_PREFIXES)), f"分支输出逃逸常量集: {out}"
            from app.core.llm_fallback_prefixes import is_llm_fallback_summary

            assert is_llm_fallback_summary(out) is True


class TestReportsClassification:
    """R164: envelope 失败 → 「错误信封」文案, 不得报「超时」。"""

    def test_envelope_classified_as_gateway_error(self):
        from app.analysis.llm.reports import _classify_llm_failure_cause

        cause = _classify_llm_failure_cause(
            "[envelope] openrouter: Rate limit exceeded", 30.0)
        assert "错误信封" in cause
        assert "超时" not in cause

    def test_429_still_quota(self):
        from app.analysis.llm.reports import _classify_llm_failure_cause

        cause = _classify_llm_failure_cause("429 Too Many Requests", 30.0)
        assert "配额耗尽" in cause

    def test_json_parse_still_parse(self):
        from app.analysis.llm.reports import _classify_llm_failure_cause

        cause = _classify_llm_failure_cause(
            "expecting value: line 1 column 1", 30.0)
        assert "解析失败" in cause

    def test_unknown_still_timeout(self):
        from app.analysis.llm.reports import _classify_llm_failure_cause

        cause = _classify_llm_failure_cause(
            "connection reset by peer", 30.0)
        assert "超时" in cause
