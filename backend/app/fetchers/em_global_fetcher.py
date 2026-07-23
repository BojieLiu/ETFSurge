"""
East Money Global Index Real-time Fetcher (akshare wrapper).

Uses akshare's index_global_spot_em() which queries East Money's
push2 API directly — free, stable from China, covers A/HK/US/EU/AP indices.

Column structure (after akshare decode):
  [0] code (int)     [1] symbol (e.g. 'GDAXI', 'SPX', 'HSI')
  [2] name (Chinese) [3] price (最新价)
  [4] change_amount   [5] change_pct   [6] prev_close
  [7] high            [8] low           [9] open
  [10] volume         [11] update_time
"""
from typing import Any
from ..utils.proxy import no_proxy
from ..core.logging import get_logger

logger = get_logger(__name__)

# Map East Money symbols → (our_symbol, region, display_name)
EM_SYMBOL_MAP: dict[str, tuple[str, str, str]] = {
    # A股
    "000001": ("000001", "A股", "上证指数"),
    "399001": ("399001", "A股", "深证成指"),
    "399006": ("399006", "A股", "创业板指"),
    "000300": ("000300", "A股", "沪深300"),
    "000688": ("000688", "A股", "科创50"),
    # 港股
    "HSI":    ("^HSI",   "港股", "恒生指数"),
    "HSCEI":  ("^HSCE",  "港股", "恒生国企指数"),
    # 亚太
    "N225":   ("^N225",  "日经", "日经225"),
    "KS11":   ("^KS11",  "韩国", "韩国综合指数"),
    # 美股
    "SPX":    ("^GSPC",  "美股", "标普500"),
    "NDX":    ("^IXIC",  "美股", "纳斯达克"),  # EM uses NDX not IXIC
    "DJIA":   ("^DJI",   "美股", "道琼斯"),
    # 欧洲
    "FTSE":   ("^FTSE",  "欧洲", "英国富时100"),  # EM uses FTSE not UKX
    "GDAXI":  ("^GDAXI", "欧洲", "德国DAX"),
    "FCHI":   ("^FCHI",  "欧洲", "法国CAC40"),  # EM uses FCHI not CAC
    "SX5E":   ("^STOXX50E", "欧洲", "欧洲斯托克50"),
}

def fetch_all() -> dict[str, list[dict[str, Any]]]:
    """Fetch all global index quotes from East Money.

    Returns:
        Dict keyed by region (A股, 港股, 美股, 日经, 韩国, 欧洲),
        each value being a list of normalized index entries.
    """
    import akshare as ak

    try:
        with no_proxy():
            df = ak.index_global_spot_em()
    except Exception as e:
        logger.warning("[em_global] index_global_spot_em failed: %s", e)
        return {}
    if df is None or df.empty:
        logger.warning("[em_global] index_global_spot_em returned empty")
        return {}

    sym_col = df.columns[1]    # symbol (ASCII, e.g. 'GDAXI')
    price_col = df.columns[3]  # 最新价
    chg_amount_col = df.columns[4]  # 涨跌额
    chg_pct_col = df.columns[5]     # 涨跌幅

    from collections import defaultdict
    regions: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for _, row in df.iterrows():
        em_sym = str(row[sym_col]).strip()
        matched = EM_SYMBOL_MAP.get(em_sym)
        if not matched:
            continue

        our_sym, region, display_name = matched
        price = row[price_col]
        chg_pct = row[chg_pct_col]
        chg_amount = row[chg_amount_col]

        entry = {
            "symbol": our_sym,
            "name": display_name,
            "region": region,
            "asset_type": "index",
            "price": float(price) if price is not None and price != "-" else None,
            "change_pct": float(chg_pct) if chg_pct is not None and chg_pct != "-" else None,
            "change_amount": float(chg_amount) if chg_amount is not None and chg_amount != "-" else None,
            "available": True,
        }
        regions[region].append(entry)

    return dict(regions)


def _fetch_tencent_hk_indices() -> dict[str, dict[str, Any]]:
    """Fetch HK index quotes via Tencent (QQ) finance API.

    More real-time and accurate than Sina for HSTECH.
    API format: http://qt.gtimg.cn/q=hk{symbol}
    Returns dict keyed by our symbol, empty dict on failure.
    """
    import urllib.request
    import json as _json

    TENCENT_SYMBOL_MAP: dict[str, str] = {
        "HSI": "^HSI",
        "HSCEI": "^HSCE",
        "HSTECH": "^HSTECH",
    }
    DISPLAY_NAMES: dict[str, str] = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
        "^HSTECH": "恒生科技指数",
    }

    codes = list(TENCENT_SYMBOL_MAP.keys())
    qstr = ",".join(f"hk{c}" for c in codes)
    url = f"http://qt.gtimg.cn/q={qstr}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("gbk").strip()
    except Exception:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        parts = line.split('"')[1].split("~")
        if len(parts) < 33:
            continue
        raw_code = parts[2].strip()
        our_sym = TENCENT_SYMBOL_MAP.get(raw_code)
        if not our_sym:
            continue

        price_str = parts[3].strip()
        prev_close_str = parts[4].strip()
        change_str = parts[31].strip()
        change_pct_str = parts[32].strip()

        try:
            price = float(price_str) if price_str else None
            prev_close = float(prev_close_str) if prev_close_str else None
            change_amt = float(change_str) if change_str else None
            change_pct = float(change_pct_str) if change_pct_str else None
        except (ValueError, TypeError):
            continue

        if price is None or price == 0:
            continue

        result[our_sym] = {
            "symbol": our_sym,
            "name": DISPLAY_NAMES.get(our_sym, ""),
            "region": "港股",
            "asset_type": "index",
            "price": price,
            "change_pct": change_pct,
            "change_amount": change_amt,
            "available": True,
        }

    return result


def fetch_hk_indices() -> dict[str, dict[str, Any]]:
    """Fetch Hong Kong index quotes — Tencent (QQ) preferred, Sina HK fallback.

    Tencent API has real-time timestamps and is more accurate for HSTECH.
    Sina HK covers the same symbols as a backup.

    Returns:
        Dict keyed by ``our_symbol`` (e.g. ``^HSTECH``) → normalized entry.
        Empty dict on failure.
    """
    # Tier 1: Tencent (QQ) — 更实时、更准确
    tencent = _fetch_tencent_hk_indices()
    if tencent:
        return tencent

    # Tier 2: Sina HK (akshare) — 兜底
    import akshare as ak

    with no_proxy():
        df = ak.stock_hk_index_spot_sina()
    if df is None or df.empty:
        logger.warning("[hk_indices] all HK sources failed")
        return {}

    sym_col = df.columns[0]     # code
    price_col = df.columns[2]    # 最新价
    chg_amount_col = df.columns[3]  # 涨跌额
    chg_pct_col = df.columns[4]  # 涨跌幅

    HK_SYMBOL_MAP: dict[str, str] = {
        "HSI": "^HSI",
        "HSCEI": "^HSCE",
        "HSTECH": "^HSTECH",
    }
    DISPLAY_NAMES: dict[str, str] = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
        "^HSTECH": "恒生科技指数",
    }

    result: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        code = str(row[sym_col]).strip()
        our_sym = HK_SYMBOL_MAP.get(code)
        if not our_sym:
            continue

        price = row[price_col]
        chg_pct = row[chg_pct_col]
        chg_amount = row[chg_amount_col]

        result[our_sym] = {
            "symbol": our_sym,
            "name": DISPLAY_NAMES.get(our_sym, ""),
            "region": "港股",
            "asset_type": "index",
            "price": float(price) if price is not None and price != "-" else None,
            "change_pct": float(chg_pct) if chg_pct is not None and chg_pct != "-" else None,
            "change_amount": float(chg_amount) if chg_amount is not None and chg_amount != "-" else None,
            "available": True,
        }

    return result
