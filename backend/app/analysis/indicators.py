"""
Technical analysis indicators — powered by pandas-ta.

Replaces hand-rolled MA/EMA/MACD/RSI/KDJ/Bollinger with battle-tested
pandas-ta implementations. All public function signatures and return
formats preserved.

Changes from previous implementation:
  - pandas-ta EMA uses adjust=True (standard); prior used adjust=False.
    MACD values differ slightly (~0.005) after convergence; both are valid.
  - RSI no longer returns NaN when loss=0 (monotonic uptrend).
    pandas-ta correctly returns 100.0.
  - Bollinger Bandwidth via pandas-ta's pre-computed BBB column.
"""

import numpy as np
import pandas as pd
import pandas_ta as ta


def compute_ma(close, window: int):
    """Simple moving average.
    
    Returns empty Series (same index, NaN values) when data is insufficient,
    matching the old close.rolling(window).mean() behavior.
    """
    result = ta.sma(close, length=window)
    if result is None:
        return pd.Series(index=close.index, dtype=float)
    return result


def compute_ema(close, window: int):
    """Exponential moving average (uses pandas_ta, adjust=True).
    
    Returns empty Series (same index, NaN values) when data is insufficient.
    """
    result = ta.ema(close, length=window)
    if result is None:
        return pd.Series(index=close.index, dtype=float)
    return result


def compute_macd(close, fast=12, slow=26, signal=9) -> dict:
    """
    MACD indicator.

    Return format preserved:
      {"dif": float, "dea": float, "macd": float (2x histogram), "histogram": [float]}
    """
    result = ta.macd(close, fast=fast, slow=slow, signal=signal)
    if result is None or result.empty:
        return {"dif": 0, "dea": 0, "macd": 0, "histogram": []}

    dif_col = f"MACD_{fast}_{slow}_{signal}"
    dea_col = f"MACDs_{fast}_{slow}_{signal}"
    hist_col = f"MACDh_{fast}_{slow}_{signal}"

    dif_series = result[dif_col]
    dea_series = result[dea_col]
    hist_series = result[hist_col]

    dif_val = float(dif_series.iloc[-1]) if not dif_series.empty else 0
    dea_val = float(dea_series.iloc[-1]) if not dea_series.empty else 0
    # Preserve 2x scaling for backward compatibility
    hist_val = float(hist_series.iloc[-1]) * 2 if not hist_series.empty else 0
    hist_list = (hist_series.tail(30) * 2).tolist() if len(hist_series) >= 30 else (hist_series * 2).tolist()

    return {
        "dif": dif_val,
        "dea": dea_val,
        "macd": hist_val,
        "histogram": hist_list,
    }


def compute_rsi(close, window=14) -> float:
    """Relative Strength Index."""
    result = ta.rsi(close, length=window)
    if result is None or result.empty:
        return 50.0
    val = result.iloc[-1]
    return float(val) if not np.isnan(val) else 50.0


def compute_kdj(high, low, close, window=9) -> dict:
    """KDJ stochastic oscillator."""
    result = ta.kdj(high=high, low=low, close=close, k=window, d=3)  # type: ignore[arg-type]
    if result is None or result.empty:
        return {"k": 50.0, "d": 50.0, "j": 50.0}

    k_col = f"K_{window}_3"
    d_col = f"D_{window}_3"
    j_col = f"J_{window}_3"

    k_val = float(result[k_col].iloc[-1]) if k_col in result.columns and not result[k_col].empty else 50.0
    d_val = float(result[d_col].iloc[-1]) if d_col in result.columns and not result[d_col].empty else 50.0
    j_val = float(result[j_col].iloc[-1]) if j_col in result.columns and not result[j_col].empty else 50.0

    return {"k": k_val, "d": d_val, "j": j_val}


def compute_bollinger(close, window=20, num_std=2) -> dict:
    """Bollinger Bands."""
    result = ta.bbands(close, length=window, std=num_std)
    if result is None or result.empty:
        return {"ma": 0, "upper": 0, "lower": 0, "bandwidth": 0}

    bbm_col = f"BBM_{window}_{num_std}_{num_std}"
    bbu_col = f"BBU_{window}_{num_std}_{num_std}"
    bbl_col = f"BBL_{window}_{num_std}_{num_std}"
    bbb_col = f"BBB_{window}_{num_std}_{num_std}"

    ma_val = float(result[bbm_col].iloc[-1]) if bbm_col in result.columns and not result[bbm_col].empty else 0
    upper_val = float(result[bbu_col].iloc[-1]) if bbu_col in result.columns and not result[bbu_col].empty else 0
    lower_val = float(result[bbl_col].iloc[-1]) if bbl_col in result.columns and not result[bbl_col].empty else 0
    bandwidth_val = float(result[bbb_col].iloc[-1]) if bbb_col in result.columns and not result[bbb_col].empty else 0

    return {
        "ma": ma_val,
        "upper": upper_val,
        "lower": lower_val,
        "bandwidth": bandwidth_val,
    }


# ── Chinese column name aliases ──────────────────────────────────
COL_MAP = {"收盘": ["收盘", "close", "Close"], "最高": ["最高", "high", "High"], "最低": ["最低", "low", "Low"]}


def _resolve_col(data, aliases):
    for a in aliases:
        if a in data.columns:
            return a
    return aliases[0]


def compute_all_indicators(df: list[dict], factor_scores: dict | None = None) -> dict:
    """Compute all technical indicators.

    When factor_scores is provided (from FactorRegistry), reuse RSI/KDJ/MACD
    values to avoid redundant computation.
    """
    if not df:
        return {}
    data = pd.DataFrame(df)
    close_col = _resolve_col(data, COL_MAP["收盘"])
    if close_col not in data.columns:
        return {}
    close = data[close_col].astype(float)
    high_col = _resolve_col(data, COL_MAP["最高"])
    high = data[high_col].astype(float) if high_col in data.columns else close
    low_col = _resolve_col(data, COL_MAP["最低"])
    low = data[low_col].astype(float) if low_col in data.columns else close

    result = {
        "ma5": float(compute_ma(close, 5).iloc[-1]) if len(close) >= 5 else None,
        "ma10": float(compute_ma(close, 10).iloc[-1]) if len(close) >= 10 else None,
        "ma20": float(compute_ma(close, 20).iloc[-1]) if len(close) >= 20 else None,
        "ma60": float(compute_ma(close, 60).iloc[-1]) if len(close) >= 60 else None,
        "bollinger": compute_bollinger(close),
    }

    # Reuse FactorRegistry factor scores to avoid redundant computation
    if factor_scores:
        rsi = factor_scores.get("technical.rsi.rsi_14")
        if rsi is not None:
            result["rsi"] = rsi
        else:
            result["rsi"] = compute_rsi(close)

        k_value = factor_scores.get("technical.kdj.k_value")
        d_value = factor_scores.get("technical.kdj.d_value")
        j_value = factor_scores.get("technical.kdj.j_value")
        if all(v is not None for v in (k_value, d_value, j_value)):
            result["kdj"] = {"k": k_value, "d": d_value, "j": j_value}
        else:
            result["kdj"] = compute_kdj(high, low, close)

        macd_val = factor_scores.get("technical.macd.macd")
        if macd_val is not None:
            result["macd"] = {"dif": 0, "dea": 0, "macd": macd_val, "histogram": []}
        else:
            result["macd"] = compute_macd(close)
    else:
        result["rsi"] = compute_rsi(close)
        result["kdj"] = compute_kdj(high, low, close)
        result["macd"] = compute_macd(close)

    return result


def _to_list(s):
    return [None if pd.isna(v) else float(v) for v in s]


def compute_chart_data(df: list[dict]) -> dict:
    """Return full k-line chart data (including indicator series)."""
    if not df:
        return {
            "dates": [], "opens": [], "highs": [], "lows": [], "closes": [], "volumes": [],
            "ma5": [], "ma10": [], "ma20": [], "ma60": [],
            "bollinger": {"upper": [], "middle": [], "lower": []},
            "macd": {"dif": [], "dea": [], "histogram": []},
        }
    data = pd.DataFrame(df)
    close = data["收盘"].astype(float)
    high = data.get("最高", close).astype(float)
    low = data.get("最低", close).astype(float)
    volume = data.get("成交量", pd.Series([0] * len(data))).astype(float)

    dates = data.get("日期", pd.Series([""] * len(data)))
    dates = [str(d) for d in dates]

    ma5 = _to_list(compute_ma(close, 5))
    ma10 = _to_list(compute_ma(close, 10))
    ma20 = _to_list(compute_ma(close, 20))
    ma60 = _to_list(compute_ma(close, 60)) if len(close) >= 60 else [None] * len(close)

    ma20_series = compute_ma(close, 20)
    std_series = close.rolling(window=20).std()
    boll_upper = _to_list(ma20_series + 2 * std_series)
    boll_middle = _to_list(ma20_series)
    boll_lower = _to_list(ma20_series - 2 * std_series)

    # MACD series for chart: use pandas-ta for the underlying calculation
    macd_pt = ta.macd(close, fast=12, slow=26, signal=9)
    dif = macd_pt["MACD_12_26_9"]
    dea = macd_pt["MACDs_12_26_9"]
    macd_hist = 2 * macd_pt["MACDh_12_26_9"]

    return {
        "dates": dates,
        "opens": _to_list(data["开盘"]),
        "highs": _to_list(high),
        "lows": _to_list(low),
        "closes": _to_list(close),
        "volumes": _to_list(volume),
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "bollinger": {"upper": boll_upper, "middle": boll_middle, "lower": boll_lower},
        "macd": {"dif": _to_list(dif), "dea": _to_list(dea), "histogram": _to_list(macd_hist)},
    }
