"""
verify.py — 快速链路验证，不启动服务器
用法: python scripts/verify.py [模块名]

模块名可选:
  all      全部 (默认)
  models   数据库模型 + schema
  service  组合服务逻辑 (P&L、分配计算)
  market   行情服务 + 数据源
  analysis 技术指标计算
  index    指数历史数据 (场外分析)
"""

import sys
import os
import importlib
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
TIMING = []


def section(name):
    print(f"\n── {name} ─{'─' * (60 - len(name))}")


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        mark = "PASS"
    else:
        FAIL += 1
        mark = "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def check_eq(label, actual, expected, detail=""):
    check(label, actual == expected, detail or f"got {actual!r}")


def timed(label, fn):
    t0 = time.time()
    try:
        result = fn()
        elapsed = time.time() - t0
        TIMING.append((label, elapsed))
        if result is None or result is True:
            check(label, True, f"{elapsed:.2f}s")
        else:
            check(label, True, f"{elapsed:.2f}s → {result}")
        return result
    except Exception as e:
        elapsed = time.time() - t0
        TIMING.append((label, elapsed))
        check(label, False, f"{elapsed:.2f}s — {e}")
        return None


# ── test suites ──────────────────────────────────────────────────


def test_models():
    section("Models & Schemas")
    from app.models.portfolio import PortfolioETF
    from app.models.schemas import PNLItem, PNLSummary, PortfolioETFCreate

    cols = [c.name for c in PortfolioETF.__table__.columns]
    check("tracked_index column", "tracked_index" in cols)

    item = PNLItem(
        symbol="110011", name="易方达中小盘", short_name="易方达中小盘",
        asset_type="A", portfolio_type="off_exchange",
        target_amount=50000, current_price=0,
        change_pct=0.8, daily_pnl=400, tracked_index="000300",
    )
    check_eq("PNLItem tracked_index", item.tracked_index, "000300")

    summary = PNLSummary(items=[item], total_pnl=400.0, total_amount=50000.0, weighted_change_pct=0.8)
    d = summary.model_dump()
    check(f"PNLSummary total_pnl={d['total_pnl']}", d["total_pnl"] == 400.0)

    create = PortfolioETFCreate(symbol="159915", name="创业板ETF", target_weight=0.2, tracked_index="399006")
    check_eq("PortfolioETFCreate.tracked_index", create.tracked_index, "399006")


def test_service():
    section("Portfolio Service")
    from app.services.portfolio_service import (
        list_etfs, add_etf, update_etf, remove_etf,
        calculate_allocation, calculate_daily_pnl, _build_price_map,
    )
    check("list_etfs imported", callable(list_etfs))
    check("add_etf imported", callable(add_etf))
    check("calculate_daily_pnl imported", callable(calculate_daily_pnl))

    import inspect
    sig = inspect.signature(calculate_daily_pnl)
    check("daily_pnl returns dict with total_pnl", "total_pnl" in str(sig.return_annotation))

    # Test _build_price_map with simulated ETFs
    from app.models.portfolio import PortfolioETF
    etfs = [
        PortfolioETF(symbol="510050", name="上证50ETF", asset_type="A", portfolio_type="on_exchange"),
        PortfolioETF(symbol="110011", name="易方达中小盘", asset_type="A", portfolio_type="off_exchange", tracked_index="000300"),
    ]
    result = timed("_build_price_map (on+off exchange)", lambda: _build_price_map(etfs))
    if result:
        check("510050 in price map", "510050" in result)
        check("000300 index fallback in map", "000300" in result)


def test_market():
    section("Market Service")
    from app.services.market_service import get_history, get_portfolio_realtime, get_all_realtime
    check("get_history imported", callable(get_history))
    check("get_portfolio_realtime imported", callable(get_portfolio_realtime))
    # Quick realtime fetch (lightweight)
    timed("get_all_realtime (indices)", lambda: __import__("asyncio").run(get_all_realtime()))


def test_analysis():
    section("Technical Analysis")
    from app.analysis.indicators import compute_all_indicators, compute_chart_data

    # Use mock data to avoid network
    mock_bars = [
        {"日期": "2024-01-01", "开盘": 100, "最高": 102, "最低": 99, "收盘": 101, "成交量": 10000},
        {"日期": "2024-01-02", "开盘": 101, "最高": 103, "最低": 100, "收盘": 102, "成交量": 12000},
        {"日期": "2024-01-03", "开盘": 102, "最高": 105, "最低": 101, "收盘": 104, "成交量": 15000},
    ] * 50  # 150 bars enough for all indicators

    ind = compute_all_indicators(mock_bars)
    check("all indicators present",
          all(k in ind for k in ["ma5", "ma10", "ma20", "ma60", "macd", "rsi", "kdj", "bollinger"]))
    check("MACD has dif/dea/histogram",
          all(k in ind["macd"] for k in ["dif", "dea", "macd", "histogram"]))

    chart = compute_chart_data(mock_bars)
    check("chart has dates/closes/volumes",
          len(chart.get("dates", [])) > 0 and len(chart.get("closes", [])) > 0)
    check("chart has MA series",
          len(chart.get("ma5", [])) > 0)


def test_index():
    section("Index History (Off-exchange Analysis)")
    from app.fetchers.akshare_fetcher import fetch_index_history, fetch_history

    data = timed("fetch_index_history(000300, daily)", lambda: fetch_index_history("000300", "daily"))
    if data and len(data) > 0:
        first = data[0]
        required = ["日期", "开盘", "最高", "最低", "收盘", "成交量"]
        check("index data has all required columns", all(k in first for k in required), f"got {list(first.keys())}")
        check(f"index data volume ({len(data)} bars)", len(data) > 100)

    data2 = timed("fetch_history(000300, index)", lambda: fetch_history("000300", "index", "daily"))
    if data2 and data:
        check("router returns same count as direct", len(data2) == len(data))

    # Test indicator computation on index data
    if data:
        from app.analysis.indicators import compute_all_indicators, compute_chart_data
        ind = timed("indicators on index data", lambda: compute_all_indicators(data))
        if ind:
            check("index indicators OK", all(k in ind for k in ["ma5", "ma10", "macd", "rsi"]))

        chart = timed("chart_data on index data", lambda: compute_chart_data(data))
        if chart:
            check("index chart dates match", len(chart.get("dates", [])) == len(data))


# ── main ─────────────────────────────────────────────────────────

def main():
    global PASS, FAIL
    suites = {
        "models": test_models,
        "service": test_service,
        "market": test_market,
        "analysis": test_analysis,
        "index": test_index,
    }

    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target == "all":
        order = ["models", "service", "analysis", "index", "market"]
        for name in order:
            suites[name]()
    elif target in suites:
        suites[target]()
    else:
        print(f"未知模块: {target}，可选: {', '.join(suites)}, all")
        sys.exit(1)

    # Summary
    elapsed_total = sum(t for _, t in TIMING)
    print(f"\n{'=' * 60}")
    print(f"  通过: {PASS}  失败: {FAIL}  耗时: {elapsed_total:.2f}s")
    if TIMING:
        slow = sorted(TIMING, key=lambda x: -x[1])[:3]
        print(f"  最慢: {', '.join(f'{lbl}={t:.2f}s' for lbl, t in slow)}")
    print(f"{'=' * 60}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
