"""Snapshot persistence mixin — split from market_data_hub (Batch 3)."""

import asyncio
import logging
from datetime import datetime

from app.core.market_calendar import market_session
from app.services.hub._common import (
    _snapshot_as_of_for,
    _persist_snapshot_sync,
    _load_latest_snapshot_sync,
)

logger = logging.getLogger(__name__)

class SnapshotMixin:
    async def _persist_snapshot_after_refresh(self, new_pool: dict) -> None:
        """round24 R26②: 盘后/熔断刷新成功 → 落盘候选池 + 板块动量快照（last-good 之上再一层）。

        原语义：仅在 post_market / after_hours 写（实时源时效场景不写，避免快照盖过实时）。
        round25 R40-b 放宽：**sector_momentum 只要 refresh 成功且非空即落盘**（盘中/收盘任一
        时点成功刷新都留下 last-good 快照，封堵「收盘后才首次启动 → 磁盘无快照 → 盘后兜底
        无物可兜」的首启空窗）；空 `[]` 不写（防空壳污染兜底）。读取侧仅在无 live 缓存时
        回退快照，故放宽写入不违反「快照盖过实时」意图。pool 快照保持盘后语义（pool 语义
        与 sector 不同，盘中实时池不该被快照盖过）。
        同步 sqlite 经 asyncio.to_thread 执行，不阻塞事件循环（符合 async def ≠ 阻塞）。
        """
        try:
            session = market_session()
            as_of = _snapshot_as_of_for()
            if not as_of:
                # R40-b: as_of 为 None（盘中/盘前）时 sector_momentum 快照仍可落盘——
                # 用当前时间戳代替（last-good 语义，仅作兜底不冒充收盘）
                as_of = datetime.now().isoformat(sep="T")
            pool_payload = {k: [dict(x) for x in v] for k, v in (new_pool or {}).items()}
            # pool 快照：保持盘后语义（post_market/after_hours 才写）
            if pool_payload and session in ("post_market", "after_hours"):
                await asyncio.to_thread(_persist_snapshot_sync, "pool", pool_payload, as_of)
            # sector_momentum 快照：R40-b 放宽——refresh 成功且非空即落盘（防空壳）
            sm = self.get_sector_momentum() or []
            if sm:
                await asyncio.to_thread(_persist_snapshot_sync, "sector_momentum", list(sm), as_of)
        except Exception as e:
            logger.debug("[hub] snapshot persist skipped (non-fatal): %s", e)


    def _load_pool_snapshot(self) -> dict | None:
        """round24 R26②: 读最近一条 pool 快照（盘后重启兜底，last-good 内存重启即丢）。"""
        try:
            snap = _load_latest_snapshot_sync("pool")
            if snap and isinstance(snap, dict):
                return snap
        except Exception:
            pass
        return None
