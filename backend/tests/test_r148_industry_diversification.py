"""R148: industry_diversification 公式改 1.0/(1+len(concepts)) 单调递减测试。

- 旧公式 1.0/max(n,1) 在 n=1,2 时返 1.0/0.5，候选池 1/1/2/2 时 O20 判 constant
- 新公式 1.0/(1+n) 给 n=1,2,3 时返 0.5/0.333/0.25，平滑单调递减
"""
from __future__ import annotations

import pytest

from app.factors.factor_registry import _compute_industry_diversification


class TestIndustryDiversificationR148:
    def test_n_equals_zero_returns_zero(self):
        """n=0 concepts 返 0.0（兼容 round7 O20 P20-③ 契约：无信息中性而非"极不分散"）。
        避免 N 个空 concepts 标的全部返 1.0 仍被 O20 判 constant。"""
        assert _compute_industry_diversification({"concepts": []}) == 0.0
        # None 也走 0.0
        assert _compute_industry_diversification({"concepts": None}) == 0.0
        # 完全没 concepts 键
        assert _compute_industry_diversification({}) == 0.0

    def test_n_equals_one_returns_0_5(self):
        """n=1 概念返 0.5（旧公式返 1.0，新公式 0.5）"""
        v = _compute_industry_diversification({"concepts": ["沪深300"]})
        assert abs(v - 0.5) < 0.0001

    def test_n_equals_two_returns_0_333(self):
        """n=2 概念返 0.333（旧公式 0.5，新公式 0.333）"""
        v = _compute_industry_diversification({"concepts": ["黄金", "贵金属"]})
        assert abs(v - 1/3) < 0.0001

    def test_n_equals_three_returns_0_25(self):
        """n=3 概念返 0.25"""
        v = _compute_industry_diversification({"concepts": ["a", "b", "c"]})
        assert abs(v - 0.25) < 0.0001

    def test_monotonic_decreasing(self):
        """新公式 1.0/(1+n) 在 n>=1 严格单调递减：n 越大值越小。
        n=0 特殊：返 0.0（无信息中性），不参与单调序列。"""
        vals_nonzero = [
            _compute_industry_diversification({"concepts": ["a"]}),
            _compute_industry_diversification({"concepts": ["a", "b"]}),
            _compute_industry_diversification({"concepts": ["a", "b", "c"]}),
        ]
        for i in range(len(vals_nonzero) - 1):
            assert vals_nonzero[i] > vals_nonzero[i+1], f"n>=1 非单调: {vals_nonzero}"
        # n=0 边界
        n0 = _compute_industry_diversification({"concepts": []})
        assert n0 == 0.0, "n=0 应返 0.0（无信息中性）"

    def test_industry_holdings_still_hhi(self):
        """有 industry_holdings 时仍走 HHI 路径（未改）"""
        # 100% 集中在一个行业 → HHI = 1.0
        v = _compute_industry_diversification({"industry_holdings": {"金融": 1.0}})
        assert abs(v - 1.0) < 0.0001
        # 50/50 集中 → HHI = 0.5
        v = _compute_industry_diversification({"industry_holdings": {"金融": 0.5, "科技": 0.5}})
        assert abs(v - 0.5) < 0.0001

    def test_pool_distribution_has_better_spread(self):
        """真实池 5 标的 concepts 分布 [1, 2, 2, 1, 0]，新公式有 3 个不同值
        （旧公式只 2 个不同值：1.0 与 0.5——n=1,2 都被映射到 1.0/0.5 两个值）。
        新公式 1.0/(1+n) 区分度提升：n=0→0.0, n=1→0.5, n=2→0.333。
        n=0 走 0.0 兼容 round7 O20 契约（避免 N 个空 concepts 标的全部返 1.0）。
        """
        cases = [
            (["沪深300"], 0.5),  # 510300
            (["黄金", "贵金属"], 1/3),  # 518880
            (["国债", "利率债"], 1/3),  # 511090
            (["创业板"], 0.5),  # 159915
            ([], 0.0),  # 512480 (n=0 → 0.0)
        ]
        results = [_compute_industry_diversification({"concepts": c}) for c, _ in cases]
        unique_vals = set(round(v, 4) for v in results)
        # 新公式 3 个不同值（0.0, 0.333, 0.5），旧公式 2 个（0.5, 1.0）
        assert len(unique_vals) == 3, f"5 标的应有 3 个不同截面值，实际 {unique_vals}"
        # 不再是 O20 截面常量（2 值以下才算 constant）
