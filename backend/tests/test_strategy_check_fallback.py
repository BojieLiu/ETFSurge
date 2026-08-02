"""
U2/N01 (round2-unfixed-fix-plan.md U2 / round3-diagnosis-and-optimization-plan.md N01
+ factor-and-strategy-check-review.md 问题3): 策略检查报告质量。

- U2 R1: rule 兜底生成 report_text（市态/因子/风险/建议，长度 >500）。
- U2 R3: LLM 超时 20s → 60s。
- U2 R2: report_text 为空 → 任务 failed。
- 问题3 R2: _rule_based_suggestion 决策表分档（hold 带因子分/信号依据）。
- 问题3 R3: 风险兜底诚实化（LLM 超时/因子缺失 → warning 级）。

mock 数据源与 LLM，无网络。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services import portfolio_service as ps
from app.services.portfolio_service import (
    _combine_risk_warnings,
    _rule_based_suggestion,
)


_MOCK_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.4, "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "518880", "name": "黄金ETF", "target_weight": 0.3, "asset_type": "ETF", "portfolio_type": "on_exchange"},
    {"symbol": "511010", "name": "国债ETF", "target_weight": 0.2, "asset_type": "ETF", "portfolio_type": "on_exchange"},
]

_MOCK_INDICATORS = {
    "510300": {"signal": {"signal": "buy"}},
    "518880": {"signal": {"signal": "sell"}},
    "511010": {"signal": {"signal": "hold"}},
}

_MOCK_FACTORS = {
    "510300": {"technical": 0.8, "momentum": 0.6},
    "518880": {"technical": -0.7, "momentum": -0.5},
    "511010": {"technical": 0.1, "momentum": 0.0},
}

_MOCK_PRICE = {"510300": (3.8, 1.2), "518880": (2.5, -0.5), "511010": (1.1, 0.1)}


@pytest.fixture
def strategy_env():
    """Patch all strategy_check data dependencies."""
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


class TestReportTextFallback:
    @pytest.mark.asyncio
    async def test_llm_timeout_generates_report_text(self, strategy_env):
        """U2 R1: LLM 超时 → report_text 非空、长度 >500、含三节。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError("llm timeout")), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        report = result.get("report_text", "")
        assert report, "report_text 不得为空（旧 bug: task 66 report_text len=0）"
        assert len(report) > 500, f"report_text 长度 {len(report)} 应 >500"
        assert "策略检查报告" in report
        assert "市态" in report
        assert "因子" in report
        assert "风险提示" in report
        assert "操作建议" in report

    @pytest.mark.asyncio
    async def test_llm_timeout_risk_warning_is_warning_level(self, strategy_env):
        """问题3 R3: LLM 超时 → 风险提示为 warning 级且标注降级。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError("llm timeout")), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        warnings = result["risk_warnings"]
        assert warnings, "risk_warnings 不得为空"
        assert warnings[0]["severity"] == "warning", \
            f"LLM 超时时风险提示应为 warning 级（诚实降级），实际 {warnings[0]['severity']}"
        assert "LLM 分析超时" in warnings[0]["description"]

    @pytest.mark.asyncio
    async def test_all_empty_factors_risk_warning(self, strategy_env):
        """问题3 R3: 因子全空 → 风险提示 warning 级并标注因子数据不可用。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value={
                       "summary": "组合稳健", "suggestions": [],
                       "holdings_analysis": [], "risk_warnings": [],
                   }), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value={}):
            result = await ps.strategy_check(db=None, total_capital=100000)

        warnings = result["risk_warnings"]
        assert warnings[0]["severity"] == "warning"
        assert "因子数据不可用" in warnings[0]["description"], \
            "因子全空时不得显示'风险指标正常'（误导）"

    @pytest.mark.asyncio
    async def test_normal_path_info_warning(self, strategy_env):
        """回归: LLM 正常 + 因子可用 → info 级'风险指标正常'。"""
        from app.factors.factor_registry import registry as factor_registry

        with patch("app.analysis.llm.generate_strategy_check_report",
                   new_callable=AsyncMock, return_value={
                       "summary": "组合稳健", "suggestions": [],
                       "holdings_analysis": [], "risk_warnings": [],
                   }), \
             patch.object(factor_registry, "compute", new_callable=AsyncMock, return_value=_MOCK_FACTORS):
            result = await ps.strategy_check(db=None, total_capital=100000)

        warnings = result["risk_warnings"]
        assert warnings[0]["severity"] == "info", "正常路径应保持 info 级"


class TestRuleSuggestionEnhancement:
    def test_buy_with_mid_factor_holds_with_reason(self):
        """问题3 R2: avg_factor ∈ (0.2, 0.5) + buy → hold，reason 带因子分。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.4,
            factor_score={"technical": 0.3, "momentum": 0.3},
            signal={"signal": "buy"}, regime="range_bound",
        )
        assert s["action"] == "hold"
        assert "未达增仓阈值" in s["reason"], s["reason"]

    def test_strong_buy_increases(self):
        """avg_factor > 0.5 + buy → increase（受 30% 单只风控上限约束）。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.2,
            factor_score={"technical": 0.8, "momentum": 0.6},
            signal={"signal": "buy"}, regime="range_bound",
        )
        assert s["action"] == "increase"
        assert s["suggested_weight"] == pytest.approx(0.24)  # 0.2 × 1.2

    def test_strong_sell_decreases(self):
        """avg_factor < -0.5 + sell → decrease。"""
        s = _rule_based_suggestion(
            symbol="518880", name="黄金ETF", target_weight=0.3,
            factor_score={"technical": -0.7, "momentum": -0.5},
            signal={"signal": "sell"}, regime="range_bound",
        )
        assert s["action"] == "decrease"

    def test_hold_reason_has_factor_and_signal(self):
        """问题3 R2: hold 的 reason 带因子分与信号（不再裸'维持现状'）。"""
        s = _rule_based_suggestion(
            symbol="511010", name="国债ETF", target_weight=0.2,
            factor_score={"technical": 0.05},
            signal={"signal": "hold"}, regime="range_bound",
        )
        assert s["action"] == "hold"
        assert "因子分" in s["reason"] and "信号" in s["reason"], s["reason"]
        assert s["reason"] != "维持现状"

    def test_weight_drift_regression(self):
        """问题3 R2: |current - target| > 20% → 向 target 回归。"""
        s = _rule_based_suggestion(
            symbol="510300", name="沪深300ETF", target_weight=0.4,
            factor_score={"technical": 0.1},
            signal={"signal": "hold"}, regime="range_bound",
            current_weight=0.3,
        )
        # |0.3 - 0.4| / 0.4 = 25% > 20% → increase 回归
        assert s["action"] == "increase", s["reason"]
        assert "偏离目标权重" in s["reason"]


class TestRiskCombineHonesty:
    def test_llm_failed_warning(self):
        """问题3 R3: llm_failed → warning 级。"""
        warnings = _combine_risk_warnings([], [], llm_failed=True)
        assert warnings[0]["severity"] == "warning"
        assert "LLM 分析超时" in warnings[0]["description"]

    def test_data_empty_warning(self):
        """问题3 R3: data_all_empty → warning 级。"""
        warnings = _combine_risk_warnings([], [], data_all_empty=True)
        assert warnings[0]["severity"] == "warning"
        assert "因子数据不可用" in warnings[0]["description"]

    def test_normal_info(self):
        """回归: 正常路径 info 级。"""
        warnings = _combine_risk_warnings([], [])
        assert warnings[0]["severity"] == "info"
