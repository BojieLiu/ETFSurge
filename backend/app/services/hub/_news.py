"""News bucket mixin — split from market_data_hub (Batch 3)."""

import logging
import math
import threading
import time

from app.services.hub._common import _rule_news_summary

logger = logging.getLogger(__name__)

class NewsMixin:
    _news_cache: list[dict] | None = None


    _news_buckets: dict | None = None


    _news_cache_ts: float = 0


    NEWS_TTL = 120


    def get_news(self) -> list[dict]:
        """获取缓存新闻（合并视图），120s TTL。"""
        now = time.time()
        if self._news_cache is not None and (now - self._news_cache_ts) < self.NEWS_TTL:
            return self._news_cache
        return []


    def _news_bucket(self, key: str) -> list[dict]:
        """按分类返回新闻桶；缓存过期或未初始化时懒刷新一次。

        R23 (round24): 懒刷新走 `_refresh_news_buckets_safe`——加锁避免并发刷新，
        且刷新失败/空桶时回退上次非空桶，杜绝高负载下 headlines/macro/global
        瞬态返 0。
        """
        now = time.time()
        if self._news_buckets is None or (now - self._news_cache_ts) > self.NEWS_TTL:
            self._refresh_news_buckets_safe()
        return (self._news_buckets or {}).get(key, [])


    def get_news_headlines(self) -> list[dict]:
        """财联社头条（分类缓存）。"""
        return self._news_bucket("headlines")


    async def enrich_news_summaries(self, cap: int = 6) -> int:
        """Z18/R17 (round24): 为重要新闻生成 AI 摘要并写回缓存。

        Z18: level>=4 或 stars>=4 的重要新闻才生成；LLM 失败静默保留 None；
        改的是缓存内 dict 引用，write-back 对 get_news_* 立即可见。
        R17 (round24): 覆盖三桶（headlines/macro/global），不再仅 headlines。
        round25 R31: 旧实现三桶合并后按重要性取前 cap 条 → headlines 恒占满
        （macro/global 0 摘要，R17 验收未达）——改为**分桶配额**：
        headlines=ceil(cap*0.5)、macro=ceil(cap*0.33)、global=剩余
        （cap=6 → 3/2/1），保证三桶均有摘要覆盖。
        """
        try:
            from ...analysis.llm import generate_news_summary
        except Exception:
            return 0
        # R31: 分桶配额——headlines 最多一半，macro/global 保底
        _head_q = max(1, math.ceil(cap * 0.5))
        _macro_q = max(1, math.ceil(cap * 0.33)) if cap >= 3 else 0
        _global_q = max(0, cap - _head_q - _macro_q)
        quotas = {"headlines": _head_q, "macro": _macro_q, "global": _global_q}

        enriched = 0
        seen_ids: set = set()
        for bucket in ("headlines", "macro", "global"):
            q = quotas.get(bucket, 0)
            if q <= 0:
                continue
            bucket_count = 0
            for n in self._news_bucket(bucket):
                if bucket_count >= q:
                    break
                # R65 (round28): 仅 LLM 来源跳过——rule 兜底摘要下轮继续重试 LLM
                # （配额空窗后补跑真摘要）；旧实现 `if n.get("ai_summary")` 把 rule
                # 摘要当已生成，永不回填 LLM。
                if n.get("ai_summary") and n.get("ai_summary_source") == "llm":
                    continue
                # F28 (round23 P0-A): 按 int 重要性判定（level>=4 或 stars>=4 → 重要）
                if (int(n.get("stars", 0) or 0) >= 4 or int(n.get("level", 0) or 0) >= 4):
                    nid = n.get("id") or n.get("title")
                    if nid in seen_ids:
                        continue
                    seen_ids.add(nid)
                    try:
                        summary = await generate_news_summary(n.get("title", ""), n.get("content", ""))
                        if summary:
                            n["ai_summary"] = summary
                            n["ai_summary_source"] = "llm"
                            enriched += 1
                            bucket_count += 1
                            continue
                    except Exception:
                        pass
                    # R65 (round28): LLM 失败/配额空窗 → 规则摘要兜底（非 null）。
                    # 旧实现 except 后直接 continue → 重要条目 ai_summary 恒 null
                    # （LLM 配额门禁让位主链路 + 无回填，round28 §6 R65）。
                    # 兜底标注 ai_summary_source="rule"，前端可区分「LLM 生成/规则截取」；
                    # 下一轮 enrich 仍会重试 LLM（仅 rule 来源允许覆盖，见上方 continue 条件）。
                    _rule = _rule_news_summary(n)
                    if _rule:
                        n["ai_summary"] = _rule
                        n["ai_summary_source"] = "rule"
                        enriched += 1
                        bucket_count += 1
            logger.debug("[hub] enrich_news_summaries bucket=%s quota=%d done=%d",
                         bucket, q, bucket_count)
        # R90 (round30): 配额外 level≥3 高重要性条目 rule 兜底全量覆盖——分桶配额
        # （cap=6 → macro=2/global=1）使配额外条目 ai_summary 恒 null（round30 §6
        # 实证 macro/global 高重要性条目摘要缺口）。本 pass 对 level>=3 且 ai_summary
        # 为 null 的条目直接填 rule 摘要（非 LLM，来源标注 rule；下轮 LLM 恢复仍重试）。
        for bucket in ("headlines", "macro", "global"):
            for n in self._news_bucket(bucket):
                if n.get("ai_summary"):
                    continue
                if int(n.get("level", 0) or 0) < 3:
                    continue
                _rule = _rule_news_summary(n)
                if _rule:
                    n["ai_summary"] = _rule
                    n["ai_summary_source"] = "rule"
                    enriched += 1
        return enriched


    def get_news_macro(self) -> list[dict]:
        """宏观政策新闻（分类缓存）。"""
        return self._news_bucket("macro")


    def get_news_global(self) -> list[dict]:
        """国际宏观新闻（分类缓存）。"""
        return self._news_bucket("global")


    def get_news_stock(self, symbol: str) -> list[dict]:
        """个股新闻（实时取数，无缓存）。"""
        try:
            from ...fetchers.news_fetcher import fetch_stock_news
            return fetch_stock_news(symbol) or []
        except Exception as e:
            logger.warning("[hub] get_news_stock(%s) failed: %s", symbol, e)
            return []


    def refresh_news(self) -> None:
        """同步刷新新闻分类缓存（headlines/macro/global 分别入桶）。

        R23 (round24): 委托 `_refresh_news_buckets_safe`——加锁 + 失败/空桶回退上次非空。
        """
        self._refresh_news_buckets_safe()


    def _refresh_news_buckets_safe(self) -> None:
        """R23 (round24): 安全刷新新闻桶。

        - 加锁：避免懒刷新与后台任务并发刷新互相踩踏（高负载下瞬态返 0 的根因之一）。
        - 回退：单个桶抓取失败/空（数据源冷却）时保留上次非空桶，而非整体置空导致
          该分类瞬态返 0 条。
        - 失败时：若历史上无任何桶，则保留上次（可能为空的）桶并刷新时间戳，
          避免立即重试风暴。
        """

        lock = getattr(self, "_news_refresh_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._news_refresh_lock = lock
        # 非阻塞抢锁：抢不到说明别的协程/任务正在刷新，直接复用当前桶（可能略旧但不为空）
        if not lock.acquire(blocking=False):
            return
        try:
            prev = self._news_buckets or {}
            try:
                from ...fetchers.news_fetcher import (
                    fetch_global_news,
                    fetch_macro_news,
                    fetch_news_headlines,
                )
                headlines = fetch_news_headlines() or []
                macro = fetch_macro_news() or []
                global_news = fetch_global_news() or []
                # R23: 空桶回退上次非空，避免数据源冷却时瞬态 0 条
                merged = {
                    "headlines": headlines or prev.get("headlines", []),
                    "macro": macro or prev.get("macro", []),
                    "global": global_news or prev.get("global", []),
                }
                self._news_buckets = merged
                self._news_cache = merged["headlines"] + merged["macro"] + merged["global"]
                self._news_cache_ts = time.time()
                logger.info(
                    "[hub] refreshed news buckets h=%d m=%d g=%d (fallback h=%d m=%d g=%d)",
                    len(merged["headlines"]), len(merged["macro"]), len(merged["global"]),
                    len(prev.get("headlines", [])), len(prev.get("macro", [])),
                    len(prev.get("global", [])),
                )
            except Exception as e:
                logger.exception("[hub] refresh_news failed: %s", e)
                # 失败时保留上次非空桶，避免整体置空
                if self._news_buckets is None:
                    self._news_buckets = prev
                self._news_cache_ts = time.time()
        finally:
            lock.release()
