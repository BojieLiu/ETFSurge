"""
O20 (docs/archived/round7-rediagnosis.md §7 P20-③): industry_diversification 数据语义 + no_data reason 修正。

P20-③ 根因: etf.industry_diversification 的 concepts fallback（1/n）上游 concepts 为空 →
恒 0.0 常量 → IC 因零方差无法计算 → ic_val=None；且该因子不在 ET_SPECIFIC_GAP_CODES →
reason 误报「IC 未累积（样本 <3）」而非「数据源未接入」。

修复:
1. concepts 空 → 因子常量 0.0 → /factors/active reason 独立标注「截面无差异（常量输出）」
2. concepts 非空 → 1/n fallback 生效（industry_diversification 有值）
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
        """concepts 非空 → 1/n fallback 生效（有区分度，非恒 0）。"""
        assert _compute_industry_diversification({"concepts": ["半导体", "芯片"]}) == 0.5
        assert _compute_industry_diversification({"concepts": ["A", "B", "C", "D"]}) == 0.25
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
            status, reason = _status_of("etf.industry_diversification", None, 0.02)
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
            status, reason = _status_of("etf.industry_diversification", None, 0.02)
            assert status == "no_data"
            assert "数据源未接入" in reason and "concepts" in reason, f"reason 应含缺 concepts: {reason}"
        finally:
            registry._data_source_gaps.pop("etf.industry_diversification", None)
