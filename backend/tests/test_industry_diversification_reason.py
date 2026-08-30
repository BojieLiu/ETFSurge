"""
O20 (docs/archived/round7-rediagnosis.md §7 P20-③) + R148 (round38 §11.3): industry_diversification 数据语义。

P20-③ 根因: etf.industry_diversification 的 concepts fallback（1/n）上游 concepts 为空 →
恒 0.0 常量 → IC 因零方差无法计算 → ic_val=None；且该因子不在 ET_SPECIFIC_GAP_CODES →
reason 误报「IC 未累积（样本 <3）」而非「数据源未接入」。

R148 (round38 §11.3): 旧公式 1/max(n,1) 改 1/(1+n) 单调递减归一——n=1,2 时二元分布
（1.0 vs 0.5）候选池 1/1/2/2 时 O20 判 constant。新公式 n=1→0.5, n=2→0.333, n=3→0.25
平滑单调，5 标的池 3 个不同截面值不再判 constant。n=0 保留 0.0 兼容 O20 契约。

修复:
1. concepts 空 → 因子常量 0.0 → /factors/active reason 独立标注「截面无差异（常量输出）」
2. concepts 非空 → 1/(1+n) fallback 生效（industry_diversification 有值）
3. ET_SPECIFIC_GAP_CODES 含 industry_diversification → reason 走「数据源未接入（缺 concepts）」
"""

from app.factors import factor_registry as fr
from app.factors.factor_registry import _compute_industry_diversification


class TestIndustryDiversificationCompute:
    def test_concepts_empty_returns_zero(self):
        """concepts 空 → 常量 0.0（无行业数据也无概念标签）。"""
        assert _compute_industry_diversification({}) == 0.0
        assert _compute_industry_diversification({"concepts": []}) == 0.0
        assert _compute_industry_diversification({"concepts": None}) == 0.0

    def test_concepts_non_empty_uses_1n(self):
        """concepts 非空 → 1/(1+n) fallback 生效（R148: 旧 1/n 改 1/(1+n)，单调递减归一）。
        区分度更平滑：n=2 → 0.333（旧 1/2=0.5），n=4 → 0.2（旧 1/4=0.25）。
        """
        assert _compute_industry_diversification({"concepts": ["半导体", "芯片"]}) == round(1/3, 4)
        assert _compute_industry_diversification({"concepts": ["A", "B", "C", "D"]}) == 0.2
        # industry_holdings 优先（HHI）
        val = _compute_industry_diversification({"industry_holdings": {"银行": 0.6, "券商": 0.4}})
        assert abs(val - (0.36 + 0.16)) < 1e-6


class TestIndustryDiversificationReason:
    def test_gap_codes_include_industry_diversification(self):
        """ET_SPECIFIC_GAP_CODES 含 industry_diversification → reason 走「数据源未接入」。"""
        assert "etf.industry_diversification" in fr.ET_SPECIFIC_GAP_CODES
        assert fr.ET_SPECIFIC_GAP_CODES["etf.industry_diversification"] == "concepts"

    def test_constant_factor_reason_label(self):
        """常量因子（截面 std=0）给独立标注「截面无差异（常量输出）」。"""
        registry = fr.registry
        assert hasattr(registry, "_constant_factor_codes"), "registry 应记录常量因子 code"
        # 模拟常量因子记录
        registry._constant_factor_codes.add("etf.industry_diversification")
        try:
            from app.routers.factors import _status_of
            status, reason = _status_of("etf.industry_diversification", samples=0, t_stat=None, ir=None, ic_val=None)
            assert status == "no_data"
            assert "截面无差异" in reason, f"常量因子 reason 应独立标注: {reason}"
        finally:
            registry._constant_factor_codes.discard("etf.industry_diversification")

    def test_missing_concepts_gap_reason(self):
        """缺 concepts 时 gap 记录 → reason「数据源未接入（缺 concepts）」。"""
        registry = fr.registry
        registry._data_source_gaps["etf.industry_diversification"] = ["510300", "560600"]
        try:
            from app.routers.factors import _status_of
            status, reason = _status_of("etf.industry_diversification", samples=0, t_stat=None, ir=None, ic_val=None)
            assert status == "no_data"
            assert "数据源未接入" in reason and "concepts" in reason, f"reason 应含缺 concepts: {reason}"
        finally:
            registry._data_source_gaps.pop("etf.industry_diversification", None)


# ── round39 §10.7 (round42 实施): 合并 R148 ─────────────────────
# R148 (round38 §11.3): 1.0/(1+n) 单调递减归一详细测试——补充本文件已有
# TestIndustryDiversificationCompute 的少量用例 (n=0/2/混合 holdings).
# 下方 5 用例覆盖 R148 独有边界: n=1/n=3 单点、严格单调、HHI 单/双行业、5 标的池 3 值.
class TestIndustryDiversificationR148:
    def test_n_equals_one_returns_0_5(self):
        """n=1 概念返 0.5（旧公式返 1.0，新公式 0.5）"""
        v = _compute_industry_diversification({"concepts": ["沪深300"]})
        assert abs(v - 0.5) < 0.0001

    def test_n_equals_three_returns_0_25(self):
        """n=3 概念返 0.25"""
        v = _compute_industry_diversification({"concepts": ["a", "b", "c"]})
        assert abs(v - 0.25) < 0.0001

    def test_monotonic_decreasing(self):
        """新公式 1.0/(1+n) 在 n>=1 严格单调递减：n 越大值越小。
        n=0 特殊：返 0.0（无信息中性），不参与单调序列。
        """
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
