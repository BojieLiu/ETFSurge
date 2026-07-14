# -*- coding: utf-8 -*-
with open('E:/ETF_Surge/backend/app/services/portfolio_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the function start
idx = content.find('def _build_price_map(etfs: list[PortfolioETF]) -> dict[str, tuple[float, float]]:')
if idx >= 0:
    # Find the end of the function (next function def at same indent)
    idx2 = content.find('\ndef ', idx + 1)
    if idx2 == -1:
        idx2 = len(content)
    
    old_func = content[idx:idx2]
    print("Found function, length:", len(old_func))
    print("---")
    print(repr(old_func[:500]))
    
    new_func = '''def _build_price_map(etfs: list[PortfolioETF | dict]) -> dict[str, tuple[float, float]]:
    """批量获取一组持仓的实时价格，返回 {symbol: (price, change_pct)} 映射表。"""
    from ..fetchers.akshare_fetcher import (
        fetch_a_stock_batch, fetch_fund_nav, fetch_hk_stock_realtime, fetch_index_realtime,
    )

    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)

    a_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "A" and _get_attr(e, "symbol", "")[:1] in ("1", "5", "6")]
    hk_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "HK"]
    us_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "US"]
    # 离岸/场外 ETF 按 tracked_index 获取实时行情
    tracked_a = [_get_attr(e, "tracked_index") for e in etfs if _get_attr(e, "tracked_index") and _get_attr(e, "tracked_index", "")[:1] in ("1", "5", "6")]
    a_symbols = a_symbols + tracked_a
    m: dict[str, tuple[float, float]] = {}

    if a_symbols:
        try:
            all_a = fetch_a_stock_batch(a_symbols)
            for item in all_a:
                m[item["symbol"]] = (item["price"], item["change_pct"])
        except Exception:
            pass

    if hk_symbols:
        try:
            for s in hk_symbols:
                items = fetch_hk_stock_realtime(s)
                if items:
                    item = items[0]
                    m[s] = (item["price"], item["change_pct"])
        except Exception:
            pass

    for s in us_symbols:
        try:
            data = fetch_us_etf_realtime(s)
            if data:
                m[s] = (data["price"], data["change_pct"])
        except Exception:
            pass

    # Also fetch tracked indices for off-exchange funds
    tracked = list({_get_attr(e, "tracked_index") for e in etfs if _get_attr(e, "tracked_index") and _get_attr(e, "tracked_index") not in m})
    if tracked:
        try:
            all_idx = fetch_index_realtime()
            for item in all_idx:
                if item["symbol"] in tracked:
                    m[item["symbol"]] = (item["price"], item["change_pct"])
        except Exception:
            pass
        # Fallback: compute change from NAV if still missing
        for t in tracked:
            if t not in m:
                try:
                    nav_data = fetch_fund_nav(t)
                    if nav_data and nav_data.get("nav") and nav_data.get("nav_date"):
                        from datetime import datetime, timedelta
                        nav = float(nav_data["nav"])
                        nav_date = datetime.strptime(nav_data["nav_date"], "%Y-%m-%d")
                        if (datetime.now() - nav_date).days <= 3:
                            m[t] = (nav, 0.0)
                except Exception:
                    pass

    return m

'''
    
    new_content = content[:idx] + new_func + content[idx2:]
    with open('E:/ETF_Surge/backend/app/services/portfolio_service.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Replaced successfully!")
else:
    print("Function not found")