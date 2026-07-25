"""Add market parameter to /market/search endpoint."""
with open('app/routers/market.py', 'r', encoding='utf-8') as f:
    src = f.read()

old = '''@router.get("/search")
async def search(keyword: str = Query("")) -> list[dict[str, Any]]:
    return await search_etf(keyword)'''

new = '''@router.get("/search")
async def search(
    keyword: str = Query(""),
    market: str | None = Query(None, description="Market filter: A/HK/US/global"),
) -> list[dict[str, Any]]:
    """Unified search: market=A searches stocks via instruments table, default searches ETFs."""
    from ..models.search import Instrument
    from sqlalchemy import select, or_

    if market and market.upper() == "A":
        try:
            async with async_session() as session:
                stmt = select(Instrument).where(
                    Instrument.is_active == True,
                    Instrument.market == "A",
                    Instrument.asset_type == "stock",
                )
                if keyword:
                    kw = keyword.lower()
                    stmt = stmt.where(
                        or_(
                            Instrument.symbol.ilike(f"%{kw}%"),
                            Instrument.name.ilike(f"%{kw}%"),
                            Instrument.pinyin.ilike(f"%{kw}%"),
                            Instrument.first_letter.ilike(f"%{kw}%"),
                        )
                    )
                stmt = stmt.limit(30)
                rows = (await session.execute(stmt)).scalars().all()
                if rows:
                    return [{
                        "symbol": r.symbol, "name": r.name,
                        "market": r.market, "asset_type": r.asset_type,
                        "type": "stock",
                    } for r in rows]
        except Exception as e:
            logger.warning("[search] stock search failed: %s", e)
        return []

    return await search_etf(keyword)'''

assert old in src, 'Old text not found in file!'
src = src.replace(old, new, 1)
with open('app/routers/market.py', 'w', encoding='utf-8') as f:
    f.write(src)
print('OK: /market/search endpoint updated with market parameter')
