"""
ICTracker: Information Coefficient tracking for factor evaluation.

Provides Spearman rank IC computation, multi-period IC series, ICIR,
and half-life estimation. Used to validate factor efficacy before
including them in portfolio design weights.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

logger = logging.getLogger(__name__)


class ICTracker:
    """Information Coefficient tracker for factor evaluation.

    IC = Spearman rank correlation between factor values and forward returns.
    ICIR = mean(IC) / std(IC) — measures consistency.
    """

    def __init__(self):
        self._records: list[dict[str, Any]] = []

    def compute_ic(self, factor_values: pd.Series, forward_returns: pd.Series) -> float:
        """Compute single-period Spearman rank IC.

        Args:
            factor_values:   Factor values across assets in period t.
            forward_returns: Forward returns (e.g. t+1) for the same assets.

        Returns:
            Spearman rank correlation coefficient.
        """
        combined = pd.concat([factor_values, forward_returns], axis=1).dropna()
        if len(combined) < 3:
            return 0.0
        vals = combined.iloc[:, 0]
        rets = combined.iloc[:, 1]
        corr, _ = spearmanr(vals, rets)
        return float(corr) if not np.isnan(corr) else 0.0

    def compute_ic_series(
        self,
        factor_values: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> pd.Series:
        """Compute IC series across multiple time periods.

        Args:
            factor_values:   DataFrame(T, N) — factor values at each period.
            forward_returns: DataFrame(T, N) — forward returns for each period.

        Returns:
            Series(T) of IC values per period.
        """
        ic_values = []
        for idx in factor_values.index:
            if idx not in forward_returns.index:
                continue
            fv = factor_values.loc[idx]
            fr = forward_returns.loc[idx]
            ic = self.compute_ic(fv, fr)
            ic_values.append(ic)
        return pd.Series(ic_values, index=factor_values.index[:len(ic_values)])

    def record(self, symbol: str, factor_code: str, value: float) -> None:
        """Record a factor value for IC tracking.

        Args:
            symbol: Asset symbol/ticker.
            factor_code: Factor identifier.
            value: Computed factor value.
        """
        self._records.append({
            "symbol": symbol,
            "factor_code": factor_code,
            "value": value,
            "timestamp": pd.Timestamp.now(),
        })

    def compute_icir(self, ic_series: pd.Series) -> float:
        """Compute ICIR = mean(IC) / std(IC).

        Higher values indicate more consistent factor performance.
        """
        if len(ic_series) < 2:
            return 0.0
        std = ic_series.std()
        if std == 0:
            return float('inf')
        return float(ic_series.mean() / std)


def compute_ic_series_fast(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> pd.Series:
    """Vectorized IC series computation (faster than loop).

    Computes cross-sectional Spearman IC for each time period using
    rank correlation across assets.
    """
    periods = factor_values.index.intersection(forward_returns.index)
    if len(periods) < 2:
        return pd.Series(dtype=float)

    ic_list = []
    for t in periods:
        fv = factor_values.loc[t]
        fr = forward_returns.loc[t]
        mask = fv.notna() & fr.notna()
        if mask.sum() < 3:
            ic_list.append(0.0)
            continue
        corr, _ = spearmanr(fv[mask], fr[mask])
        ic_list.append(float(corr) if not np.isnan(corr) else 0.0)

    return pd.Series(ic_list, index=periods)


# Global singleton
ic_tracker = ICTracker()
