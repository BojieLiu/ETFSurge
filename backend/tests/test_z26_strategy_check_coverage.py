"""Test Z26: Strategy check coverage rule fallback.

Covers:
1. LLM timeout -> rule engine covers 100% of holdings
2. LLM partial coverage -> rule engine fills the gap, coverage_pct=1.0
3. LLM full coverage -> no rule suggestions, coverage_pct=1.0
4. Rule suggestion shape: action enum, confidence=0.7, source='rule'
5. Action enum restricted to increase/decrease/hold
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "short_name": "300ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.5},
    {"symbol": "518880", "name": "黄金ETF", "short_name": "黄金ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.3},
    {"symbol": "511010", "name": "国债ETF", "short_name": "国债ETF",
     "asset_type": "ETF", "portfolio_type": "on_exchange", "target_weight": 0.2},
]

_MOCK_FACTORS = {
    "510300": {"trend_1m": 0.8, "momentum_20d": 0.6, "volatility_20d": 0.1},
    "518880": {"trend_1m": -0.8, "momentum_20d": -0.7, "volatility_20d": -0.1},
    "511010": {"trend_1m": 0.1, "momentum_20d": 0.0, "volatility_20d": -0.2},
}

_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "sell"}},
    "511010": {"signal": {"signal": "hold"}},
}

_MOCK_PRICE = {"510300": (3.8, 1.2), "518880": (2.5, -0.5), "511010": (1.1, 0.1)}


@pytest.fixture
def strategy_env():
    """Patch all strategy_check data dependencies; yield a helper to set LLM result."""
    from app.services import portfolio_service as ps

    ps._strategy_check_cache.clear()
    patches = [
        patch.object(ps, "list_etfs", new_callable=AsyncMock, return_value=_MOCK_ETFS),
        patch.object(ps, "_compute_indicators", new_callable=AsyncMock, return_value=_MOCK_INDICATORS),
        patch.object(ps, "build_price_map", new_callable=AsyncMock, return_value=_MOCK_PRICE),
        patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


class TestStrategyCheckCoverage:
    """Z26: strategy check rule fallback."""

    @pytest.mark.asyncio
    async def test_llm_timeout_rule_covers_all(self, strategy_env):
        """Z26: LLM timeout -> rule engine suggestions for every holding."""
        from app.services import portfolio_service as ps
        from app.analysis.llm import generate_strategy_check_report
        from app.factors.factor_registry import registry as factor_registry

        with patch.object(generate_strategy_check_report, "__module__"):
            with patch("app.analysis.llm.generate_strategy_check_report",
                       new_callable=AsyncMock, side_effect=asyncio.TimeoutError("llm timeout")):
                with patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
                    result = await ps.strategy_check(db=None, total_capital=100000)

        assert result["suggestions"], "suggestions should not be empty"
        # Coverage must be 100%
        assert result["coverage"]["coverage_pct"] == 1.0
        assert result["coverage"]["total_holdings"] == 3
        # All suggestions are rule-generated
        for s in result["suggestions"]:
            assert s["source"] == "rule"
            assert s["action"] in ("increase", "decrease", "hold")
            assert s["confidence"] == 0.7
            assert "current_weight" in s and "suggested_weight" in s
            assert s["reason"]

    @pytest.mark.asyncio
    async def test_llm_partial_coverage_rule_fills_gap(self, strategy_env):
        """Z26: LLM covers 1 of 3 -> rule fills remaining 2, coverage 100%."""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_result = {
            "summary": "组合整体稳健",
            "suggestions": [{
                "symbol": "510300", "name": "沪深300ETF",
                "action": "increase", "current_weight": 0.5,
                "suggested_weight": 0.55, "reason": "LLM 建议",
                "confidence": 0.8,
            }],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value=llm_result):
            with patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
                result = await ps.strategy_check(db=None, total_capital=100000)

        suggestions = result["suggestions"]
        assert len(suggestions) == 3, f"expected 3 suggestions, got {len(suggestions)}"
        assert result["coverage"]["coverage_pct"] == 1.0
        assert result["coverage"]["covered_by_llm"] == 1
        assert result["coverage"]["covered_by_rule"] == 2

        by_symbol = {s["symbol"]: s for s in suggestions}
        assert by_symbol["510300"]["source"] == "llm"
        assert by_symbol["518880"]["source"] == "rule"
        assert by_symbol["511010"]["source"] == "rule"
        # 518880: factor score negative + sell signal -> decrease
        assert by_symbol["518880"]["action"] == "decrease"
        # 511010: neutral -> hold
        assert by_symbol["511010"]["action"] == "hold"

    @pytest.mark.asyncio
    async def test_llm_full_coverage_no_rule_needed(self, strategy_env):
        """Z26: LLM covers all -> no rule suggestions, coverage 100%."""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_result = {
            "summary": "组合整体稳健",
            "suggestions": [
                {"symbol": "510300", "name": "沪深300ETF", "action": "increase",
                 "current_weight": 0.5, "suggested_weight": 0.55, "reason": "a", "confidence": 0.8},
                {"symbol": "518880", "name": "黄金ETF", "action": "hold",
                 "current_weight": 0.3, "suggested_weight": 0.3, "reason": "b", "confidence": 0.8},
                {"symbol": "511010", "name": "国债ETF", "action": "hold",
                 "current_weight": 0.2, "suggested_weight": 0.2, "reason": "c", "confidence": 0.8},
            ],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value=llm_result):
            with patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
                result = await ps.strategy_check(db=None, total_capital=100000)

        assert result["coverage"]["coverage_pct"] == 1.0
        assert result["coverage"]["covered_by_rule"] == 0
        assert all(s["source"] == "llm" for s in result["suggestions"])

    @pytest.mark.asyncio
    async def test_rule_suggestion_decision_table(self, strategy_env):
        """Z26: rule decision table — strong factor + buy -> increase; weak + sell -> decrease."""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        # 510300: factor > 0.5 + buy -> increase
        factors = {
            "510300": {"trend_1m": 0.9, "momentum_20d": 0.8},
            "518880": {"trend_1m": -0.9, "momentum_20d": -0.8},
        }
        indicators = {
            "510300": {"signal": {"signal": "buy"}},
            "518880": {"signal": {"signal": "sell"}},
        }
        etfs = [
            {"symbol": "510300", "name": "沪深300ETF", "asset_type": "ETF",
             "portfolio_type": "on_exchange", "target_weight": 0.5},
            {"symbol": "518880", "name": "黄金ETF", "asset_type": "ETF",
             "portfolio_type": "on_exchange", "target_weight": 0.3},
        ]
        from app.services import portfolio_service as ps_mod
        ps_mod._strategy_check_cache.clear()
        with patch.object(ps_mod, "list_etfs", new_callable=AsyncMock, return_value=etfs), \
             patch.object(ps_mod, "_compute_indicators", new_callable=AsyncMock, return_value=indicators), \
             patch.object(ps_mod, "build_price_map", new_callable=AsyncMock,
                          return_value={"510300": (3.8, 1.0), "518880": (2.5, -1.0)}), \
             patch("app.services.market_data_hub.market_data_hub.get_market_regime", return_value="range_bound"), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=factors), \
             patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError("timeout")):
            result = await ps_mod.strategy_check(db=None, total_capital=100000)

        by_symbol = {s["symbol"]: s for s in result["suggestions"]}
        assert by_symbol["510300"]["action"] == "increase"
        # increase: min(current*1.2, 0.30 风控上限) = 0.30
        assert by_symbol["510300"]["suggested_weight"] == pytest.approx(0.30)
        assert by_symbol["518880"]["action"] == "decrease"
        # decrease: max(current*0.7, 0) = 0.21
        assert by_symbol["518880"]["suggested_weight"] == pytest.approx(0.21)
        assert result["coverage"]["coverage_pct"] == 1.0

    def test_action_enum_restricted(self):
        """Z26: rule engine only emits increase/decrease/hold."""
        from app.services.portfolio_service import _rule_based_suggestion

        for scenario in [
            ({"a": 0.9}, {"signal": "buy"}, "range_bound"),
            ({"a": -0.9}, {"signal": "sell"}, "range_bound"),
            ({"a": 0.1}, {"signal": "hold"}, "range_bound"),
            ({"a": 0.9}, {"signal": "buy"}, "bearish"),
        ]:
            suggestion = _rule_based_suggestion(
                symbol="X", name="X", target_weight=0.3,
                factor_score=scenario[0], signal=scenario[1], regime=scenario[2],
            )
            assert suggestion["action"] in ("increase", "decrease", "hold")
            assert suggestion["source"] == "rule"
            assert suggestion["confidence"] == 0.7


# ── P2-F: 成功的 LLM 报告短缓存（同持仓重复检查第 2 次起命中，不再调 LLM）──
class TestP2FLlmReportCache:
    @pytest.mark.asyncio
    async def test_second_call_hits_llm_report_cache(self, strategy_env):
        """P2-F: 同持仓同 capital 重复 strategy_check——第 2 次命中 LLM 报告缓存，
        不再调用 generate_strategy_check_report（旧实现每次 60-120s 重算）。"""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_calls = []

        async def _fake_llm(**kw):
            llm_calls.append(1)
            return {"summary": "组合稳健", "suggestions": [],
                    "holdings_analysis": [], "risk_warnings": []}

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new=AsyncMock(side_effect=_fake_llm)), \
             patch.object(factor_registry, "compute",
                          new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            r1 = await ps.strategy_check(db=None, total_capital=100000)
            r2 = await ps.strategy_check(db=None, total_capital=100000)

        assert len(llm_calls) == 1, f"第 2 次应命中缓存不再调 LLM，实际 {len(llm_calls)} 次"
        assert r2["summary"] == r1["summary"]
        # 缓存命中时 raw_llm 同源（LLM 成功报告复用）
        assert "组合稳健" in r1["summary"]

    @pytest.mark.asyncio
    async def test_llm_failure_not_cached(self, strategy_env):
        """P2-F: LLM 超时兜底不写缓存——下次检查仍会重试 LLM（不得把降级当成功复用）。"""
        from app.services import portfolio_service as ps
        from app.factors.factor_registry import registry as factor_registry

        llm_calls = []

        async def _flaky_llm(**kw):
            llm_calls.append(1)
            if len(llm_calls) == 1:
                raise asyncio.TimeoutError("llm slow")
            return {"summary": "组合稳健", "suggestions": [],
                    "holdings_analysis": [], "risk_warnings": []}

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new=AsyncMock(side_effect=_flaky_llm)), \
             patch.object(factor_registry, "compute",
                          new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            r1 = await ps.strategy_check(db=None, total_capital=100000)
            r2 = await ps.strategy_check(db=None, total_capital=100000)

        assert len(llm_calls) == 2, f"失败不缓存，第 2 次应重试 LLM，实际 {len(llm_calls)} 次"
        assert "组合稳健" in r2["summary"]


if __name__ == "__main__":
    import asyncio
    pytest.main([__file__, "-v"])