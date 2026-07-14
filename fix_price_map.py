# -*- coding: utf-8 -*-
with open('E:/ETF_Surge/backend/app/services/portfolio_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = """def _build_price_map(etfs: list[PortfolioETF]) -> dict[str, tuple[float, float]]:
    \"\"\"批量获取一组持仓的实时价格，返回 {symbol: (price, change_pct)} 映射表。\"\"\"
    from ..fetchers.akshare_fetcher import (
        fetch_a_stock_batch, fetch_fund_nav, fetch_hk_stock_realtime, fetch_index_realtime,
    )

    a_symbols = [e.symbol for e in etfs if e.asset_type == "A" and e.symbol[:1] in ("1", "5", "6")]
    hk_symbols = [e.symbol for e in etfs if e.asset_type == "HK"]
    us_symbols = [e.symbol for e in etfs if e.asset_type == "US\"]"""

new = """def _build_price_map(etfs: list[PortfolioETF | dict]) -> dict[str, tuple[float, float]]:
    \"\"\"批量获取一组持仓的实时价格，返回 {symbol: (price, change_pct)} 映射表。\"\"\"
    from ..fetchers.akshare_fetcher import (
        fetch_a_stock_batch, fetch_fund_nav, fetch_hk_stock_realtime, fetch_index_realtime,
    )

    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)

    a_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "A" and _get_attr(e, "symbol", "")[:1] in ("1", "5", "6")]
    hk_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "HK"]
    us_symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "asset_type") == "US\"]"""

if old in content:
    content = content.replace(old, new)
    with open('E:/ETF_Surge/backend/app/services/portfolio_service.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Replaced!')
else:
    print('NOT FOUND')
    idx = content.find('a_symbols = [e.symbol')
    print(repr(content[idx:idx+200]))