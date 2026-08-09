import sys, asyncio, traceback
sys.path.insert(0, "backend")
sys.path.insert(0, "backend/tests")
from _pytest.monkeypatch import MonkeyPatch
from app.services.market_data_hub import market_data_hub

calls = {"bench": 0, "shares": 0}

async def fake_get_market_history(symbol, asset_type="A", period="daily"):
    calls["bench"] += 1
    return [{"date": f"2026-07-{d:02d}", "close": 3000.0 + d} for d in range(1, 21)]

def fake_fetch_etf_shares_outstanding(symbol):
    calls["shares"] += 1
    return {"total_shares": 1e8, "shares_change_20d": 0.03}

mp = MonkeyPatch()
mp.setattr(market_data_hub, "get_market_history", fake_get_market_history)
import app.fetchers.china_market as cm
mp.setattr(cm, "fetch_etf_shares_outstanding", fake_fetch_etf_shares_outstanding)
market_data_hub._FUND_SHARES_CACHE.clear()

try:
    out = asyncio.run(market_data_hub._enrich_symbol_extra(
        ["510300", "588000", "512480"],
        {"510300": {"fund_scale": 100}, "588000": {"fund_scale": 50}, "512480": {}},
    ))
    print("calls:", calls)
    print("510300 keys:", sorted(out["510300"].keys()))
    print("benchmark_close len:", len(out["510300"].get("benchmark_close", [])))
    print("shares_change_20d:", out["510300"].get("shares_change_20d"))
    print("institutional_holdings_change:", out["510300"].get("institutional_holdings_change"))
    print("512480 keys:", sorted(out["512480"].keys()))
except Exception:
    traceback.print_exc()