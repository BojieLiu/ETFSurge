from __future__ import annotations
"""Folded business tests (from early-round audit)."""

# folded-from audit: docs/test-redundancy-audit-and-plan.md


# ===== folded from test_round19_p1.py =====
import pytest
from app.engine.correlation import (
    correlation_matrix, high_correlation_pairs, avg_correlation,
    median_correlation_for,
)
from app.engine.rationale import build_rationale
from app.engine.allocation_engine import (
    _dedup_same_index, _is_large_cap_wide_basis, MANDATORY_CODES,
)
class TestRationaleCorrelationGuard:
    """round19 P1-③: rationale「低相关性」措辞条件化。"""

    def _rationale(self, correlation_median):
        return build_rationale(
            code="513500",
            layer="defense",
            strategy="defensive",
            meta={"name": "标普500ETF", "tracked_index": "标普500"},
            factor_scores={"momentum": 0.3},
            correlation_median=correlation_median,
        )

    def test_none_median_no_low_correlation_claim(self):
        """correlation_median=None（矩阵不可用）→ 不含「低相关」字样（负向：None 时
        出现「低相关」→ FAIL——杜绝无数据冒充低相关）。"""
        r = self._rationale(None)
        assert "低相关" not in r, f"矩阵不可用不应声称低相关: {r}"
        assert "防御" in r or "避险" in r or "下行" in r, "应回退中性防御文案"

    def test_high_median_no_low_correlation_claim(self):
        r = self._rationale(0.6)
        assert "低相关" not in r

    def test_low_median_allows_low_correlation(self):
        """correlation_median=0.1（<0.3）→ 防御池保留低相关句（可被抽样命中）。"""
        from app.engine.rationale import _layer_phrase, _DEFENSE_PHRASES
        # 防御池本身含低相关句
        assert any("低相关" in fn("X") for fn in _DEFENSE_PHRASES)
        # median=0.1 时不过滤 → 多 sym 抽样至少 1 条含「低相关性/低相关」
        hit = any(
            "低相关" in _layer_phrase("defense", "标普500ETF", sym, "defensive", 0.1)
            for sym in ["513500", "513300", "518880", "511090", "159920", "513100", "513050", "159941", "513080", "513180"]
        )
        assert hit, "真实低相关（0.1）时防御池应保留低相关句"

    def test_high_median_filters_all_samples(self):
        """median=0.6（≥0.3）→ 多 sym 抽样均不含低相关句。"""
        from app.engine.rationale import _layer_phrase
        for sym in ["513500", "513300", "518880", "511090"]:
            r = _layer_phrase("defense", "标普500ETF", sym, "defensive", 0.6)
            assert "低相关" not in r, f"median=0.6 不应出现低相关措辞: {r}"


# ===== folded from test_round20_engine_fixes.py =====
from app.engine.allocation_engine import (
    allocate,
    enforce_max_correlation,
    check_structure_reasonableness,
)
from app.analysis.signal import generate_signal
class TestP1_2DeterministicLowCorrPhrase:
    def test_low_corr_median_yields_low_corr_phrase(self):
        """P1-2: correlation_median=0.2（<0.3）→ rationale 必含「低相关」。"""
        r = build_rationale(
            code="511090",
            layer="defense",
            strategy="defensive",
            meta={"name": "30年国债ETF", "tracked_index": "国债"},
            factor_scores={},
            regime="range_bound",
            industry="国债",
            correlation_median=0.2,
        )
        assert "低相关" in r, f"correlation_median=0.2 应命中低相关措辞，实际: {r}"

    def test_high_corr_median_no_low_corr_phrase(self):
        """median=0.7（>=0.3）→ 不得出现「低相关」措辞。"""
        r = build_rationale(
            code="510300",
            layer="core",
            strategy="balanced",
            meta={"name": "沪深300ETF", "tracked_index": "沪深300"},
            factor_scores={},
            regime="range_bound",
            industry="宽基指数",
            correlation_median=0.7,
        )
        assert "低相关" not in r, f"median=0.7 不应出现低相关措辞，实际: {r}"
