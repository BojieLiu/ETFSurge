"""Sector / hot-plate mixin — split from market_data_hub (Batch 3)."""

import logging
import time

from app.core.market_calendar import market_session
from app.fetchers import sector_fetcher
from app.services.hub._common import (
    _load_latest_snapshot_sync,
    _normalize_hot_plate,
)

logger = logging.getLogger(__name__)

class SectorMixin:
    def get_sector_momentum(self) -> list[dict]:
        """获取板块动量，120s 缓存 TTL。

        round25 R40-a: 读取兜底闭环——缓存过期/空 且 盘后/收盘后（post_market /
        after_hours）时，读已落盘的 `sector_momentum` 快照（写入侧 `_persist_snapshot_
        after_refresh` 已有）；盘中缓存失效**不**用快照（避免昨日收盘冒充盘中实时），
        保持 `[]` 触发既有降级。旧实现只返内存缓存或 `[]`，从不读快照（「写了不读」）。
        """
        now = time.time()
        if self._sector_momentum_cache and (now - self._sector_momentum_cache_ts) < 120:
            return self._sector_momentum_cache
        # 缓存过期/空：盘后才回退快照（注入收盘动量）；盘中保持 []（诚实降级）
        try:
            session = market_session()
            if session in ("post_market", "after_hours"):
                snap = _load_latest_snapshot_sync("sector_momentum")
                if isinstance(snap, list) and snap:
                    self._sector_momentum_cache = snap
                    self._sector_momentum_cache_ts = time.time()
                    logger.info(
                        "[hub] sector momentum loaded from post-market snapshot (%d rows)",
                        len(snap),
                    )
                    return snap
        except Exception as e:
            logger.debug("[hub] sector momentum snapshot read failed (non-fatal): %s", e)
        return self._sector_momentum_cache or []


    def get_hot_plates(self, limit: int | None = None, market: str = "A") -> list[dict]:
        """热点板块。默认返回缓存；传 limit 时实时取数（保持路由语义）。

        F2-6 步骤A: 输出统一归一化（secu_name→name / up_reason→reason /
        plate_stock_up_num→stock_count / stock_list→lead_stocks 数组）。
        F16 (round6 §16.4): market=HK 走港股 push2delay 行业聚合；
        market=US 返回「暂不支持」（不返回 A 股数据）。
        """
        if market and market.upper() != "A":
            from ...fetchers.hk_hot_fetcher import get_hk_hot_plates
            if market.upper() == "HK":
                return get_hk_hot_plates(limit or 15)
            # round14 P2-AK: 美股热点板块——东财美股 spot 按行业聚合（实测 m:105 为个股
            # 含行业字段，akshare stock_us_industry_spot_em 已删除，见 fetch_us_plates）
            from ...fetchers.sector_fetcher import fetch_us_plates
            return fetch_us_plates(limit or 15)
        if limit is not None:
            try:
                rows = sector_fetcher.fetch_hot_plates(limit) or []
            except Exception as e:
                logger.warning("[hub] get_hot_plates(limit) failed: %s", e)
                return []
        else:
            rows = self._hot_plates_cache or []
        return [_normalize_hot_plate(r) for r in rows]


    def get_sector_heat(self, limit: int | None = None, market: str = "A") -> list[dict]:
        """获取板块热度排行（Phase 6.1.6）。

        F2-3: limit 传值时实时取数（与 get_hot_plates 语义一致），否则返回缓存。
        F16: market=HK 走港股行业聚合；market=US 暂不支持。
        """
        if market and market.upper() != "A":
            from ...fetchers.hk_hot_fetcher import get_hk_hot_plates
            if market.upper() == "HK":
                plates = get_hk_hot_plates(limit or 20)
                return [{"rank": i + 1, "name": p["name"], "heat_index": round(p["amount"] / 1e6, 1),
                         "change_pct": p["change_pct"], "plate_code": "HK"}
                        for i, p in enumerate(plates)]
            return []
        if limit is not None:
            try:
                # P0-17① (round16 3.19 R1): A 股热度优先走东财行业板块 spot
                # （自带真实涨跌幅+领涨股）——财联社 sign 失效后名称回填命中率仅 5/20。
                rows = sector_fetcher.fetch_sector_heat_em(limit)
                if rows:
                    return rows
                # EM 源失败 → 回退财联社 + 端点名称回填链
                return sector_fetcher.fetch_sector_heat(limit) or []
            except Exception as e:
                logger.warning("[hub] get_sector_heat(%s) failed: %s", limit, e)
                return []
        return self._sector_heat_cache or []


    def get_sector_industry(self, limit: int = 80) -> list[dict]:
        """行业板块列表（实时取数）。"""
        try:
            from ...fetchers.sector_fetcher import fetch_industry_sectors
            return fetch_industry_sectors(limit) or []
        except Exception as e:
            logger.warning("[hub] get_sector_industry failed: %s", e)
            return []


    def get_sector_concept(self, limit: int = 150) -> list[dict]:
        """概念板块列表（实时取数）。"""
        try:
            from ...fetchers.sector_fetcher import fetch_concept_sectors
            return fetch_concept_sectors(limit) or []
        except Exception as e:
            logger.warning("[hub] get_sector_concept failed: %s", e)
            return []


    def get_sector_stocks(self, sector_code: str) -> list[dict]:
        """板块成分股（实时取数）。"""
        try:
            from ...fetchers.sector_fetcher import fetch_sector_stocks
            return fetch_sector_stocks(sector_code) or []
        except Exception as e:
            logger.warning("[hub] get_sector_stocks(%s) failed: %s", sector_code, e)
            return []


    def get_fund_flow(self, symbol: str) -> dict | None:
        """个股资金流。"""
        try:
            from ...fetchers.fundamentals_fetcher import fetch_fund_flow
            return fetch_fund_flow(symbol)
        except Exception as e:
            logger.warning("[hub] get_fund_flow(%s) failed: %s", symbol, e)
            return None


    def get_hist_avg_volume(self, symbol: str, days: int = 20) -> dict | None:
        """历史平均成交量。"""
        try:
            from ...fetchers.fundamentals_fetcher import fetch_hist_avg_volume
            return fetch_hist_avg_volume(symbol, days)
        except Exception as e:
            logger.warning("[hub] get_hist_avg_volume(%s) failed: %s", symbol, e)
            return None


    def get_sector_popular_stocks(self, plate_code: str) -> list[dict]:
        """板块热门个股。"""
        try:
            from ...fetchers.sector_fetcher import fetch_sector_popular_stocks
            return fetch_sector_popular_stocks(plate_code) or []
        except Exception as e:
            logger.warning("[hub] get_sector_popular_stocks(%s) failed: %s", plate_code, e)
            return []


    def get_sector_history(self, sector_code: str) -> list[dict]:
        """板块历史行情。"""
        try:
            from ...fetchers.sector_fetcher import fetch_sector_history
            return fetch_sector_history(sector_code) or []
        except Exception as e:
            logger.warning("[hub] get_sector_history(%s) failed: %s", sector_code, e)
            return []


    def get_sector_industry_cls(self, limit: int = 80) -> list[dict]:
        """行业板块分类（轮动）。"""
        try:
            from ...fetchers.sector_fetcher import fetch_sector_industry_cls
            return fetch_sector_industry_cls(limit) or []
        except Exception as e:
            logger.warning("[hub] get_sector_industry_cls failed: %s", e)
            return []
