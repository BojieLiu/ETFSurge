"""同步行业/概念板块到本地 sectors 表（供行情分析下拉框）。

数据源: levistock（优先）→ akshare 降级，与 sector_fetcher 一致。
运行:
  python -m scripts.sync_sectors
"""

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


async def collect_all() -> list[dict]:
    from app.fetchers.sector_fetcher import _try_two
    from app.fetchers.sector_fetcher import _ak_industry_sectors, _ak_concept_sectors
    import levistock as lv

    def _lv_industry():
        try:
            return lv.sector_em("industry")
        except Exception:
            return []

    def _lv_concept():
        try:
            return lv.sector_em("concept")
        except Exception:
            return []

    ind = _try_two(_lv_industry, _ak_industry_sectors, default=[])
    con = _try_two(_lv_concept, _ak_concept_sectors, default=[])

    out = []
    for s in ind:
        code = str(s.get("sector_code") or s.get("code") or s.get("bk_code") or "").strip()
        name = str(s.get("sector_name") or s.get("name") or s.get("bk_name") or "").strip()
        if code and name:
            out.append({"code": code, "name": name, "type": "industry"})
    for s in con:
        code = str(s.get("sector_code") or s.get("code") or s.get("bk_code") or "").strip()
        name = str(s.get("sector_name") or s.get("name") or s.get("bk_name") or "").strip()
        if code and name:
            out.append({"code": code, "name": name, "type": "concept"})
    return out


async def sync():
    from app.database import async_session, init_db
    from app.models.search import Sector
    from sqlalchemy import delete

    print("[sync_sectors] collecting...")
    rows = await collect_all()
    print(f"[sync_sectors] got {len(rows)} sectors")

    await init_db()
    async with async_session() as session:
        await session.execute(delete(Sector))
        session.add_all([
            Sector(code=r["code"], name=r["name"], type=r["type"])
            for r in rows
        ])
        await session.commit()
    print(f"[sync_sectors] done. {len(rows)} rows written.")


if __name__ == "__main__":
    asyncio.run(sync())
