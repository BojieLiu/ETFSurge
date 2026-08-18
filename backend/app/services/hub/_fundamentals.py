"""Fundamentals / stock-rank mixin — split from market_data_hub (Batch 3)."""

import logging

from app.fetchers import sector_fetcher
from app.services.hub._common import _parse_concept_tags

logger = logging.getLogger(__name__)

class FundamentalsMixin:
    def get_fundamentals(self, symbol: str) -> dict:
        """基本面数据（Tushare）。"""
        try:
            from ...fetchers.fundamentals_fetcher import fetch_fundamentals
            return fetch_fundamentals(symbol) or {}
        except Exception as e:
            logger.warning("[hub] get_fundamentals(%s) failed: %s", symbol, e)
            return {}


    def get_fund_nav(self, symbol: str):
        """基金净值。"""
        try:
            from ...fetchers.china_market import fetch_fund_nav
            return fetch_fund_nav(symbol)
        except Exception as e:
            logger.warning("[hub] get_fund_nav(%s) failed: %s", symbol, e)
            return None


    def get_stock_hot_rank(self, limit: int = 50, market: str = "A") -> list[dict]:
        """热门个股排行（Z25: 补全 volume/turnover/sector）。

        F16→P2-R (round10 §5.6): market=HK 走港股成交额榜；market=US 走东财
        spot_em 成交额降序 TOP N（美股无涨跌停，成交额榜即"热度"）。
        """
        if market and market.upper() == "HK":
            from ...fetchers.hk_hot_fetcher import get_hk_hot_stocks
            return get_hk_hot_stocks(limit)
        if market and market.upper() == "US":
            try:
                from ...fetchers.china_market import _fetch_us_spot
                us_rows = _fetch_us_spot() or []
                # 按成交额降序（amount 缺失的排到尾），取 TOP N
                ranked = sorted(
                    [r for r in us_rows if r.get("amount") is not None],
                    key=lambda r: -(r.get("amount") or 0),
                )
                head = ranked[:limit]
                if not head:
                    head = us_rows[:limit]
                return [
                    {
                        "symbol": r.get("symbol"),
                        "name": r.get("name"),
                        "price": r.get("price"),
                        "change_pct": r.get("change_pct"),
                        "amount": r.get("amount"),
                        "mcap": r.get("mcap"),
                        "market": "US",
                    }
                    for r in head
                ]
            except Exception as e:
                logger.warning("[hub] get_stock_hot_rank US failed: %s", e)
                return []
        try:
            from ...fetchers.sector_fetcher import fetch_stock_hot_rank
            rows = fetch_stock_hot_rank(limit) or []
        except Exception as e:
            logger.warning("[hub] get_stock_hot_rank failed: %s", e)
            return []
        if not rows:
            return []
        try:
            return self._enrich_stock_hot_rank(rows)
        except Exception as e:
            logger.warning("[hub] stock_hot_rank enrich failed: %s", e)
            return rows


    def _enrich_stock_hot_rank(self, rows: list[dict]) -> list[dict]:
        """Z25: 热门个股补全 volume/turnover（批量行情）+ sector（行业映射）。

        任一补全步骤失败不阻塞主流程，缺失字段留默认值。
        """
        codes = [str(r.get("code") or r.get("symbol") or "").strip() for r in rows]
        codes = [c for c in codes if c]
        if not codes:
            return rows

        # 1) volume/turnover via batch realtime
        batch_map: dict[str, dict] = {}
        try:
            from ...fetchers.china_market import fetch_a_stock_batch
            batch = fetch_a_stock_batch(codes) or []
            for b in batch:
                sym = str(b.get("symbol", "")).strip()
                if sym:
                    batch_map[sym] = b
        except Exception as e:
            logger.warning("[hub] stock_hot_rank batch realtime failed: %s", e)

        # 2) sector via industry map
        sector_map: dict[str, str] = {}
        try:
            from ...fetchers.sector_fetcher import get_stock_industry_map
            sector_map = get_stock_industry_map(codes) or {}
        except Exception as e:
            logger.warning("[hub] stock_hot_rank industry map failed: %s", e)

        out: list[dict] = []
        for rank, row in enumerate(rows, start=1):
            code = str(row.get("code") or row.get("symbol") or "").strip()
            b = batch_map.get(code) or {}
            item = dict(row)
            item["rank"] = rank
            item["symbol"] = code
            item["volume"] = b.get("volume", item.get("volume", 0))
            item["turnover"] = b.get("turnover", item.get("turnover", 0))
            if b:
                if b.get("price") is not None:
                    item["price"] = b["price"]
                if b.get("change_pct") is not None:
                    item["change_pct"] = b["change_pct"]
                if b.get("change_amount") is not None:
                    item["change_amount"] = b["change_amount"]
            # 批量行情自带 sector 优先，其次行业映射，最后空串
            item["sector"] = b.get("sector") or sector_map.get(code) or ""
            item["asset_type"] = "A"
            # F2-6 步骤A: tag 字符串解析为 concept_tags 数组（前端 chip 展示）
            item["concept_tags"] = _parse_concept_tags(row.get("tag"))
            out.append(item)
        return out


    def get_research_reports(self, symbol: str) -> list[dict]:
        """个股研报。"""
        try:
            from ...fetchers.news_fetcher import fetch_research_reports
            return fetch_research_reports(symbol) or []
        except Exception as e:
            logger.warning("[hub] get_research_reports(%s) failed: %s", symbol, e)
            return []


    def get_all_stocks(self) -> list[dict]:
        """全市场股票列表。"""
        try:
            from ...fetchers.sector_fetcher import fetch_all_stocks
            return fetch_all_stocks() or []
        except Exception as e:
            logger.warning("[hub] get_all_stocks failed: %s", e)
            return []


    def get_a_stock_batch(self, symbols: list[str]) -> list[dict]:
        """A 股批量实时行情。"""
        try:
            from ...fetchers.china_market import fetch_a_stock_batch
            return fetch_a_stock_batch(symbols) or []
        except Exception as e:
            logger.warning("[hub] get_a_stock_batch failed: %s", e)
            return []
