from typing import Any

import requests

from ..utils.proxy import no_proxy


def _to_stooq(symbol: str) -> str:
    """将 APP 内的原始代码(如 'SPY')转换为 Stooq 代码 'spy.us'。"""
    s = symbol.strip().lower()
    if s.endswith(".us"):
        return s
    return f"{s}.us"


def fetch_us_etf_realtime(symbol: str | None = None) -> list[dict[str, Any]]:
    """Stooq 美股/ETF 实时行情(免费、无需 key、稳定)。变动率以当日开盘近似。"""
    if not symbol:
        return []
    url = f"https://stooq.com/q/l/?s={_to_stooq(symbol)}&f=sd2t2ohlcv&h&e=csv"
    try:
        with no_proxy():
            r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if not r.text or "Symbol" not in r.text:
            return []
        import csv
        import io

        row = next(csv.DictReader(io.StringIO(r.text)), None)
        if not row:
            return []
        try:
            op = float(row.get("Open") or 0)
            cl = float(row.get("Close") or 0)
        except (ValueError, TypeError):
            return []
        return [{
            "symbol": symbol.upper(),
            "name": "",
            "price": cl,
            "change_pct": round((cl - op) / op * 100, 2) if op else 0.0,
            "change_amount": round(cl - op, 2) if op else 0.0,
            "volume": float(row.get("Volume") or 0),
            "asset_type": "US",
        }]
    except Exception:
        return []


def fetch_us_batch(symbols: list[str]) -> list[dict[str, Any]]:
    """批量获取美股/ETF 实时行情(逗号拼接,单次请求)。"""
    if not symbols:
        return []
    joined = ",".join(_to_stooq(s) for s in symbols)
    url = f"https://stooq.com/q/l/?s={joined}&f=sd2t2ohlcv&h&e=csv"
    try:
        with no_proxy():
            r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if not r.text or "Symbol" not in r.text:
            return []
        import csv
        import io

        out: list[dict[str, Any]] = []
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                sym_raw = (row.get("Symbol") or "").upper().replace(".US", "")
                op = float(row.get("Open") or 0)
                cl = float(row.get("Close") or 0)
            except (ValueError, TypeError):
                continue
            out.append({
                "symbol": sym_raw,
                "name": "",
                "price": cl,
                "change_pct": round((cl - op) / op * 100, 2) if op else 0.0,
                "change_amount": round(cl - op, 2) if op else 0.0,
                "volume": float(row.get("Volume") or 0),
                "asset_type": "US",
            })
        return out
    except Exception:
        return []


def fetch_stooq_history(
    symbol: str,
    period: str = "daily",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Stooq 美股/ETF 历史 K 线(daily/weekly/monthly)。"""
    interval = {"weekly": "w", "monthly": "m"}.get(period, "d")
    url = f"https://stooq.com/q/d/l/?s={_to_stooq(symbol)}&i={interval}"
    if start_date and end_date:
        url += f"&d1={start_date}&d2={end_date}"
    try:
        with no_proxy():
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if not r.text or "Date" not in r.text:
            return []
        import csv
        import io

        out: list[dict[str, Any]] = []
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                out.append({
                    "日期": str(row.get("Date", "")),
                    "开盘": float(row.get("Open") or 0),
                    "最高": float(row.get("High") or 0),
                    "最低": float(row.get("Low") or 0),
                    "收盘": float(row.get("Close") or 0),
                    "成交量": float(row.get("Volume") or 0),
                })
            except (ValueError, TypeError):
                continue
        return out
    except Exception:
        return []
