"""初始化全球指数表 indices（替代硬编码 _GLOBAL_INDEX_DEFS）。

指数定义基本不变，属于低频维护数据。直接写库即可，无需从 akshare 拉取。

round29 续轮: 本模块自 `scripts/` 移入 `app/fetchers/`——scripts/ 被 .dockerignore
排除出镜像，容器内 import `scripts.*` 会 `No module named 'scripts'`。移入 app 包后
容器/生产路径可正常 import（与 sync_instruments / sync_indices_meta 同一 R30 模式）。

运行:
  python -m app.fetchers.sync_indices
"""
import asyncio


async def sync() -> None:
    from app.database import async_session, init_db
    from app.models.search import Index
    from app.services.market_service import _GLOBAL_INDEX_DEFS
    from sqlalchemy import select

    # (symbol, name, region) -> 推断 source
    def _source(symbol: str) -> str:
        if symbol.startswith("^"):
            return "yfinance"
        return "akshare"

    def _currency(region: str) -> str:
        return {"港股": "HKD", "美股": "USD", "日经": "JPY", "韩国": "KRW"}.get(region, "CNY")

    rows = [
        {
            "symbol": sym,
            "name": name,
            "region": region,
            "asset_type": "index",
            "currency": _currency(region),
            "source": _source(sym),
        }
        for sym, name, region in _GLOBAL_INDEX_DEFS
    ]

    await init_db()
    async with async_session() as session:
        # 仅插入不存在的，保留已有的自定义行
        existing = set(
            r[0] for r in (await session.execute(select(Index.symbol))).all()
        )
        for r in rows:
            if r["symbol"] not in existing:
                session.add(Index(**r))
        await session.commit()
    print(f"[sync_indices] ensured {len(rows)} indices (existing: {len(existing)}).")


if __name__ == "__main__":
    asyncio.run(sync())
