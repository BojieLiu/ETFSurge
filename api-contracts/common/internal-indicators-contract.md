# Indicators Module — Internal API Contract

> Scope: `analysis/indicators.py` refactor — pandas-ta replacement
> Status: Active · No external API change

## Public Functions (interface preserved)

### `compute_ma(close: pd.Series, window: int) -> pd.Series`
- **Input**: Close price Series, window in periods
- **Output**: Moving average Series (same length as input, NaN-prefixed)
- **Change**: `close.rolling(window).mean()` → `pandas_ta.sma(close, length=window)`
- **Note**: Values identical for same data. pandas-ta uses same rolling window internally.

### `compute_ema(close: pd.Series, window: int) -> pd.Series`
- **Input**: Close price Series, window in periods
- **Output**: EMA Series (same length, NaN-prefixed)
- **Change**: `close.ewm(span=window, adjust=False).mean()` → `pandas_ta.ema(close, length=window)`
- **Note**: pandas-ta internally uses `ewm(span=window, adjust=True)` by default.

### `compute_macd(close: pd.Series, fast=12, slow=26, signal=9) -> dict`
- **Input**: Close Series, fast/slow/signal periods
- **Output**: `{"dif": float, "dea": float, "macd": float, "histogram": [float]}`
- **Change**: Manual EWM computation → `pandas_ta.macd(close, fast, slow, signal)`
- **Mapping**:
  - `dif` = pandas-ta `MACD_12_26_9` (last value)
  - `dea` = pandas-ta `MACDs_12_26_9` (last value)
  - `macd` = pandas-ta `MACDh_12_26_9` × 2 (last value) — preserves 2× scaling
  - `histogram` = pandas-ta `MACDh_12_26_9` × 2 (last 30 values as list)

### `compute_rsi(close: pd.Series, window=14) -> float`
- **Input**: Close Series, window
- **Output**: Float (50.0 on empty/insufficient data)
- **Change**: Manual RSI → `pandas_ta.rsi(close, length=window).iloc[-1]`

### `compute_kdj(high: pd.Series, low: pd.Series, close: pd.Series, window=9) -> dict`
- **Input**: High/Low/Close Series, KDJ period
- **Output**: `{"k": float, "d": float, "j": float}` (50.0 default for missing)
- **Change**: Manual KDJ → `pandas_ta.kdj(high, low, close)`
- **Mapping**: pandas-ta columns `K_9_3`, `D_9_3`, `J_9_3`

### `compute_bollinger(close: pd.Series, window=20, num_std=2) -> dict`
- **Input**: Close Series, window, std multiplier
- **Output**: `{"ma": float, "upper": float, "lower": float, "bandwidth": float}`
- **Change**: Manual → `pandas_ta.bbands(close, length=window, std=num_std)`
- **Mapping**: 
  - `ma` = `BBM_{window}_{num_std}_{num_std}`
  - `upper` = `BBU_*`
  - `lower` = `BBL_*`
  - `bandwidth` = `BBB_*` — pandas-ta pre-computes this

### `compute_all_indicators(df, factor_scores=None) -> dict`
- **Unchanged**: Interface and logic preserved
- **Benefits from**: Underlying indicator functions now use pandas-ta

### `compute_chart_data(df) -> dict`
- **Unchanged**: Interface preserved
- **Internal MACD/MA/Bollinger**: Updated to use pandas-ta internally

---

## Verification Checklist
- [ ] `compute_rsi` returns same float for same input (within 1% tolerance)
- [ ] `compute_macd` returns same dict keys and compatible values
- [ ] `compute_kdj` returns same dict keys and compatible values
- [ ] `compute_bollinger` returns same dict keys and compatible values
- [ ] `compute_all_indicators` with factor_scores still skips redundant computation
- [ ] `compute_chart_data` produces same chart output format
- [ ] All empty/edge inputs return expected defaults (50.0 for RSI/KDJ, 0 for MACD, zero dicts for bollinger)
