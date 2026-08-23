"""instruments 表同步 service（F17, round6 §16.5）。

- 启动自动同步：lifespan 后台任务调用（不阻塞启动/健康检查，失败静默）；
- scheduler 每日 16:30 同步：复用本函数（内置防并发互斥锁，避免双写竞态）；
- 全部段失败保留旧表（N09 语义，不复用 collect_all 的空表风险）。
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# F17: 防并发互斥锁 + 运行标志（启动同步与每日同步不得同时写表）
_sync_lock = asyncio.Lock()
_syncing = False

# O1 (round8 §7 P0-新): 服务层整体超时——默认 120s（可 env 覆盖），
# 覆盖 collect_all 内部所有段（含美股黑洞段），超时仅降级不阻塞启动。
_INSTRUMENTS_SYNC_TIMEOUT = float(os.environ.get("INSTRUMENTS_SYNC_TIMEOUT", "120"))


def _sync_disabled() -> bool:
    """O1: 环境开关 INSTRUMENTS_SYNC_DISABLED=1 跳过 instruments 同步。"""
    return os.environ.get("INSTRUMENTS_SYNC_DISABLED", "").strip().lower() in ("1", "true", "yes")


async def _collect() -> list[dict]:
    """复用 app.fetchers.sync_instruments 的收集逻辑（A 股/ETF/港股分段）。

    round25 R30: 原 `from scripts.sync_instruments import collect_all`——scripts/ 被
    .dockerignore 排除出容器镜像，容器内启动同步静默失败（No module named 'scripts'）；
    生产代码已移入 app/fetchers/。
    """
    from ..fetchers.sync_instruments import collect_all
    return await collect_all()


async def sync_instruments_table() -> int:
    """全量同步 instruments 表。成功返回行数；失败/被锁返回 0；永不抛异常。"""
    global _syncing
    if _sync_disabled():
        logger.info("[instruments-sync] INSTRUMENTS_SYNC_DISABLED=1 — skip")
        return 0
    if _syncing:
        logger.info("[instruments-sync] already running — skip (mutex)")
        return 0
    async with _sync_lock:
        _syncing = True
        try:
            # O1: 整体超时保护——黑洞段（US）在窗口内必然结束，不阻塞事件循环
            rows = await asyncio.wait_for(_collect(), timeout=_INSTRUMENTS_SYNC_TIMEOUT)
            if not rows:
                logger.warning(
                    "[instruments-sync] all segments failed — keeping existing table"
                )
                return 0
            from sqlalchemy import delete

            from app.database import async_session, init_db
            from app.models.search import Instrument

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
