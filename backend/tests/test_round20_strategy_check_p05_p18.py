"""
round20 P0-5 + P1-8 (docs/round20-container-acceptance-diagnosis.md §五):
策略检查 LLM 超时优化 + 规则引擎 reason/action/confidence 与数据支持匹配。

TDD 顺序：本文件为「先写失败单测」阶段——以下断言当前实现必然 FAIL：
  - P0-5①: generate_strategy_check_report 单次 provider 调用超时仍 35s（应 15s）；
  - P0-5②: opencode_zen 429 后仍在后续 attempt 反复重试（应立即降级 deepseek 不重试）；
  - P1-8②: holdings_analysis 无 action/suggested_weight（与 suggestions 同源）；
  - P1-8①③: reason 不得含「基本面」当因子填充率<50%；填充率<70% 置信度不得 high。

修复：llm.py request_timeout 35→15；429 标记 provider 跳过后续 attempt；
portfolio_service.py 为 holdings_analysis 注入 action/suggested_weight（复用规则引擎）。

纯逻辑测试（mock LLM 网络）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ─── P0-5①: LLM 单次调用超时 38s→15s ─────────────────────────────

class TestP0_5LLMTimeout:
    @pytest.mark.asyncio
    async def test_strategy_check_report_uses_15s_timeout(self):
        """P0-5: generate_strategy_check_report 单次 provider 调用超时必须 15s（非 35s）。"""
        from app.analysis import llm as llm_mod

        run_json_mock = AsyncMock(return_value={
            "summary": "ok", "suggestions": [], "holdings_analysis": [],
            "risk_warnings": [],
        })
        agent_mock = MagicMock()
        agent_mock.run_json = run_json_mock
        # generate_strategy_check_report 内部 `from ..analysis.registry import get_agent`（局部导入）
        with patch("app.analysis.registry.get_agent", return_value=agent_mock):
            await llm_mod.generate_strategy_check_report(
                market_data=[{"symbol": "510300", "name": "沪深300", "target_weight": 0.3}],
                factor_breakdowns={"510300": {"factor_scores": {}, "technical_signal": {}}},
                regime="range_bound",
                data_quality={"all_empty": True, "partial": False},
            )
        _, kwargs = run_json_mock.call_args
        assert kwargs.get("request_timeout", 35.0) <= 15.0, (
            f"LLM 单次调用超时应为 15s（ReadTimeout 38s 根因），实际 {kwargs.get('request_timeout')}"
        )


# ─── P0-5②: 429 立即降级，不再反复重试 ───────────────────────────

class TestP0_5RateLimitFailover:
    @pytest.mark.asyncio
    async def test_429_primary_skipped_on_retry_attempt(self):
        """P0-5: opencode_zen 429 → 本轮切 deepseek；后续 attempt 不再重试 429 的 provider。

        旧行为：max_retries=1 时第 2 轮又重试 opencode_zen（429 每 2-3s 失败一次，
        task 417 日志实证）。修复后 429 的 provider 标记跳过，只走 deepseek。
        """
        from app.analysis import llm as llm_mod
        import httpx

        # 模拟两个 provider：opencode_zen(429) + deepseek(200 成功)
        calls = {"opencode_zen": 0, "deepseek": 0}

        class _FakeResp:
            def __init__(self, status, json_data=None, headers=None):
                self.status_code = status
                self._json = json_data or {}
                self.headers = headers or {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        f"HTTP {self.status_code}", request=MagicMock(), response=self,
                    )

            def json(self):
                return self._json

        class _FakeClient:
            def __init__(self, provider_id):
                self._pid = provider_id

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **kw):
                calls[self._pid] += 1
                if self._pid == "opencode_zen":
                    return _FakeResp(429, headers={"retry-after": "1"})
                return _FakeResp(200, {
                    "choices": [{"message": {"content": '{"summary": "ok"}'}}],
                    "usage": {},
                })

        providers = [
            MagicMock(id="opencode_zen", model="m1", api_url="http://x", api_key="k",
                      timeout=15),
            MagicMock(id="deepseek", model="m2", api_url="http://y", api_key="k",
                      timeout=15),
        ]
        fake_clients = {
            "opencode_zen": _FakeClient("opencode_zen"),
            "deepseek": _FakeClient("deepseek"),
        }

        async def _fake_async_client_factory(*a, **kw):
            # 根据调用侧 provider 区分 client——通过当前尝试的 provider id 无法从
            # 工厂得知，改用按调用顺序回退：第一次 429 后第二次应为 deepseek。
            return _FakeClient("opencode_zen" if calls["opencode_zen"] + calls["deepseek"] < 1 else "deepseek")

        # 模拟 provider 序列：[opencode_zen(429), deepseek(200)]——注意第二 attempt
        # 修复后不得再出现 opencode_zen（429 标记跳过）。按调用顺序给 client。
        seq = [_FakeClient("opencode_zen"), _FakeClient("deepseek")]
        it = iter(seq)

        def _factory(*a, **kw):
            try:
                return next(it)
            except StopIteration:
                return _FakeClient("deepseek")

        with patch("httpx.AsyncClient", side_effect=_factory), \
             patch.object(llm_mod, "get_configured_providers", return_value=providers), \
             patch.object(llm_mod, "_check_key", new=AsyncMock()):
            # max_retries=1：修复前第 2 轮会再打 opencode_zen（calls>=2），修复后只 1 次
            result = await llm_mod.llm_complete_with_system(
                system_prompt="s", prompt="p", max_retries=1, rate_limit_cap=1.0,
                request_timeout=15.0,
            )

        assert "ok" in result
        assert calls["opencode_zen"] == 1, (
            f"429 后不应再重试 opencode_zen（反复 429 重试即 task 417 根因），实际 {calls['opencode_zen']} 次"
        )
        assert calls["deepseek"] >= 1, "429 后应立即降级 deepseek"


# ─── P1-8②: holdings_analysis 携带 action/suggested_weight ──────

class TestP1_8HoldingsAction:
    def test_rule_fallback_holdings_analysis_has_action(self):
        """P1-8: 规则兜底 holdings_analysis 骨架必须带 action/suggested_weight（D-B2 割裂）。"""
        from app.services.portfolio_service import _build_rule_fallback_holdings_analysis

        etfs = [{"symbol": "510300", "name": "沪深300", "target_weight": 0.3}]
        market_data = [{"symbol": "510300", "name": "沪深300", "target_weight": 0.3,
                        "price": 4.0, "change_pct": 0.5}]
        factor_breakdowns = {
            "510300": {
                "factor_scores": {"technical.momentum": 0.6},
                "technical_signal": {"signal": "buy"},
                "technical_indicators": {},
            }
        }
        rows = _build_rule_fallback_holdings_analysis(
            etfs=etfs, market_data=market_data,
            factor_breakdowns=factor_breakdowns, weight_map={"510300": 0.3},
        )
        assert rows, "应生成 holdings_analysis 骨架"
        h = rows[0]
        assert h.get("action") in ("increase", "decrease", "hold"), (
            f"holdings_analysis 缺 action（与 suggestions 割裂）: {h}"
        )
        assert h.get("suggested_weight") is not None, "holdings_analysis 缺 suggested_weight"


# ─── P2-4: 多因子评分注释与数据一致 ─────────────────────────────

class TestP2_4FactorScoreNote:
    def test_factor_score_note_not_claiming_0_1(self):
        """P2-4: 报告注释不得称「0~1」（实测 511090=-2.31 超范围）；
        应改为「可负可超 1，区别于技术信号」。"""
        from app.tasks.design_report import _build_plan_tables

        strategies = [{
            "label": "稳健型", "positioning": "稳健", "expected_return": 0.08,
            "expected_return_current": 0.08, "max_drawdown": 0.1, "sharpe_ratio": 1.0,
            "expected_characteristics": "", "id": "balanced",
            "allocations": [{
                "symbol": "511090", "name": "30年国债ETF", "layer": "defense",
                "weight": 0.2, "factor_score": -2.31, "factor_breakdown": {},
                "daily_change_pct": 0.1, "selection_rationale": "低相关对冲",
            }],
        }]
        md = _build_plan_tables(strategies)
        assert "多因子综合分（可负可超 1" in md, "注释应明示可负可超 1"
        assert "（0~1）" not in md, f"注释不得再声称 0~1 范围（511090=-2.31 实测超范围）: {md}"


# ─── P2-4 结束 ──────────────────────────────────────────────────

class TestP1_8ReasonAndConfidence:
    def test_reason_no_basics_when_factor_sparse(self):
        """P1-8: 因子填充率<50% 时 reason 不得含「基本面」（无基本面数据拼「基本面共振」= 失真）。"""
        from app.services.portfolio_service import _rule_based_suggestion

        s = _rule_based_suggestion(
            symbol="510300", name="沪深300", target_weight=0.3,
            factor_score={"technical.momentum": 0.6, "technical.rsi": 0.4},
            signal={"signal": "buy"}, regime="range_bound",
            current_weight=0.25, factor_availability={"filled": 1, "total": 3},
        )
        assert "基本面" not in s["reason"], f"无基本面数据时 reason 不得含「基本面」: {s['reason']}"

    def test_confidence_medium_when_fill_below_70(self):
        """P1-8: factor_availability 填充率 <70% → confidence 不得为 high（应 medium）。"""
        from app.services.portfolio_service import _rule_based_suggestion

        s = _rule_based_suggestion(
            symbol="512480", name="半导体", target_weight=0.2,
            factor_score={"technical.momentum": 0.8},
            signal={"signal": "buy"}, regime="range_bound",
            current_weight=0.2, factor_availability={"filled": 2, "total": 5},
        )
        assert s["confidence"] != "high", (
            f"填充率 2/5=40%<70% 不得 high，实际 {s['confidence']}"
        )
