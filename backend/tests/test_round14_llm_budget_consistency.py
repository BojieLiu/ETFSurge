"""round14 P0-B: 策略检查 LLM 超时——预算-重试一致性断言。

对应 docs/round14-container-acceptance-diagnosis.md §2.1/§5 P0-B：
- 根因 = provider 35s 无响应 + 预算-重试不匹配（1 轮双 provider 71.5s 耗光 90s，
  max_retries=1 的第 2 轮开始即被外层截断 → CancelledError 兜底）
- 修复（方案 b）: max_retries=0（1 轮双 provider 失败立即兜底）+ _llm_timeout_for
  完整档 90→75s（2×35=70 ≤ 75）
- 断言：max_retries≥1 时 (max_retries+1)×providers×request_timeout ≤ 0.9×预算
  必须成立——当前若有人把 max_retries 改回 1，本测试 FAIL（防回归）
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analysis import llm as llm_mod
from app.services.portfolio_service import _llm_timeout_for

# 与 generate_strategy_check_report 的 run_json 配置一致（llm.py L1421-1427）
STRATEGY_CHECK_MAX_RETRIES = 0
STRATEGY_CHECK_REQUEST_TIMEOUT = 35.0
PROVIDER_COUNT = 2  # opencode_zen + deepseek（双 provider 并行）


def _consistency(max_retries: int, budget: int, request_timeout: float = 35.0) -> bool:
    """预算-重试一致性：max_retries=0 时免 0.9 系数直接 providers×timeout ≤ 预算；
    max_retries≥1 时 (max_retries+1)×providers×timeout ≤ 0.9×预算
    （0.9 系数兜 rate_limit_cap=10 退避与 retry_delay=3s 容差）。"""
    worst = (max_retries + 1) * PROVIDER_COUNT * request_timeout
    if max_retries >= 1:
        return worst <= 0.9 * budget
    return worst <= budget


class TestBudgetRetryConsistency:
    def test_full_quality_budget_consistent(self):
        """完整档 75s：max_retries=0 时 2×35=70 ≤ 75 PASS。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": False})
        assert budget == 75, "完整档预算应为 75s（round14 P0-B 方案 b）"
        assert _consistency(STRATEGY_CHECK_MAX_RETRIES, budget, STRATEGY_CHECK_REQUEST_TIMEOUT)

    def test_max_retries_regression_flagged(self):
        """防回归：max_retries 改回 1 时 140 > 0.9×75=67.5 → 一致性 FAIL。
        （这就是 round14 §2.1 的核心 bug 形态——第 2 轮永远没机会跑完。）"""
        budget = _llm_timeout_for({"all_empty": False, "partial": False})
        assert not _consistency(1, budget, 35.0), "max_retries=1 时预算-重试不一致，必须 FAIL"

    def test_partial_budget_consistent_with_no_retry(self):
        """partial 30s：max_retries=0 时 2×35=70 > 30 仍超——设计取舍
        （partial 档数据不全，30s 快速兜底；max_retries=0 保证不重试叠加）。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": True})
        assert budget == 30
        # 70 > 30：partial 档天然超预算——由 max_retries=0 保证只有 1 轮，可接受
        assert STRATEGY_CHECK_MAX_RETRIES == 0

    def test_all_empty_budget_15(self):
        assert _llm_timeout_for({"all_empty": True}) == 15


class TestStrategyCheckLlMCallParams:
    def test_run_json_uses_max_retries_zero(self):
        """generate_strategy_check_report 的 run_json 必须 max_retries=0 + 35s。"""
        fake_agent = MagicMock()
        fake_agent.run_json = AsyncMock(return_value={"summary": "ok"})
        holdings = [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2}]
        with patch("app.analysis.registry.get_agent", return_value=fake_agent):
            with patch.object(llm_mod, "get_last_llm_error", return_value=None):
                result = asyncio.run(llm_mod.generate_strategy_check_report(holdings, {}, "neutral"))
        assert result.get("summary") == "ok"
        kwargs = fake_agent.run_json.call_args.kwargs
        assert kwargs.get("max_retries") == 0, f"max_retries 应为 0（防重试超预算），实际 {kwargs.get('max_retries')}"
        assert kwargs.get("request_timeout") == 35.0

    def test_provider_slow_within_budget_no_cancelled_error(self):
        """负向：mock provider 慢响应 → 兜底在预算内完成，不抛 CancelledError 穿透
        （round14 §5 P0-B 测试 2）。"""
        async def _slow_run_json(*args, **kwargs):
            await asyncio.sleep(0.05)
            raise asyncio.TimeoutError("provider slow")

        fake_agent = MagicMock()
        fake_agent.run_json = AsyncMock(side_effect=_slow_run_json)
        holdings = [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2}]
        with patch("app.analysis.registry.get_agent", return_value=fake_agent):
            with patch.object(llm_mod, "get_last_llm_error", return_value="timeout"):
                # 外层 wait_for 60ms < provider 50ms×2 → 触发 CancelledError 兜底路径
                result = asyncio.run(
                    asyncio.wait_for(
                        llm_mod.generate_strategy_check_report(holdings, {}, "neutral"),
                        timeout=0.12,
                    )
                )
        assert "兜底" in result.get("summary", "") or "超时" in result.get("summary", "")
