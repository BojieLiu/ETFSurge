# FactorRegistry — Internal API Contract

> Scope: `factors/factor_registry.py` compute functions refactor — pandas-ta reint
> Status: Active · No public API change

## Public Interface (unchanged)

### `FactorRegistry.compute_batch(symbols, market_data, ...) -> dict[str, dict[str, float]]`

No signature or return type change. All 32 compute functions keep their:
- **Signature**: `_compute_xxx(data: dict[str, Any]) -> float`
- **Return**: single float (default when data insufficient)
- **No I/O**: pure function, no external calls

## Compute Functions Affected (11 functions → pandas-ta)

| Function | pandas-ta Equivalent | Internal Change |
|---|---|---|
| `_compute_sma_5` | `ta.sma(pd.Series(data["close"]), length=5).iloc[-1]` | List→Series→pandas-ta |
| `_compute_sma_10` | `ta.sma(pd.Series(data["close"]), length=10).iloc[-1]` | Same pattern |
| `_compute_sma_20` | `ta.sma(pd.Series(data["close"]), length=20).iloc[-1]` | Same pattern |
| `_compute_sma_60` | `ta.sma(pd.Series(data["close"]), length=60).iloc[-1]` | Same pattern |
| `_compute_rsi_14` | `ta.rsi(pd.Series(data["close"]), length=14).iloc[-1]` | Same pattern |
| `_compute_macd` | `ta.macd(pd.Series(data["close"]))["MACD_12_26_9"].iloc[-1]` | Returns DIF (MACD line = EMA12-EMA26) |
| `_compute_bollinger_bandwidth` | `ta.bbands(pd.Series(data["close"]))["BBB_*"].iloc[-1]` | Uses pre-computed BBB |
| `_compute_atr_14` | `ta.atr(high=pd.Series(data["high"]), low=..., close=..., length=14).iloc[-1]` | Requires H/L/C |
| `_compute_kdj_k` | Shared: `kdj = ta.kdj(...)`, return `kdj["K_*"].iloc[-1]` | Shared cache across K/D/J |
| `_compute_kdj_d` | Same shared kdj result | `kdj["D_*"].iloc[-1]` |
| `_compute_kdj_j` | Same shared kdj result | `kdj["J_*"].iloc[-1]` |

## Compute Functions Unchanged (21 functions)

All remaining functions (ln_mcap, volume_ratio, vwap, amount_stability, panic_greed_diff,
news_heat, news_direction, signal_overall, industry_diversification, change_pct,
return_1m/3m, price, premium_discount, tracking_error, shares_change,
institutional_holdings_change, five_year_plan, strategic_emerging,
dual_circulation, stock_divergence) — **not affected**.

## Empty/Edge Behavior (preserved)

| Function | Current Default | Notes |
|---|---|---|
| sma_5/10/20/60 | 0.0 | When len(close) < window |
| rsi_14 | 50.0 | When len(close) < 15 |
| macd | 0.0 | When len(close) < 26 |
| bollinger_bandwidth | 0.0 | When len(close) < 20 |
| atr_14 | 0.0 | When len(close) < 15 |
| kdj_k/d/j | 50.0 | When len(close) < 9 |

## Verification
- [ ] All 11 functions return same type (float)
- [ ] All 11 functions return same default for empty data
- [ ] All 21 unaffected functions return unchanged values
- [ ] `compute_batch` produces identical-shaped output dict
