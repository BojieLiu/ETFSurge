"""
O25 (docs/round7-rediagnosis.md §7 P25): 策略检查数据管道 + LLM 超时分级。

P25 根因:
① 采集超时全丢弃——wait_for(gather) 超时取消整个 gather，部分完成的结果拿不到
   （日志写「using partial results」实际赋 {} 全空）→ data_quality.all_empty=True
   → LLM 收到空上下文输出「数据缺失」结论。
② LLM 超时设置失衡——策略检查 30s 是全线最紧（设计 90s / provider 240s），
   数据采集也用 30s，LLM 实际剩余不足 → 恒超时 → 规则兜底常态。
③ 兜底文案固定「LLM 分析超时」不含数据质量。

修复: 采集独立 wait_for 保留部分结果 + LLM 超时按数据完整性分级
（all_empty 15s / partial 30s / full 60s）+ 兜底文案携带 data_quality。
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from app.services import portfolio_service as ps
from app.services.portfolio_service import _collect_strategy_data, _llm_timeout_for, _build_llm_fail_summary


class TestPartialCollectionKept:
    @pytest.mark.asyncio
    async def test_indicator_timeout_keeps_factors(self):
        """① 指标任务超时 → 因子结果保留（非全空）。"""
        async def slow_indicators(symbols):
            await asyncio.sleep(1.0)  # 远超 indicators_timeout
            return {"510300": {"signal": {"signal": "buy"}}}

        async def fast_factors(symbols):
            return {"510300": {"technical": 0.5}, "560600": {"technical": 0.4}}

        with patch.object(ps, "_compute_indicators", new=slow_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=fast_factors):
            indicators, factor_scores = await _collect_strategy_data(
                ["510300", "560600"], indicators_timeout=0.1, factor_timeout=5,
            )
        assert indicators == {}, "指标超时应返回 {}"
        assert factor_scores == {"510300": {"technical": 0.5}, "560600": {"technical": 0.4}}, \
            f"因子结果应保留（非全空）: {factor_scores}"

    @pytest.mark.asyncio
    async def test_factor_failure_keeps_indicators(self):
        """因子任务失败 → 指标结果保留。"""
        async def fast_indicators(symbols):
            return {"510300": {"signal": {"signal": "hold"}}}

        async def boom_factors(symbols):
            raise RuntimeError("data source down")

        with patch.object(ps, "_compute_indicators", new=fast_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=boom_factors):
            indicators, factor_scores = await _collect_strategy_data(
                ["510300"], indicators_timeout=5, factor_timeout=5,
            )
        assert indicators == {"510300": {"signal": {"signal": "hold"}}}
        assert factor_scores == {}

    @pytest.mark.asyncio
    async def test_both_ok(self):
        """正常路径：两任务均返回。"""
        async def fast_indicators(symbols):
            return {"510300": {"signal": {"signal": "hold"}}}

        async def fast_factors(symbols):
            return {"510300": {"technical": 0.5}}

        with patch.object(ps, "_compute_indicators", new=fast_indicators), \
             patch("app.factors.factor_registry.registry.compute", new=fast_factors):
            indicators, factor_scores = await _collect_strategy_data(["510300"])
        assert indicators["510300"]["signal"]["signal"] == "hold"
        assert factor_scores["510300"]["technical"] == 0.5


class TestLlmTimeoutGrading:
    def test_all_empty_15s(self):
        """② all_empty → 15s 快速兜底（上下文不足，快速失败更合理）。"""
        assert _llm_timeout_for({"all_empty": True, "partial": False}) == 15

    def test_partial_30s(self):
        assert _llm_timeout_for({"all_empty": False, "partial": True}) == 30

    def test_full_60s(self):
        assert _llm_timeout_for({"all_empty": False, "partial": False}) == 60


class TestFallbackSummaryWithQuality:
    def test_summary_includes_data_quality(self):
        """③ 兜底 summary 携带数据质量（N/M 因子可用 + 缺失原因）。"""
        summary = _build_llm_fail_summary(
            duration_s=30.0, diag="DeepSeek timeout",
            data_quality={"filled_count": 2, "total_count": 3, "partial": True},
        )
        assert "2/3" in summary, f"summary 应含因子可用数: {summary}"
        assert "因子" in summary

    def test_summary_all_empty(self):
        summary = _build_llm_fail_summary(
            duration_s=15.0, diag="timeout",
            data_quality={"filled_count": 0, "total_count": 3, "all_empty": True},
        )
        assert "0/3" in summary
        assert "数据不足" in summary or "缺失" in summary

    def test_summary_backward_compatible(self):
        """不传 data_quality 时保持旧文案结构（兼容调用方）。"""
        summary = _build_llm_fail_summary(duration_s=30.0, diag="timeout")
        assert "规则引擎兜底" in summary
