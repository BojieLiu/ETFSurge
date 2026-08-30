"""Agentic 成本核算（v7 §6.5，REVIEW-R3-4 口径）。

单 run 预算上限 $0.5（DeepSeek-Chat $0.14/M tokens 估算 = ~3.5M tokens，
远超实际单次研判 <50k tokens）。

换算：cost = (prompt_tokens * input_price + completion_tokens * output_price) / 1e6
价格表：$/1M tokens。free 模型价格为 0；未登记模型按 deepseek-chat 官方价兜底
（宁可高估不低估——预算熔断宁严勿松）。

告警阈值（§6.5）：
- 单 run > $0.5      -> WARNING + agentic_budget_exceeded（RUN_BUDGET_USD）
- 日累计 > $5 / 月累计 > $50 -> P2 admin 面板实施时落 DAILY_/MONTHLY_ 常量
  （本模块暂只做单 run 口径——无消费点的常量会被 P3-1 未引用审计拦）
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

# $/1M tokens —— 输入, 输出（2026-08 官方牌价；free 池 0）
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    # opencode_zen / openrouter free 池：价格 0（但有日配额——配额治理在 gates.py）
}
_DEFAULT_PRICE = MODEL_PRICES["deepseek-chat"]  # 未登记模型兜底（宁高估勿低估）

RUN_BUDGET_USD = 0.5


def model_price(model: str) -> tuple[float, float]:
    """模型 -> (input_price, output_price) $/1M tokens。"""
    if not model:
        return _DEFAULT_PRICE
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    if model.endswith("-free") or "free" in model:
        return (0.0, 0.0)
    return _DEFAULT_PRICE


def compute_cost_usd(model: str, prompt_tokens: int,
                     completion_tokens: int) -> float:
    """单次调用成本 $。"""
    inp, out = model_price(model)
    return (prompt_tokens * inp + completion_tokens * out) / 1_000_000


def check_run_budget(cost_usd: float, run_id: str = "") -> bool:
    """单 run 预算检查：超限 WARNING + 返回 False（调用方决定是否截断）。"""
    if cost_usd > RUN_BUDGET_USD:
        logger.warning("[agentic-budget] run %s cost $%.4f > $%.2f "
                       "(agentic_budget_exceeded)", run_id, cost_usd, RUN_BUDGET_USD)
        return False
    return True
