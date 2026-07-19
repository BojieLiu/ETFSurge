# Factor Integration Contracts / 因子集成契约

## Overview
FactorRegistry.compute() is already wired into pool_manager.refresh() at
line 123. This document covers the remaining scaffolding-to-real upgrades.

## 1. `_compute_stock_divergence`

### Before
```python
def _compute_stock_divergence(data: dict) -> float:
    return 0.0  # scaffolding
```

### After
Read advance_decline ratio from sentiment_fetcher (now stable via push2).
When divergence is high (many stocks deviating from index), sentiment
dispersion is amplified.

**Input**: `data["advance_decline"]` — float, ratio of advancing/declining stocks
**Output**: normalized float -1.0~1.0 (0 = neutral, >0 = greedy, <0 = panic)

### Data Source
`app.fetchers.sentiment_fetcher.fetch_advance_decline_ratio()` — push2 API
(Stage 2 upgraded, no proxy, 8s timeout)

## 2. Test Plan

| Test | What it verifies |
|---|---|
| test_stock_divergence_computed | Returns non-zero when advance_decline present |
| test_stock_divergence_neutral | Returns ~0 when advance_decline ~1.0 |
| test_stock_divergence_fallback | Returns 0 when no advance_decline data |
