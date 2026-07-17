"""
MarketDataAdapter: converts fetcher output (list[dict]) to pandas DataFrame
for use by VectorBT backtesting and ICTracker IC computation.

Standardizes column names to open/high/low/close/volume format and
supports MultiIndex (symbol, date) for multi-asset backtesting.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Column name aliases → standard names
_COLUMN_ALIASES = {
    "open": ["开盘", "open", "Open", "OPEN"],
    "high": ["最高", "high", "High", "HIGH"],
    "low": ["最低", "low", "Low", "LOW"],
    "close": ["收盘", "close", "Close", "CLOSE"],
    "volume": ["成交量", "volume", "Volume", "VOLUME", "成交额"],
    "date": ["日期", "date", "Date", "DATE", "datetime", "Datetime", "timestamp"],
}


def _resolve_col(df: pd.DataFrame, target: str) -> str | None:
    """Find the actual column name in df for a target (open/high/low/...)."""
    aliases = _COLUMN_ALIASES.get(target, [target])
    for alias in aliases:
        if alias in df.columns:
            return alias
    return None


def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename fetcher column names to standard names."""
    rename_map = {}
    for standard, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in df.columns:
                rename_map[alias] = standard
                break
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


class MarketDataAdapter:
    """市场数据适配器。"""

    def to_dataframe(self, data: list[dict[str, Any]]) -> pd.DataFrame | None:
        """Convert list[dict] → DataFrame with standardized column names.

        Args:
            data: List of OHLCV dicts from fetchers.

        Returns:
            DataFrame or None if empty.
        """
        if not data:
            return None
        df = pd.DataFrame(data)
        df = _rename_columns(df)
        # Ensure date column is datetime
        date_col = _resolve_col(df, "date")
        if date_col and date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.sort_values(date_col).reset_index(drop=True)
        return df

    def to_multi_index(
        self,
        symbol_data: dict[str, list[dict[str, Any]]],
    ) -> pd.DataFrame | None:
        """Merge multiple symbols into a MultiIndex DataFrame.

        Args:
            symbol_data: {symbol: [OHLCV dicts, ...]}

        Returns:
            DataFrame with MultiIndex (symbol, date) or None if empty.
        """
        if not symbol_data:
            return None
        frames = []
        for symbol, records in symbol_data.items():
            df = self.to_dataframe(records)
            if df is not None:
                date_col = _resolve_col(df, "date") or df.columns[0]
                df["symbol"] = symbol
                frames.append(df)
        if not frames:
            return None
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.set_index(["symbol", date_col]).sort_index()
        return combined


# Global singleton
adapter = MarketDataAdapter()
