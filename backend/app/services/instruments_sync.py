"""instruments 表同步 service（F17, round6 §16.5）。

- 启动自动同步：lifespan 后台任务调用（不阻塞启动/健康检查，失败静默）；
- scheduler 每日 16:30 同步：复用本函数（内置防并发互斥锁，避免双写竞态）；
- 全部段失败保留旧表（N09 语义，不复用 collect_all 的空表风险）。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# F17: 防并发互斥锁 + 运行标志（启动同步与每日同步不得同时写表）
_sync_lock = asyncio.Lock()
_syncing = False


async def _collect() -> list[dict]:
    """复用 scripts.sync_instruments 的收集逻辑（A 股/ETF/港股分段）。"""
    from scripts.sync_instruments import collect_all
    return await collect_all()


async def sync_instruments_table() -> int:
    """全量同步 instruments 表。成功返回行数；失败/被锁返回 0；永不抛异常。"""
    global _syncing
    if _syncing:
        logger.info("[instruments-sync] already running — skip (mutex)")
        return 0
    async with _sync_lock:
        _syncing = True
        try:
            rows = await _collect()
            if not rows:
                logger.warning(
                    "[instruments-sync] all segments failed — keeping existing table"
                )
                return 0
            from app.database import async_session, init_db
            from app.models.search import Instrument
            from sqlalchemy import delete

            await init_db()
            async with async_session() as session:
                await session.execute(delete(Instrument))
                session.add_all([
                    Instrument(
                        symbol=r["symbol"],
                        name=r["name"],
                        market=r["market"],
                        asset_type=r["asset_type"],
                        pinyin=r.get("pinyin", ""),
                        first_letter=r.get("first_letter", ""),
                    )
                    for r in rows
                ])
                await session.commit()
            logger.info("[instruments-sync] done: %d rows written", len(rows))
            return len(rows)
        except Exception as e:  # noqa: BLE001 — 启动路径失败静默（不阻塞应用）
            logger.warning("[instruments-sync] failed (non-fatal): %s", e)
            return 0
        finally:
            _syncing = False
