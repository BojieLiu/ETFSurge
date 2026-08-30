"""v7 P2: cost.py 单测——价格表解析 + 成本计算 + 预算检查。"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agentic.cost import (
    RUN_BUDGET_USD,
    check_run_budget,
    compute_cost_usd,
    model_price,
)


class TestModelPrice:
    def test_registered_model(self):
        assert model_price("deepseek-chat") == (0.14, 0.28)

    def test_free_models_zero(self):
        assert model_price("deepseek-v4-flash-free") == (0.0, 0.0)
        assert model_price("nemotron-3-ultra-free") == (0.0, 0.0)

    def test_unknown_model_falls_back_to_deepseek_price(self):
        """未登记模型按 deepseek-chat 官方价兜底（宁高估勿低估）。"""
        assert model_price("mystery-model") == (0.14, 0.28)

    def test_empty_model_falls_back(self):
        assert model_price("") == (0.14, 0.28)


class TestComputeCost:
    def test_deepseek_chat_cost(self):
        # 1M input tokens * 0.14 = $0.14
        assert compute_cost_usd("deepseek-chat", 1_000_000, 0) == 0.14
        # 1M output tokens * 0.28 = $0.28
        assert compute_cost_usd("deepseek-chat", 0, 1_000_000) == 0.28

    def test_free_model_zero_cost(self):
        assert compute_cost_usd("deepseek-v4-flash-free", 100_000, 50_000) == 0.0

    def test_realistic_report_cost_under_budget(self):
        """真实单次研判 <50k tokens -> 成本远低于 $0.5 预算（§6.5 口径验证）。"""
        cost = compute_cost_usd("deepseek-chat", 40_000, 8_000)
        assert cost < 0.02  # 40k*0.14/1M + 8k*0.28/1M = 0.0056+0.00224 ≈ $0.0078


class TestRunBudget:
    def test_under_budget_ok(self):
        assert check_run_budget(0.10, "run-1") is True

    def test_over_budget_warns_and_returns_false(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.agentic.cost"):
            ok = check_run_budget(RUN_BUDGET_USD + 0.01, "run-2")
        assert ok is False
        assert any("agentic_budget_exceeded" in r.message for r in caplog.records)
