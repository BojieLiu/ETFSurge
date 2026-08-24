# -*- coding: utf-8 -*-
"""round29 R70 / R70b: LLM 配额诚实降级 + 设计报告 connect 对齐。

R70（§14.1）: 策略检查 LLM 失败后 summary 用「LLM 分析超时」掩盖真实原因
（429 配额耗尽 / JSONDecodeError）→ 改为按错误诊断区分「配额耗尽」「解析失败」「超时」。
R70b（§14.1）: `generate_design_report` 仍 `connect=15.0`（R57 只改了策略检查路径，
设计报告路径同脆弱点）→ 对齐 60s。

无网络：get_agent.run_json 全部 monkeypatch。
"""
import asyncio

import pytest

from app.analysis import llm


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


class _QuotaError(RuntimeError):
    def __init__(self):
        super().__init__("quota_exhausted: free tier limit reached")
        self.response = _FakeResp(429)


class _JSONError(ValueError):
    def __init__(self):
        super().__init__("Expecting value: line 1 column 1 (char 0)")


@pytest.fixture
def patch_run_json(monkeypatch):
    import app.analysis.llm.gates as gates

    def _set_error(exc):
        gates._record_llm_error(exc)

    monkeypatch.setattr(gates, "_record_llm_error", _set_error)
    return monkeypatch


def _call_strategy_check(monkeypatch, exc, last_err):
    """触发 reports.generate_strategy_check_report 的兜底分支并返回结果。"""
    import app.analysis.llm.gates as gates
    from app.analysis.llm import reports

    async def _boom(*a, **k):
        raise exc

    class _Agent:
        async def run_json(self, *a, **k):
            await _boom()

    monkeypatch.setattr(gates, "_last_llm_error", last_err)
    monkeypatch.setattr("app.analysis.registry.get_agent", lambda name: _Agent())

    async def _run():
        return await reports.generate_strategy_check_report(
            market_data=[{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3}],
            factor_breakdowns={"510300": {"factor_scores": {"momentum": 0.5}, "technical_signal": {}}},
            regime="range_bound",
            data_quality=None,
        )
    return asyncio.get_event_loop().run_until_complete(_run())


class TestR70QuotaHonestDegradation:
    def test_quota_exhausted_summary_mentions_quota(self, monkeypatch):
        """429 配额耗尽 → summary 含「配额」关键词，不得用「超时」掩盖真实原因。"""
        out = _call_strategy_check(monkeypatch, _QuotaError(),
                                   last_err="[rate-limited] 429 Too Many Requests")
        assert "配额" in out["summary"], f"配额文案缺失: {out['summary']}"
        assert "超时" not in out["summary"].split("（")[0], \
            f"429 被误标为超时: {out['summary']}"

    def test_timeout_summary_still_says_timeout(self, monkeypatch):
        """真超时 → 仍标「超时」（不误伤）。"""
        out = _call_strategy_check(monkeypatch, asyncio.TimeoutError("read timed out"),
                                   last_err="[timeout] connection timed out")
        assert "超时" in out["summary"]

    def test_json_decode_summary_mentions_parse_failure(self, monkeypatch):
        """JSONDecodeError → summary 提及「解析失败」而非「超时」。"""
        out = _call_strategy_check(monkeypatch, _JSONError(),
                                   last_err="Expecting value: line 1 column 1 (char 0)")
        assert "解析失败" in out["summary"] or "解析" in out["summary"], \
            f"JSON 解析失败被掩盖: {out['summary']}"
        assert "超时" not in out["summary"].split("（")[0]


class TestR70bDesignReportConnectAligned:
    def test_generate_design_report_uses_connect_60(self):
        """设计报告路径 connect 必须对齐 60s（R57 只改了策略检查路径）。

        round35 §19 GapE 收敛后：connect/read/write/pool 四元组字面量上移至
        core/llm_timeouts 单源——本钉定改为验证「路径走收敛 helper + 预算
        常量」且合成 Timeout 的 connect 行为不变量仍为 60s（防回潮）。
        """
        import inspect

        from app.analysis.llm import reports
        from app.core.llm_timeouts import (
            DESIGN_REPORT_READ_S,
            LLM_HTTP_CONNECT_S,
            llm_http_timeout,
        )

        src = inspect.getsource(reports.generate_design_report)
        assert "llm_http_timeout(read_s=DESIGN_REPORT_READ_S)" in src, \
            "generate_design_report 未走 §19 GapE 收敛超时 helper"
        assert "httpx.Timeout(" not in src, "四元组字面量不得回潮（应走 llm_http_timeout）"
        # 行为不变量保持：该路径合成 Timeout 的 connect 必须仍是 60s
        assert llm_http_timeout(DESIGN_REPORT_READ_S).connect == LLM_HTTP_CONNECT_S == 60.0
