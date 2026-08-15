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
def _series(base, drift=0.001, n=80):
    """构造近 n 根单调上涨序列（同 drift → r≈1.0；反向 drift → r≈-1.0）。"""
    out = []
    v = base
    for i in range(n):
        v += drift
        out.append(v)
    return out
def _wave(base, amp, phase, n=80):
    """正弦波动序列（相位差 π → r≈-1.0；不同频率 → r≈0）。"""
    import math
    return [base + amp * math.sin(i / 5.0 + phase) for i in range(n)]
class TestCorrelationEngine:
    """round19 P1-①: correlation.py 纯函数。"""

    def test_matrix_perfectly_correlated(self):
        closes = {
            "510300": _series(4.0),
            "159338": _series(4.1),  # 同向同漂移 → r≈1.0
        }
        m = correlation_matrix(closes, window=60)
        r = m[("159338", "510300")]
        assert r is not None and abs(r - 1.0) < 0.02, f"同向序列 r 应≈1.0，实得 {r}"

    def test_matrix_negative_correlation(self):
        closes = {
            "A": _wave(4.0, 0.1, 0.0),
            "B": _wave(4.0, 0.1, 3.14159),  # 反相 → r≈-1.0
        }
        m = correlation_matrix(closes, window=60)
        r = m[("A", "B")]
        assert r is not None and abs(r + 1.0) < 0.05, f"反向序列 r 应≈-1.0，实得 {r}"

    def test_window_insufficient_returns_none(self):
        """历史 <30 根 → r=None（数据不足诚实标注，负向：0 冒充 → FAIL）。"""
        closes = {"A": _series(4.0, n=20), "B": _series(5.0, n=80)}
        m = correlation_matrix(closes, window=60)
        assert m[("A", "B")] is None, "数据不足标的 r 应为 None 而非 0"

    def test_high_correlation_pairs_threshold(self):
        closes = {"A": _series(4.0), "B": _series(4.1), "C": _series(50.0, drift=-0.01)}
        m = correlation_matrix(closes, window=60)
        pairs = high_correlation_pairs(m, threshold=0.8)
        assert len(pairs) >= 1
        assert pairs[0][0] > 0.8

    def test_avg_correlation(self):
        closes = {"A": _series(4.0), "B": _series(4.1), "C": _series(50.0, drift=-0.01)}
        m = correlation_matrix(closes, window=60)
        avg = avg_correlation(m, ["A", "B", "C"])
        assert avg is not None and -1 <= avg <= 1

    def test_median_correlation_for(self):
        closes = {"A": _series(4.0), "B": _series(4.1), "C": _series(50.0, drift=-0.01)}
        m = correlation_matrix(closes, window=60)
        med = median_correlation_for(m, "A", ["B", "C"])
        assert med is not None
class TestKeywordGap:
    """round19 P1-②: 裸 A500/A50 关键词补漏（563360 漏判场景）。"""

    def test_bare_a500_detected_as_large_cap(self):
        c = {"name": "A500ETF华泰柏瑞", "tracked_index": ""}
        assert _is_large_cap_wide_basis(c) is True, "裸 A500 应判大盘宽基（旧实现漏判）"
