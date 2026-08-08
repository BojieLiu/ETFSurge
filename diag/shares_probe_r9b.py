# -*- coding: utf-8 -*-
"""round9: 实测 akshare fund_etf_hist_em 对场内 ETF 的份额列（P1-9 主源）"""
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main():
    import akshare as ak
    for sym in ("510050", "159338", "518880"):
        try:
            df = ak.fund_etf_hist_em(symbol=sym, period="daily", start_date="20260101", end_date="20260807", adjust="")
            print("=== %s rows=%d cols=%s" % (sym, 0 if df is None else len(df),
                                              list(df.columns)[:12] if df is not None else None))
            if df is not None and len(df) > 0:
                print("   last row:", df.iloc[-1].to_dict())
        except Exception as e:
            print("=== %s FAIL: %s %s" % (sym, type(e).__name__, str(e)[:150]))


main()
