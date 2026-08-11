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

    def compute_ic(self, factor_values: pd.Series, forward_returns: pd.Series) -> float | None:
        """Compute single-period Spearman rank IC.

        Args:
            factor_values:   Factor values across assets in period t.
            forward_returns: Forward returns (e.g. t+1) for the same assets.

        Returns:
            Spearman rank correlation coefficient, or None when the IC is
            undefined (insufficient samples / constant input / NaN) —
            U3/N06: None 语义表示"该因子本批不可计算"，调用方跳过而非写 0。
        """
        combined = pd.concat([factor_values, forward_returns], axis=1).dropna()
        if len(combined) < 3:
            return None
        vals = combined.iloc[:, 0]
        rets = combined.iloc[:, 1]
        # U3/N06: 常量输入检测——spearmanr 对常量序列产生 ConstantInputWarning + NaN，
        # 旧代码把 NaN 转 0.0，全 0 批次覆盖 _last_ic_batch → IC 数据永久丢失（Z06/N06）。
        if vals.nunique() == 1 or rets.nunique() == 1:
            return None
        corr, _ = spearmanr(vals, rets)
        if np.isnan(corr):
            return None
        return float(corr)

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
            if ic is not None:  # U3/N06: 跳过不可计算的周期（None）
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
                # round14 P2-Z 修复 3: tracking_error 合法值 0.001~0.02（_compute_tracking_error
                # 注释 0~0.05）——abs<0.001 会把合法跟踪误差全判零（§2.11：有效样本<3 → 永不产 IC）；
                # 按因子区分：tracking_error 仅排除真 0（1e-6），其余因子维持 0.001。
                _zero_tol = 1e-6 if code == "etf.tracking_error" else 0.001
                if abs(val) < _zero_tol:
                    st[0] += 1
                    continue
                if code not in factor_by_code:
                    factor_by_code[code] = {}
                factor_by_code[code][sym] = val
        self._zero_ratio = {
            c: (st[0] / st[1]) if st[1] else 0.0
            for c, st in _stats.items()
        }

        # P2-9 (round9 §6.5.1-D): IC 口径核对（2026-08-07）——Spearman 秩相关横截面 IC
        # （单期全体标的截面相关），forward return window=1，常量输入/样本<3 返回 None
        # （不写 0 防污染批次）——口径本身正确。vol_ratio IC=0.001 属真实弱因子（ETF 同质化
        # + 量比差异小），非方法缺陷；按 P1-3 已标 warn（|IC|<阈值），待样本累积后按 O6
        # 淘汰线决策，不因弱 IC 修改计算方法。

        # Compute IC per factor code
        ic_results: dict[str, float] = {}
        for code, values in factor_by_code.items():
            fv = pd.Series(values)
            common = fv.index.intersection(forward_rets.index)
            if len(common) < 3:
                # U3/N06: 样本不足跳过该因子（不写 0.0——全 0 批次会覆盖有效 IC）
                continue
            ic_val = self.compute_ic(
                fv[common], forward_rets[common]
            )
            if ic_val is None:
                # U3/N06: 常量输入/NaN → 跳过，不污染批次
                continue
            ic_results[code] = ic_val

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
            # U3/N06: 过滤 None / NaN / 0 值（旧逻辑只过滤 0，NaN 会落库）
            if ic_val is None:
                continue
            if isinstance(ic_val, float) and (ic_val != ic_val):  # NaN 自比较
                continue
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


# Global singleton
ic_tracker = ICTracker()
