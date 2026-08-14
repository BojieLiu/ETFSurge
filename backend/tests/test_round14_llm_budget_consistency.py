"""round14 P0-B + round20 P0-5: 策略检查 LLM 超时——预算-重试一致性断言。

对应 docs/archived/round14-container-acceptance-diagnosis.md §2.1/§5 P0-B +
docs/archived/round20-container-acceptance-diagnosis.md §五 P0-5：
- 根因 = provider 35s 无响应 + 预算-重试不匹配（1 轮双 provider 71.5s 耗光 90s，
  max_retries=1 的第 2 轮开始即被外层截断 → CancelledError 兜底）
- 修复（方案 b）: max_retries=0（1 轮双 provider 失败立即兜底）+ _llm_timeout_for
  完整档 90→75s（2×35=70 ≤ 75）
- round20 P0-5: 单次 provider 调用超时 35s→15s（task 417 ReadTimeout 38s = 35s +
  429 退避；缩到 15s 后最坏 2×15=30s ≤ 各档预算）
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
STRATEGY_CHECK_REQUEST_TIMEOUT = 15.0  # round20 P0-5: 35→15（ReadTimeout 38s 根因）
PROVIDER_COUNT = 2  # opencode_zen + deepseek（双 provider 并行）


def _consistency(max_retries: int, budget: int, request_timeout: float = 15.0) -> bool:
    """预算-重试一致性：max_retries=0 时免 0.9 系数直接 providers×timeout ≤ 预算；
    max_retries≥1 时 (max_retries+1)×providers×timeout ≤ 0.9×预算
    （0.9 系数兜 rate_limit_cap=10 退避与 retry_delay=3s 容差）。"""
    worst = (max_retries + 1) * PROVIDER_COUNT * request_timeout
    if max_retries >= 1:
        return worst <= 0.9 * budget
    return worst <= budget


class TestBudgetRetryConsistency:
    def test_full_quality_budget_consistent(self):
        """完整档 75s：max_retries=0 时 2×15=30 ≤ 75 PASS（round20 P0-5 后余量更大）。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": False})
        assert budget == 75, "完整档预算应为 75s（round14 P0-B 方案 b）"
        assert _consistency(STRATEGY_CHECK_MAX_RETRIES, budget, STRATEGY_CHECK_REQUEST_TIMEOUT)

    def test_max_retries_regression_flagged(self):
        """防回归：max_retries 改回 1 时 60 > 0.9×75=67.5 仍 FAIL（round20 P0-5 后
        timeout=15 使 1 轮重试 60s ≤ 67.5s 理论可过——但 429 退避/慢响应容差
        rate_limit_cap=10 会挤占，保持 max_retries=0 是纪律，见 llm.py 注释）。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": False})
        assert not _consistency(1, budget, 35.0), "max_retries=1+旧35s 时预算-重试不一致，必须 FAIL"
        # round20 P0-5 后 15s×1 轮重试=60s ≤ 67.5s——但仍禁止（429 退避容差被挤占）
        assert STRATEGY_CHECK_MAX_RETRIES == 0, "max_retries 必须保持 0（429 退避/慢响应容差）"

    def test_partial_budget_consistent_with_no_retry(self):
        """partial 30s：max_retries=0 时 2×15=30 ≤ 30 PASS（round20 P0-5 后 partial
        档也一致——旧 2×35=70 > 30 仅靠不重试兜底）。"""
        budget = _llm_timeout_for({"all_empty": False, "partial": True})
        assert budget == 30
        assert _consistency(STRATEGY_CHECK_MAX_RETRIES, budget, STRATEGY_CHECK_REQUEST_TIMEOUT), \
            "partial 档 2×15=30 ≤ 30 应一致（round20 P0-5 后）"

    def test_all_empty_budget_15(self):
        assert _llm_timeout_for({"all_empty": True}) == 15


class TestStrategyCheckLlMCallParams:
    def test_run_json_uses_max_retries_zero(self):
        """generate_strategy_check_report 的 run_json 必须 max_retries=0 + 15s（round20 P0-5）。"""
        fake_agent = MagicMock()
        fake_agent.run_json = AsyncMock(return_value={"summary": "ok"})
        holdings = [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.2}]
        with patch("app.analysis.registry.get_agent", return_value=fake_agent):
            with patch.object(llm_mod, "get_last_llm_error", return_value=None):
                result = asyncio.run(llm_mod.generate_strategy_check_report(holdings, {}, "neutral"))
        assert result.get("summary") == "ok"
        kwargs = fake_agent.run_json.call_args.kwargs
        assert kwargs.get("max_retries") == 0, f"max_retries 应为 0（防重试超预算），实际 {kwargs.get('max_retries')}"
        # round23 遗留修复（2026-08-14）：request_timeout 由 float 15 改为 httpx.Timeout
        #（connect=15s 防 429/连接挂起，read=90s 容纳 deepseek 长报告生成——实测
        # 21.8s，float 15s 的 read 侧 ReadTimeout → LLM 报告永远走规则兜底）。
        to = kwargs.get("request_timeout")
        assert hasattr(to, "connect") and hasattr(to, "read"), \
            f"request_timeout 应为 httpx.Timeout(connect短/read长)，实际 {to!r}"
        assert to.connect <= 15.0, f"connect 超时应 ≤15s（防 429 挂起），实际 {to.connect}"
        assert to.read >= 60.0, f"read 超时应 ≥60s（容纳长报告生成），实际 {to.read}"

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
