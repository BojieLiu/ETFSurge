"""indices_meta 表启动自动同步（P0-20，round16 3.21）。

- 启动自动同步：lifespan 后台任务调用（不阻塞启动/健康检查，失败静默）；
- 复用 scripts.sync_indices_meta 的收集逻辑（含 P0-20/P0-22 静态兜底段——
  「恒生港股通」系列 + 主流港股/美股指数，数据源失败时仍入表）；
- 全部段失败保留旧表（与 instruments_sync 同语义，避免空表覆盖）。
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_syncing = False

_INDICES_SYNC_TIMEOUT = float(os.environ.get("INDICES_SYNC_TIMEOUT", "120"))


def _sync_disabled() -> bool:
    """环境开关 INDICES_SYNC_DISABLED=1 跳过 indices_meta 同步。"""
    return os.environ.get("INDICES_SYNC_DISABLED", "").strip().lower() in ("1", "true", "yes")


async def _collect() -> list[dict]:
    """复用 app.fetchers.sync_indices_meta 的收集逻辑（A/HK/行业/概念 + 静态兜底段）。

    round25 R30: 原 `from scripts.sync_indices_meta import collect_all`——scripts/ 被
    .dockerignore 排除出容器镜像，容器内启动同步静默失败（No module named 'scripts'）；
    生产代码已移入 app/fetchers/。
    """
    from ..fetchers.sync_indices_meta import collect_all
    return await collect_all()


async def sync_indices_meta_table() -> int:
    """全量同步 indices_meta 表。成功返回行数；失败/被锁返回 0；永不抛异常。"""
    global _syncing
    if _sync_disabled():
        logger.info("[indices-meta-sync] INDICES_SYNC_DISABLED=1 — skip")
        return 0
    if _syncing:
        logger.info("[indices-meta-sync] already running — skip (mutex)")
        return 0
    async with _sync_lock:
        _syncing = True
        try:
            rows = await asyncio.wait_for(_collect(), timeout=_INDICES_SYNC_TIMEOUT)
            if not rows:
                logger.warning(
                    "[indices-meta-sync] all segments failed — keeping existing table"
                )
                return 0
            from app.database import async_session, init_db
            from app.models.search import IndexMeta
            from sqlalchemy import delete

            await init_db()
            async with async_session() as session:
                await session.execute(delete(IndexMeta))
                seen: set[tuple[str, str]] = set()
                added = []
                for r in rows:
                    key = (str(r.get("symbol", "")), str(r.get("market", "")))
                    if key in seen or not key[0]:
                        continue
                    seen.add(key)
                    pinyin = r.get("pinyin") or ""
                    first_letter = r.get("first_letter") or ""
                    if not pinyin:
                        try:
                            # round25 R30: 同 R30——生产代码自 scripts/ 移入 app/fetchers/
                            from ..fetchers.sync_indices_meta import _to_pinyin
                            pinyin, first_letter = _to_pinyin(r.get("name", ""))
                        except Exception:
                            pass
                    added.append(IndexMeta(
                        symbol=r["symbol"],
                        name=r["name"],
                        market=r["market"],
                        category=r.get("category", "broad"),
                        index_type=r.get("index_type", "price"),
                        source=r.get("source", "sync"),
                        pinyin=pinyin,
                        first_letter=first_letter,
                    ))
                session.add_all(added)
                await session.commit()
            logger.info("[indices-meta-sync] synced %d rows", len(added))
            return len(added)
        except Exception as e:  # noqa: BLE001
            logger.warning("[indices-meta-sync] sync failed (non-fatal): %s", e)
            return 0
        finally:
            _syncing = False
