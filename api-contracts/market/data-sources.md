# Data Source Fetcher Contracts / 数据源接入契约

## 1. Twelve Data Fetcher / 十二数据接入

### Overview
Free-tier (800 calls/day) US/global stocks realtime + daily K-line + commodity data.
API: `https://api.twelvedata.com` — no proxy needed in China.

### Module: `backend/app/fetchers/twelvedata_fetcher.py`

### Exported Functions

#### `fetch_realtime(symbol: str) -> dict | None`
```
Input:  symbol — ticker (SPY, AAPL, GOLD, CL)
Output: {
  "symbol": "SPY",
  "price": 743.29,
  "change_pct": -0.99,
  "change_amount": -7.43,
  "volume": 62569200,
  "high": 747.29,
  "low": 740.8,
  "open": 742.08,
  "previous_close": 750.72
}
On error/timeout: return None
```

#### `fetch_history(symbol: str, days: int = 60) -> list[dict] | None`
```
Input:  symbol, days (max 5000 free)
Output: [{"date": "2026-07-17", "open": 742.08, "high": 747.29, "low": 740.8, "close": 743.29, "volume": 62569200}]
On error/timeout: return None
```

---

## 2. Finnhub Fetcher / Finnhub 数据接入

### Overview
Free tier (60 calls/min) US/HK/global stocks realtime + daily K-line.
API: `https://finnhub.io/api/v1` — no proxy needed.

### Module: `backend/app/fetchers/finnhub_fetcher.py`

### Exported Functions

#### `fetch_realtime(symbol: str) -> dict | None`
```
Input:  symbol
Output: {
  "symbol": "SPY",
  "price": 743.29,
  "change_pct": -0.99,
  "change_amount": -7.43,
  "high": 747.29,
  "low": 740.8,
  "open": 742.08,
  "previous_close": 750.72,
  "volume": 62650961
}
On error/timeout: return None
```

#### `fetch_candles(symbol: str, resolution: str = "D") -> list[dict] | None`
```
Input:  symbol, resolution ("D", "W", "M", "15", "30", "60")
Output: [{"date": "2026-07-17", "open": 742.08, "high": 747.29, "low": 740.8, "close": 743.29, "volume": 62650961}]
On error/timeout: return None
```

---

## 3. Alpha Vantage Fetcher / Alpha Vantage 接入

### Overview
Free tier (25 calls/day, 5 calls/min) US/global stocks + commodities + forex + indices.
API: `https://www.alphavantage.co/query` — no proxy needed.

### Module: `backend/app/fetchers/alphavantage_fetcher.py`

### Exported Functions

#### `fetch_realtime(symbol: str) -> dict | None`
```
Input:  symbol
Output: { "symbol":"SPY", "price":743.29, "change_pct":-0.99, "change_amount":-7.43, "volume":62650961, "latest_trading_day":"2026-07-17", "previous_close":750.72 }
On error/timeout: return None
```

#### `fetch_daily(symbol: str, outputsize: str = "compact") -> list[dict] | None`
```
Input:  symbol, outputsize ("compact"=100 days, "full"=20 years)
Output: [{"date":"2026-07-17","open":742.08,"high":747.29,"low":740.8,"close":743.29,"volume":62650961}]
On error/timeout: return None
```

---

## 4. SourceRegistry Routing / 熔断路由

### Integration Point: `backend/app/services/market_service.py`

```python
# Current _route_us() will be extended:
def _route_us(symbol: str) -> dict | None:
    return registry.route([
        ("twelvedata", _twelvedata),    # NEW — 800 calls/day
        ("finnhub", _finnhub),           # NEW — 60 calls/min
        ("alphav", _alphav),             # NEW — 25 calls/day
        ("yfinance", _yf),               # existing fallback
    ])

# New _route_hk() for HK stocks:
def _route_hk(symbol: str) -> dict | None:
    return registry.route([
        ("finnhub", _finnhub_hk),        # NEW
        ("alphav", _alphav_hk),           # NEW
        ("akshare", _ak_hk),              # existing (wrapped)
    ])
```

---

## Frontend-Backend Checklist

- [x] Twelve Data API key verified (tested SPY, GOLD, CL, AAPL)
- [x] Finnhub API key verified (tested SPY quote)
- [x] Alpha Vantage API key verified (tested GLOBAL_QUOTE, TIME_SERIES_DAILY)
- [ ] Test Twelve Data fetcher module
- [ ] Test Finnhub fetcher module
- [ ] Test Alpha Vantage fetcher module
- [ ] Test SourceRegistry routing integration
- [ ] All akshare calls wrapped in run_in_thread
- [ ] Backend tests pass
- [ ] E2E verification passes
- [ ] Frontend build + dev server starts
