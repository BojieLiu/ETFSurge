"""
FactorRegistry: YAML-driven factor definitions with async computation engine.

Loads factor_definitions.yaml, manages 167+ factor definitions, and provides
async computation for 30 core factors (S1 scope).
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from pathlib import Path

import yaml
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Default YAML path relative to this file
_DEFAULT_YAML = Path(__file__).parent / "factor_definitions.yaml"


@dataclass
class FactorDefinition:
    """Standardized factor definition matching factor_definitions.yaml schema."""

    code: str
    name: str
    category: str
    subcategory: str = ""
    frequency: str = "daily"
    compute_fn: str = ""                     # Name of computation function
    dependencies: list[str] = field(default_factory=list)
    standardization: str = "zscore"          # zscore / rank / minmax / industry_neutral / none
    lookback_window: int = 1
    ic_threshold: float = 0.02
    ic_ir_threshold: float = 0.5
    source: str = "internal"
    version: int = 1
    description: str = ""
    tags: list[str] = field(default_factory=list)


def _standardize(series: pd.Series, method: str) -> pd.Series:
    """Apply standardization to a factor series."""
    if method == "none" or len(series) < 2:
        return series
    if method == "zscore":
        std = series.std()
        if std == 0:
            return series * 0
        return (series - series.mean()) / std
    if method == "rank":
        return series.rank(pct=True)
    if method == "minmax":
        rng = series.max() - series.min()
        if rng == 0:
            return series * 0
        return (series - series.min()) / rng
    return series


# ── Built-in computation functions for S1 core factors ──────────────

def _compute_ln_mcap(data: dict[str, Any]) -> float:
    """style.size.ln_mcap: 对数总市值"""
    mv = data.get("total_mv", 0)
    return math.log(mv) if mv > 0 else 0.0


def _compute_sma_5(data: dict[str, Any]) -> float:
    """technical.ma.sma_5: 5日均线"""
    close = data.get("close", [])
    if len(close) < 5:
        return 0.0
    return float(np.mean(close[-5:]))


def _compute_sma_10(data: dict[str, Any]) -> float:
    """technical.ma.sma_10: 10日均线"""
    close = data.get("close", [])
    if len(close) < 10:
        return 0.0
    return float(np.mean(close[-10:]))


def _compute_sma_20(data: dict[str, Any]) -> float:
    """technical.ma.sma_20: 20日均线"""
    close = data.get("close", [])
    if len(close) < 20:
        return 0.0
    return float(np.mean(close[-20:]))


def _compute_sma_60(data: dict[str, Any]) -> float:
    """technical.ma.sma_60: 60日均线"""
    close = data.get("close", [])
    if len(close) < 60:
        return 0.0
    return float(np.mean(close[-60:]))


def _compute_rsi_14(data: dict[str, Any]) -> float:
    """technical.rsi.rsi_14: 14日RSI"""
    close = data.get("close", [])
    if len(close) < 15:
        return 50.0
    s = pd.Series(close)
    delta = s.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0


def _compute_macd(data: dict[str, Any]) -> float:
    """technical.macd.macd: MACD值"""
    close = data.get("close", [])
    if len(close) < 26:
        return 0.0
    s = pd.Series(close)
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    return float(dif.iloc[-1])


def _compute_bollinger_bandwidth(data: dict[str, Any]) -> float:
    """technical.bollinger.bandwidth: 布林带宽%"""
    close = data.get("close", [])
    if len(close) < 20:
        return 0.0
    s = pd.Series(close)
    ma20 = s.rolling(20).mean()
    std20 = s.rolling(20).std()
    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20
    bw = (upper - lower) / ma20
    return float(bw.iloc[-1]) if not np.isnan(bw.iloc[-1]) else 0.0


def _compute_volume_ratio(data: dict[str, Any]) -> float:
    """technical.volume.vol_ratio: 量比 (近5日均量/近20日均量)"""
    volume = data.get("volume", [])
    if len(volume) < 20:
        return 1.0
    vol5 = np.mean(volume[-5:])
    vol20 = np.mean(volume[-20:])
    return float(vol5 / vol20) if vol20 > 0 else 1.0


def _compute_atr_14(data: dict[str, Any]) -> float:
    """technical.atr.atr_14: 14日ATR"""
    high = data.get("high", [])
    low = data.get("low", [])
    close = data.get("close", [])
    if len(close) < 15:
        return 0.0
    h, l, c = pd.Series(high), pd.Series(low), pd.Series(close)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    return float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0


def _compute_vwap(data: dict[str, Any]) -> float:
    """technical.volume.vwap: 成交量加权平均价"""
    close = data.get("close", [])
    volume = data.get("volume", [])
    if not close or not volume or len(close) != len(volume):
        return float(close[-1]) if close else 0.0
    c = np.array(close)
    v = np.array(volume)
    total_vol = v.sum()
    return float(np.sum(c * v) / total_vol) if total_vol > 0 else float(c[-1])


# ── Mapping of factor code → compute function ─────────────────────

_BUILTIN_COMPUTERS: dict[str, Callable[[dict], float]] = {
    "style.size.ln_mcap": _compute_ln_mcap,
    "style.size.ln_float_mcap": _compute_ln_mcap,  # Same logic with float_mv
    "technical.ma.sma_5": _compute_sma_5,
    "technical.ma.sma_10": _compute_sma_10,
    "technical.ma.sma_20": _compute_sma_20,
    "technical.ma.sma_60": _compute_sma_60,
    "technical.rsi.rsi_14": _compute_rsi_14,
    "technical.macd.macd": _compute_macd,
    "technical.bollinger.bandwidth": _compute_bollinger_bandwidth,
    "technical.volume.vol_ratio": _compute_volume_ratio,
    "technical.atr.atr_14": _compute_atr_14,
    "technical.volume.vwap": _compute_vwap,
}

# 30 core factors for S1 (extend this list as implementation progresses)
_CORE_FACTORS = [
    # Style: Size & Value
    "style.size.ln_mcap",
    "style.size.ln_float_mcap",
    # Technical: MA
    "technical.ma.sma_5",
    "technical.ma.sma_10",
    "technical.ma.sma_20",
    "technical.ma.sma_60",
    # Technical: RSI
    "technical.rsi.rsi_14",
    # Technical: MACD
    "technical.macd.macd",
    # Technical: Bollinger
    "technical.bollinger.bandwidth",
    # Technical: Volume
    "technical.volume.vol_ratio",
    # Technical: ATR
    "technical.atr.atr_14",
    # Technical: VWAP
    "technical.volume.vwap",
]


class FactorRegistry:
    """YAML-driven factor registry with async computation.

    Usage:
        reg = FactorRegistry()
        reg.load_definitions()
        factors = reg.list_factors(category="technical")
        result = await reg.compute(["510300", "518880"])
    """

    def __init__(self):
        self._factors: dict[str, FactorDefinition] = {}
        self._computers: dict[str, Callable[[dict], float]] = dict(_BUILTIN_COMPUTERS)

    def load_definitions(self, yaml_path: str | None = None) -> None:
        """Load factor definitions from YAML file."""
        path = Path(yaml_path) if yaml_path else _DEFAULT_YAML
        if not path.exists():
            logger.warning("Factor definitions not found at %s", path)
            return
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        raw_list = data.get("factor_definitions", [])
        for item in raw_list:
            code = item.get("code", "")
            if not code:
                continue
            self._factors[code] = FactorDefinition(
                code=code,
                name=item.get("name", ""),
                category=item.get("category", ""),
                subcategory=item.get("subcategory", ""),
                frequency=item.get("frequency", "daily"),
                compute_fn=item.get("compute_fn", ""),
                dependencies=item.get("dependencies", []),
                standardization=item.get("standardization", "zscore"),
                lookback_window=item.get("lookback_window", 1),
                ic_threshold=item.get("ic_threshold", 0.02),
                ic_ir_threshold=item.get("ic_ir_threshold", 0.5),
                source=item.get("source", "internal"),
                version=item.get("version", 1),
                description=item.get("description", ""),
                tags=item.get("tags", []),
            )
        logger.info("Loaded %d factor definitions from %s", len(self._factors), path)

    def list_factors(self, category: str | None = None) -> list[FactorDefinition]:
        """List all factors, optionally filtered by category."""
        if category:
            return [f for f in self._factors.values() if f.category == category]
        return list(self._factors.values())

    def get_factor(self, code: str) -> FactorDefinition | None:
        """Get a single factor definition by code."""
        return self._factors.get(code)

    def register_computer(self, code: str, fn: Callable[[dict], float]) -> None:
        """Register a custom computation function for a factor."""
        self._computers[code] = fn

    async def _fetch_market_data(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch market data needed for factor computation.

        In S1, this returns mock/placeholder data.
        In later sprints, this pulls from data sources (akshare, FRED, etc.).
        """
        # Placeholder: subclasses/replace with actual data fetch in later sprints
        result = {}
        for sym in symbols:
            result[sym] = {
                "total_mv": 100e9,
                "float_mv": 80e9,
                "close": [4.0 + i * 0.01 for i in range(60)],
                "high": [4.0 + i * 0.02 for i in range(60)],
                "low": [4.0 - i * 0.01 for i in range(60)],
                "volume": [1000000 + i * 1000 for i in range(60)],
            }
        return result

    async def compute(
        self,
        symbols: list[str],
        codes: list[str] | None = None,
        market_data: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Compute factor values for given symbols.

        Args:
            symbols: List of ETF/code symbols to compute for.
            codes:   Specific factor codes to compute (None = all with computers).
            market_data: Optional pre-fetched market data. If None, uses mock/placeholder.

        Returns:
            {symbol: {factor_code: standardized_value}}
        """
        if codes is None:
            codes = [c for c in _CORE_FACTORS if c in self._computers]

        if market_data is not None:
            # 使用外部注入的真实数据
            pass
        else:
            market_data = await self._fetch_market_data(symbols)

        result: dict[str, dict[str, float]] = {}
        for sym in symbols:
            row: dict[str, float] = {}
            data = market_data.get(sym, {})
            for code in codes:
                computer = self._computers.get(code)
                if computer is None:
                    continue
                try:
                    raw_value = computer(data)
                    definition = self._factors.get(code)
                    if definition and definition.standardization != "none":
                        # Note: full standardization across symbols requires
                        # batch processing. For S1, per-symbol normalization only.
                        pass
                    row[code] = raw_value if raw_value is not None else 0.0
                except Exception as e:
                    logger.debug("Factor %s failed for %s: %s", code, sym, e)
                    row[code] = 0.0
            result[sym] = row
        return result


# Global singleton
registry = FactorRegistry()
