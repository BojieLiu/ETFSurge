def compute_ma(close, window: int):
    import pandas as pd
    return close.rolling(window=window).mean()


def compute_ema(close, window: int):
    import pandas as pd
    return close.ewm(span=window, adjust=False).mean()


def compute_macd(close, fast=12, slow=26, signal=9) -> dict:
    import pandas as pd
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = 2 * (dif - dea)
    return {
        "dif": dif.iloc[-1] if not dif.empty else 0,
        "dea": dea.iloc[-1] if not dea.empty else 0,
        "macd": macd_bar.iloc[-1] if not macd_bar.empty else 0,
        "histogram": macd_bar.tail(30).tolist() if len(macd_bar) >= 30 else macd_bar.tolist(),
    }


def compute_rsi(close, window=14) -> float:
    import numpy as np
    import pandas as pd
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50


def compute_kdj(high, low, close, window=9) -> dict:
    import numpy as np
    import pandas as pd
    low_min = low.rolling(window=window).min()
    high_max = high.rolling(window=window).max()
    rsv = (close - low_min) / (high_max - low_min).replace(0, np.nan) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {
        "k": float(k.iloc[-1]) if not k.empty else 50,
        "d": float(d.iloc[-1]) if not d.empty else 50,
        "j": float(j.iloc[-1]) if not j.empty else 50,
    }


def compute_bollinger(close, window=20, num_std=2) -> dict:
    import pandas as pd
    ma = compute_ma(close, window)
    std = close.rolling(window=window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return {
        "ma": float(ma.iloc[-1]) if not ma.empty else 0,
        "upper": float(upper.iloc[-1]) if not upper.empty else 0,
        "lower": float(lower.iloc[-1]) if not lower.empty else 0,
        "bandwidth": float((upper.iloc[-1] - lower.iloc[-1]) / ma.iloc[-1] * 100)
        if not (upper.empty or lower.empty or ma.empty) and ma.iloc[-1]
        else 0,
    }


COL_MAP = {"收盘": ["收盘", "close", "Close"], "最高": ["最高", "high", "High"], "最低": ["最低", "low", "Low"]}


def _resolve_col(data, aliases):
    for a in aliases:
        if a in data.columns:
            return a
    return aliases[0]


def compute_all_indicators(df: list[dict]) -> dict:
    import pandas as pd
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
    return {
        "ma5": float(compute_ma(close, 5).iloc[-1]) if len(close) >= 5 else None,
        "ma10": float(compute_ma(close, 10).iloc[-1]) if len(close) >= 10 else None,
        "ma20": float(compute_ma(close, 20).iloc[-1]) if len(close) >= 20 else None,
        "ma60": float(compute_ma(close, 60).iloc[-1]) if len(close) >= 60 else None,
        "macd": compute_macd(close),
        "rsi": compute_rsi(close),
        "kdj": compute_kdj(high, low, close),
        "bollinger": compute_bollinger(close),
    }


def _to_list(s):
    import pandas as pd
    return [None if pd.isna(v) else float(v) for v in s]


def compute_chart_data(df: list[dict]) -> dict:
    """返回 K 线图所需全部数据（含指标序列）。"""
    import pandas as pd
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

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_hist = 2 * (dif - dea)

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
