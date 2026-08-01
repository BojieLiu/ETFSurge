"""
ICTracker: Information Coefficient tracking for factor evaluation.

Provides Spearman rank IC computation, multi-period IC series, ICIR,
and half-life estimation. Used to validate factor efficacy before
including them in portfolio design weights.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logger = logging.getLogger(__name__)


def build_forward_returns(
    market_data: dict[str, dict[str, Any]],
    symbols: list[str] | None = None,
    window: int = 1,
) -> pd.Series:
    """Build forward returns from market_data close price series.

    Uses the close price history to compute (close[0] - close[window]) / close[window],
    where index 0 is the most recent.

    Args:
        market_data: {symbol: {close: [float, ...]}} with close prices (recent first).
        symbols: Optional subset of symbols to compute (default: all).
        window: Forward return window in periods (1 = next period return).

    Returns:
        pd.Series: {symbol: forward_return} for symbols with sufficient data.
    """
    targets = symbols if symbols is not None else list(market_data.keys())
    returns: dict[str, float] = {}
    for sym in targets:
        data = market_data.get(sym, {})
        close = data.get("close", [])
        if not isinstance(close, (list, tuple)) or len(close) < window + 1:
            continue
        try:
            cur = float(close[0])
            fut = float(close[window])
            if fut != 0:
                returns[sym] = (cur - fut) / fut
        except (TypeError, ValueError, IndexError):
            continue
    return pd.Series(returns)


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

    def compute_periodic_ic(
        self,
        factor_values: dict[str, dict[str, float]],
        market_data: dict[str, dict[str, Any]],
        window: int = 1,
    ) -> dict[str, float]:
        """Compute single-period IC for each factor code across all symbols.

        Args:
            factor_values: {symbol: {factor_code: value}}
            market_data: {symbol: {close: [float, ...]}}
            window: Forward return window.

        Returns:
            {factor_code: ic_value}
        """
        if not factor_values or not market_data:
            return {}

        symbols = list(factor_values.keys())
        forward_rets = build_forward_returns(market_data, symbols, window)
        if len(forward_rets) < 3:
            return {}

        # Group factor values by code
        factor_by_code: dict[str, dict[str, float]] = {}
        # F3-4 步骤D: 零值占比统计（code -> [zero_count, total_count]）
        _stats: dict[str, list[int]] = {}
        for sym, factors in factor_values.items():
            if not factors:
                continue
            for code, val in factors.items():
                st = _stats.setdefault(code, [0, 0])
                st[1] += 1
                if abs(val) < 0.001:
                    st[0] += 1
                    continue
                if code not in factor_by_code:
                    factor_by_code[code] = {}
                factor_by_code[code][sym] = val
        self._zero_ratio = {
            c: (st[0] / st[1]) if st[1] else 0.0
            for c, st in _stats.items()
        }

        # Compute IC per factor code
        ic_results: dict[str, float] = {}
        for code, values in factor_by_code.items():
            fv = pd.Series(values)
            common = fv.index.intersection(forward_rets.index)
            if len(common) < 3:
                ic_results[code] = 0.0
                continue
            ic_results[code] = self.compute_ic(
                fv[common], forward_rets[common]
            )

        return ic_results

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

    async def save_ic_batch_to_db(self, session: AsyncSession, ic_batch: dict[str, float]) -> int:
        """Persist the current IC batch to the database.

        Args:
            session: SQLAlchemy async session
            ic_batch: {factor_code: ic_value} dict from registry._last_ic_batch

        Returns:
            Number of records saved
        """
        from ..models.factor_ic import FactorICRecord  # lazy import to avoid circular dependency

        count = 0
        now = datetime.utcnow()
        for code, ic_val in ic_batch.items():
            if abs(ic_val) < 0.0001:
                continue
            record = FactorICRecord(
                factor_code=code,
                ic_value=round(float(ic_val), 4),
                sample_count=self._get_ic_sample_count(code),
                computed_at=now,
            )
            session.add(record)
            count += 1

        await session.commit()
        return count

    def _get_ic_sample_count(self, factor_code: str) -> int:
        """Count occurrences of *factor_code* in internal records.

        self._records is list[dict], not a dict indexed by factor_code,
        so we must sum matches rather than doing a direct key lookup.
        """
        return sum(
            1 for r in self._records
            if isinstance(r, dict) and r.get("factor_code") == factor_code
        )


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
