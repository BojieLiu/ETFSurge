"""round15 方案二: composite 分量量纲统一（docs §5.2/§7 负向断言 2）。

- 区分度恢复断言：同层 A（fund_scale=2000 亿、factor_sum=0）vs B（30 亿、factor_sum=0），
  balanced/neutral 市态 composite(A) > composite(B)——修复前两者 scale 分都≈0 无法区分
  （*1e-9 与亿口径错配），修复前必失败。
- 因子主导性断言：A（2000 亿、factor_sum=+9）vs B（2000 亿、factor_sum=0）→
  composite(A) > composite(B) 且 factor 项贡献占比 > 50%（防量纲统一后反被规模压死）。
- 向后兼容：layer_amounts=None（research/opportunistic/外部调用）→ 旧 *1e-9 路径不变。
"""
import math
from unittest.mock import patch

import pytest

from app.services.market_data_hub import MarketDataHub


def _hub():
    h = MarketDataHub()
    # 固定「交易时段」，避免非交易时段 P6 分支（liquidity 减半）影响断言
    patcher = patch.object(h, "_is_market_hours", return_value=True)
    patcher.start()
    h.__market_hours_patcher = patcher  # 保持引用防 GC
    return h


def _item(amount: float, scale: float, factor_sum: float = 0.0):
    return {
        "amount": amount,
        "fund_scale": scale,
        "factor_scores": {"technical": factor_sum, "momentum": 0.0,
                          "valuation": 0.0, "sentiment": 0.0},
    }


class TestCompositeUnifiedScale:
    def test_scale_discrimination_restored(self):
        """2000 亿 vs 30 亿（factor_sum 均 0）→ composite 可区分（修复前 scale 分都≈0）。"""
        hub = _hub()
        big = _item(amount=1e9, scale=2000.0)
        small = _item(amount=1e9, scale=30.0)
        amounts = [1e9, 1e9]
        scales = [2000.0, 30.0]
        s_big = hub._compute_composite(big, "core", "neutral", amounts, scales)
        s_small = hub._compute_composite(small, "core", "neutral", amounts, scales)
        assert s_big > s_small, \
            f"2000 亿应高于 30 亿（scale 维度仍死值: {s_big} vs {s_small}）"

    def test_factor_dominance_kept(self):
        """同规模下 factor_sum=+9 > factor_sum=0，且 factor 项贡献 > 50%。"""
        hub = _hub()
        hi = _item(amount=1e9, scale=2000.0, factor_sum=9.0)
        lo = _item(amount=1e9, scale=2000.0, factor_sum=0.0)
        amounts = [1e9, 1e9]
        scales = [2000.0, 2000.0]
        s_hi = hub._compute_composite(hi, "core", "neutral", amounts, scales)
        s_lo = hub._compute_composite(lo, "core", "neutral", amounts, scales)
        assert s_hi > s_lo
        # factor 项 = w.factor(0.50) × tanh(9/6)=tanh(1.5)
        factor_term = 0.50 * math.tanh(9.0 / 6.0)
        assert factor_term / s_hi > 0.5, f"factor 贡献占比应 >50%（实际 {factor_term/s_hi:.2f}）"

    def test_backward_compat_legacy_path(self):
        """layer_amounts=None → 旧 *1e-9 路径（research 层等行为不变）。"""
        hub = _hub()
        item = _item(amount=4.47e9, scale=1193.85, factor_sum=1.0)
        # 旧路径：liquidity ≈ 4.47e9*1e-9*0.25 ≈ 1.12，scale ≈ 1193.85*1e-9*0.25 ≈ 0
        s = hub._compute_composite(item, "core", "neutral")
        assert s == pytest.approx(0.50 * 1.0 + 0.25 * 4.47e9 * 1e-9 + 0.25 * 1193.85 * 1e-9)

    def test_pct_rank_with_ties(self):
        hub = _hub()
        assert hub._pct_rank(30.0, [10.0, 30.0, 50.0]) == pytest.approx(0.5)  # 中位
        assert hub._pct_rank(50.0, [10.0, 30.0, 50.0]) == pytest.approx((2 + 0.5) / 3)
        assert hub._pct_rank(100.0, [10.0, 30.0, 50.0]) == pytest.approx(1.0)
        assert hub._pct_rank(1.0, []) == 0.0

    def test_opportunistic_keeps_legacy(self):
        """opportunistic 层不启用百分位（保持旧路径 + opp 分量）。"""
        hub = _hub()
        item = _item(amount=1e8, scale=10.0, factor_sum=0.0)
        item["composite_score"] = 0.6
        s = hub._compute_composite(item, "opportunistic", "neutral")
        # 旧路径：0.35(factor 0) + 0.15*1e8*1e-9 + 0.35*0.6（opp 权重随 regime）
        assert s == pytest.approx(0.15 * 1e8 * 1e-9 + 0.35 * 0.6, abs=1e-9)
