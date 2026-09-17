# -*- coding: utf-8 -*-
"""L2 PE-only v1: engine/valuation.py 纯函数契约（TDD 先红）.

契约: api-contracts/analysis/advice-valuation.md §5-§6.
- compute_pe_percentile: 当前值在历史序列中的分位 (0..1),空历史→None.
- classify_valuation: PE-only v1 无 ROE/PB 源时,缺基本面一律待验,
  不硬判错杀/陷阱(防 sess-1ef0 式臆断).
"""
import pytest

from app.engine.valuation import classify_valuation, compute_pe_percentile


def test_percentile_empty_history_is_none():
    assert compute_pe_percentile(14.6, []) is None
    assert compute_pe_percentile(14.6, None) is None


def test_percentile_basic():
    hist = [10.0, 12.0, 14.0, 16.0, 18.0]
    assert compute_pe_percentile(10.0, hist) == pytest.approx(0.0)
    assert compute_pe_percentile(18.0, hist) == pytest.approx(1.0)
    assert compute_pe_percentile(14.0, hist) == pytest.approx(0.5)


def test_percentile_ignores_none():
    assert compute_pe_percentile(14.0, [12.0, None, 16.0]) == pytest.approx(0.5)


def test_classify_no_fundamentals_is_pending():
    # v1 无 ROE/PB 源:即使 PE 分位极低也不判错杀,必须待验
    assert classify_valuation(pe_pct=0.1, pb_pct=None, roe=None) == "待验"
    assert classify_valuation(pe_pct=0.9, pb_pct=None, roe=None) == "待验"
    assert classify_valuation(pe_pct=None, pb_pct=None, roe=None) == "待验"


def test_classify_with_roe():
    # 有 ROE 才允许下结论:低分位+ROE 稳→错杀候选;高分位+ROE 恶化→陷阱候选
    assert classify_valuation(pe_pct=0.2, pb_pct=0.25, roe=0.12) == "错杀候选"
    assert classify_valuation(pe_pct=0.85, pb_pct=0.8, roe=-0.03) == "陷阱候选"
    assert classify_valuation(pe_pct=0.5, pb_pct=0.5, roe=0.08) == "合理"
