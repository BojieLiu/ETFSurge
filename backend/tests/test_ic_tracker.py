"""IC 跟踪系统测试 — Phase 3

P3-1: compute_ic() Spearman rank correlation
P3-2: compute_ic_series() on multiple periods
P3-3: compute_icir() stable/unstable factor detection
"""

import pytest
import pandas as pd
import numpy as np


# --- P3-1: compute_ic ---

def test_p3_compute_ic():
    """compute_ic returns Spearman rank correlation between factor and returns."""
    from app.factors.ic_tracker import ICTracker

    tracker = ICTracker()

    # Positive correlation
    factor = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    returns = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
    ic = tracker.compute_ic(factor, returns)
    assert abs(ic - 1.0) < 0.01, f"Perfect positive IC should be ~1.0, got {ic}"

    # Negative correlation
    ic_neg = tracker.compute_ic(factor, -returns)
    assert abs(ic_neg - (-1.0)) < 0.01, f"Perfect negative IC should be ~-1.0, got {ic_neg}"

    # Zero correlation
    ic_zero = tracker.compute_ic(factor, pd.Series([0.5, 0.5, 0.5, 0.5, 0.5]))
    assert abs(ic_zero) < 0.01, f"No correlation IC should be ~0, got {ic_zero}"

    # Handles NaN
    factor_nan = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0])
    returns_nan = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
    ic_nan = tracker.compute_ic(factor_nan, returns_nan)
    assert not np.isnan(ic_nan), "IC should handle NaN gracefully"


# --- P3-2: compute_ic_series ---

def test_p3_compute_ic_series():
    """compute_ic_series returns time series of IC values."""
    from app.factors.ic_tracker import ICTracker

    tracker = ICTracker()

    dates = pd.date_range("2026-01-01", periods=5, freq="ME")
    factors = pd.DataFrame({
        "A": [1.0, 2.0, 3.0, 4.0, 5.0],
        "B": [5.0, 4.0, 3.0, 2.0, 1.0],
    }, index=dates)
    returns = pd.DataFrame({
        "A": [0.01, 0.02, 0.03, 0.04, 0.05],
        "B": [0.05, 0.04, 0.03, 0.02, 0.01],
    }, index=dates)

    ic_series = tracker.compute_ic_series(factors, returns)
    assert len(ic_series) == 5, f"Expected 5 periods, got {len(ic_series)}"
    assert not ic_series.isna().all(), "IC series should have valid values"
    # A has +1 IC, B has -1 IC, overall should be close to 0 (mixed)
    assert abs(ic_series.mean()) < 0.5, (
        f"Mixed IC series mean should be ~0, got {ic_series.mean():.3f}"
    )


# --- P3-3: compute_icir ---

def test_p3_compute_icir():
    """compute_icir distinguishes stable from unstable factors."""
    from app.factors.ic_tracker import ICTracker

    tracker = ICTracker()

    # Stable IC (low std -> high ICIR)
    stable_ic = pd.Series([0.05, 0.06, 0.04, 0.05, 0.07, 0.06])
    stable_icir = tracker.compute_icir(stable_ic)
    assert stable_icir > 5.0, f"Stable factor ICIR should be high, got {stable_icir:.2f}"

    # Unstable IC (high std -> low ICIR)
    unstable_ic = pd.Series([0.8, -0.5, 0.3, -0.6, 0.7, -0.4])
    unstable_icir = tracker.compute_icir(unstable_ic)
    assert abs(unstable_icir) < 2.0, (
        f"Unstable factor ICIR should be low, got {unstable_icir:.2f}"
    )

    # Single value -> returns 0
    single_ic = pd.Series([0.05])
    single_icir = tracker.compute_icir(single_ic)
    assert single_icir == 0.0, f"Single-value ICIR should be 0, got {single_icir}"
