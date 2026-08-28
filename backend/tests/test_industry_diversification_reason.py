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
