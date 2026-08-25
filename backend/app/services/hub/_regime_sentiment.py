"""Market regime / sentiment mixin — split from market_data_hub (Batch 3)."""

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)


def _sentiment_cache_file() -> str:
    """A02 crash-recovery 情绪缓存落点单点。

    round35 RC-C5 (docs/round35-architecture-review.md §18.4): 原 dirname×3 把
    sentiment_cache.json 写到 backend/data（容器内碰巧正确、宿主机错位），收敛到
    settings.data_dir（正牌挂载卷）；写（刷新成功持久化）与读（失败回读恢复）
    两处共用本函数，杜绝双拷贝漂移。
    """
    from ...config import _DATA_DIR, settings

    data_dir = str(getattr(settings, "data_dir", "") or _DATA_DIR)
    return os.path.join(data_dir, "sentiment_cache.json")


class RegimeSentimentMixin:
    _regime_cache: dict[str, str] = {}


    _regime_cache_ts: float = 0


    REGIME_TTL = 60


    _sentiment_cache: dict | None = None


    _sentiment_cache_ts: float = 0


    SENTIMENT_TTL = 120


    @staticmethod
    def _is_market_hours() -> bool:
        """检查当前是否为A股交易时段。

        非交易时段：成交额数据可能为昨日值，应降低流动性权重。
        """
        from datetime import datetime as _dt
        now = _dt.now()
        if now.weekday() >= 5:  # 周末
            return False
        t = now.strftime("%H:%M")
        return "09:30" <= t <= "11:30" or "13:00" <= t <= "15:00"


    @staticmethod
    def _normalize_regime(regime: str) -> str:
        """C2: 将市场状态值映射到 _LAYER_WEIGHTS 表的 key。

        外部 detect_market_regime() 返回的值可能包含 `bull_strong`、`range_bound` 等，
        但 _LAYER_WEIGHTS 表使用 `bull`、`neutral` 等简化 key。

        E2 (round23 §10.2): 归一化逻辑提取 core/regime.normalize_regime 为单一口径
        （与 risk_controls 的熊市判定共用本模块），本方法保留为兼容委托。
        """
        from ...core.regime import normalize_regime
        return normalize_regime(regime)


    def get_market_regime(self, market: str = "A") -> str:
        """获取市场状态，60s 缓存。支持多市场（Phase 5.1）。"""
        now = time.time()
        cached = self._regime_cache.get(market)
        if cached and (now - self._regime_cache_ts) < self.REGIME_TTL:
            return cached
        # Cache miss — regime 由外部定时刷新，返回旧值或默认
        return self._regime_cache.get(market, "range_bound")


    async def update_market_regime(self, market: str = "A") -> None:
        """异步刷新市场状态（由 refresh() 或外部调度器调用）。

        Phase 5.1: 支持按市场刷新。
        C2: 同步更新 self.current_regime 以便 _compute_composite 使用最新市态。
        """
        try:
            from ..market_trends import detect_market_regime
            broad_index = {"A": "000001", "HK": "^HSI", "US": "^GSPC"}.get(market, "000001")
            # round13 §3.1 P1: A 市场刷新市态时组装宏观快照（fetch_macro_snapshot，
            # 24h 缓存；失败降级 None → detect_market_regime 行为与旧版一致）
            macro = None
            if market == "A":
                try:
                    from ...fetchers.macro_fetcher import fetch_macro_snapshot
                    macro = await asyncio.to_thread(fetch_macro_snapshot)
                except Exception as _me:
                    logger.warning("[pool] macro snapshot fetch failed for regime: %s", _me)
            regime = detect_market_regime(broad_index_code=broad_index, macro=macro)
            if regime:
                self._regime_cache[market] = regime
                self._regime_cache_ts = time.time()
                if market == "A":
                    self.current_regime = regime  # C2: 同步更新
                logger.info("[pool] regime updated for %s: %s", market, regime)
        except Exception as e:
            logger.exception("[pool] update_market_regime failed for %s: %s", market, e)


    async def refresh_sentiment_cache(self) -> None:
        """异步刷新市场情绪缓存（2.7.9）。"""
        try:
            from ...fetchers.fundamentals_fetcher import fetch_market_sentiment
            sentiment = await fetch_market_sentiment()
            if sentiment:
                self._sentiment_cache = sentiment
                self._sentiment_cache_ts = time.time()
                # A02: Persist sentiment cache to file for crash recovery
                # round36 ASYNC230/240 修复：文件 IO 移入 to_thread（事件循环不阻塞）；
                # round35 RC-C5: 落点随 settings.data_dir 收敛（原 dirname×3 → backend/data）
                _cache_file = _sentiment_cache_file()

                def _persist() -> None:
                    os.makedirs(os.path.dirname(_cache_file), exist_ok=True)
                    with open(_cache_file, "w", encoding="utf-8") as f:
                        json.dump({"sentiment": sentiment, "ts": time.time()}, f, ensure_ascii=False)

                await asyncio.to_thread(_persist)
                logger.info("[pool] sentiment cache refreshed and persisted")
        except Exception as e:
            logger.warning("[pool] refresh_sentiment_cache failed: %s", e)
            # A02: On failure, try to restore from persisted file
            try:
                # round35 RC-C5: 读路径同款收敛（与写共用 _sentiment_cache_file 单点）
                _cache_file = _sentiment_cache_file()

                def _read_persisted():
                    if not os.path.exists(_cache_file):
                        return None
                    with open(_cache_file, "r", encoding="utf-8") as f:
                        return json.load(f)

                cached = await asyncio.to_thread(_read_persisted)
                if isinstance(cached, dict) and "sentiment" in cached:
                        self._sentiment_cache = cached["sentiment"]
                        self._sentiment_cache_ts = cached.get("ts", 0)
                        logger.info("[pool] restored sentiment from persisted cache file")
            except Exception as restore_e:
                logger.warning("[pool] failed to restore sentiment from cache file: %s", restore_e)


    def get_market_sentiment(self) -> dict:
        """获取市场情绪，120s 缓存。"""
        now = time.time()
        if self._sentiment_cache and (now - self._sentiment_cache_ts) < self.SENTIMENT_TTL:
            return self._sentiment_cache
        try:
            # Can't directly await here — cache miss just returns default
            pass
        except Exception:
            pass
        return self._sentiment_cache or {"sentiment_index": 50, "sentiment_label": "中性"}
