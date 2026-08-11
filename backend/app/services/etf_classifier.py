"""
ETFClassifier: infer Shenwan industry classification and concept board
membership for ETFs based on name keywords and tracked_index metadata.

Used by MarketDataHub._classify_5layer() to enrich classification decisions
beyond simple name-keyword matching.

Data sources:
  - ETF name (always available)
  - ETF tracked_index (from akshare fund_etf_fund_info_em)
  - ETF top 10 holdings (future enhancement: overlap with board constituents)

Levels of inference (S2 scope):
  1. Tracked index name match (highest confidence)
  2. ETF name keyword match (medium confidence)
  3. Unknown (lowest confidence)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Keyword → industry/concept mapping tables
# Order matters: first match wins (more specific → more general)

_NAME_RULES: list[tuple[str, str, list[str]]] = [
    # (name_keyword, industry, concepts)
    # --- Core: Broad-based indices ---
    ("沪深300", "宽基指数", ["沪深300", "大盘"]),
    ("中证A500", "宽基指数", ["中证A500", "A500"]),
    ("上证50", "宽基指数", ["上证50", "超大盘"]),
    ("上证180", "宽基指数", ["上证180"]),
    ("中证800", "宽基指数", ["中证800"]),
    ("中证500", "宽基指数", ["中证500", "中盘"]),
    ("创业板", "宽基指数", ["创业板", "成长"]),
    ("科创50", "宽基指数", ["科创50", "科创板"]),
    ("科创100", "宽基指数", ["科创100"]),
    ("深证100", "宽基指数", ["深证100"]),
    ("MSCI A50", "宽基指数", ["MSCI", "A50"]),
    ("A50", "宽基指数", ["A50"]),
    # --- Satellite: Technology ---
    ("半导体", "电子", ["半导体", "芯片", "集成电路"]),
    ("芯片", "电子", ["芯片", "半导体"]),
    ("集成电路", "电子", ["集成电路", "芯片"]),
    ("人工智能", "计算机", ["人工智能", "AI"]),
    ("AI", "计算机", ["AI", "人工智能"]),
    ("大数据", "计算机", ["大数据"]),
    ("云计算", "计算机", ["云计算"]),
    ("软件", "计算机", ["软件", "信创"]),
    ("信创", "计算机", ["信创", "国产软件"]),
    ("计算机", "计算机", ["计算机"]),
    ("电子", "电子", ["电子"]),
    ("通信", "通信", ["通信", "5G"]),
    ("5G", "通信", ["5G", "通信"]),
    ("物联网", "通信", ["物联网"]),
    # --- Satellite: New Energy ---
    # round14 P2-U: 新能源/碳中和类 industry 改「新能源」——旧「电力设备」概念粗映射
    #（碳中和/科创新能源指数成分含电力设备+环保/公用事业/汽车）；精确词前置防子串误匹配
    ("科创新能源", "新能源", ["新能源", "电力设备", "光伏", "锂电池"]),
    ("新能源", "新能源", ["新能源", "锂电池", "光伏"]),
    ("碳中和", "新能源", ["碳中和", "环保", "电力设备"]),
    ("光伏", "电力设备", ["光伏", "太阳能"]),
    ("锂电池", "电力设备", ["锂电池", "新能源车"]),
    ("储能", "电力设备", ["储能"]),
    # --- Satellite: Medical ---
    ("医药", "医药生物", ["医药", "医疗", "生物医药"]),
    ("医疗", "医药生物", ["医疗", "医疗器械"]),
    ("生物医药", "医药生物", ["生物医药", "创新药"]),
    ("创新药", "医药生物", ["创新药"]),
    # --- Satellite: Military ---
    ("军工", "国防军工", ["军工", "国防", "航天"]),
    ("国防", "国防军工", ["国防", "军工"]),
    ("航天", "国防军工", ["航天", "军工"]),
    # --- Satellite: Finance ---
    ("证券", "非银金融", ["证券", "券商"]),
    ("券商", "非银金融", ["券商", "证券"]),
    ("保险", "非银金融", ["保险"]),
    ("银行", "银行", ["银行"]),
    ("金融", "非银金融", ["金融"]),
    # --- Satellite: Consumption ---
    # O23 (round7 §7 P23): 「消费电子」精确规则前置——宽泛「消费」子串匹配会把
    # 消费电子/消费50/消费龙头等误归食品饮料（_match 是 keyword in text 子串匹配）
    ("消费电子", "电子", ["消费电子", "电子"]),
    ("消费", "食品饮料", ["消费", "食品饮料"]),
    ("食品饮料", "食品饮料", ["食品饮料"]),
    ("酒", "食品饮料", ["白酒", "酒"]),
    ("白酒", "食品饮料", ["白酒"]),
    ("家电", "家用电器", ["家电"]),
    ("汽车", "汽车", ["汽车", "新能源汽车"]),
    # --- Satellite: Materials ---
    ("有色", "有色金属", ["有色", "金属"]),
    ("钢铁", "钢铁", ["钢铁"]),
    ("化工", "化工", ["化工"]),
    ("建材", "建筑材料", ["建材"]),
    # --- Satellite: Industrials ---
    ("机械", "机械设备", ["机械", "高端制造"]),
    ("高端制造", "机械设备", ["高端制造"]),
    ("基建", "建筑装饰", ["基建", "建筑"]),
    ("房地产", "房地产", ["房地产"]),
    ("地产", "房地产", ["地产"]),
    ("电力", "公用事业", ["电力"]),
    ("交通运输", "交通运输", ["交通运输", "物流"]),
    ("物流", "交通运输", ["物流"]),
    # --- Satellite: Media ---
    ("传媒", "传媒", ["传媒", "游戏"]),
    ("游戏", "传媒", ["游戏"]),
    # --- Defense ---
    ("黄金", "商品", ["黄金", "贵金属"]),
    ("白银", "商品", ["白银", "贵金属"]),
    ("原油", "商品", ["原油", "石油"]),
    ("有色ETF", "商品", ["有色", "商品"]),
    ("商品", "商品", ["商品"]),
    # --- Defense: Fixed Income ---
    ("国债", "固收", ["国债", "利率债"]),
    ("国开", "固收", ["国开债"]),
    ("地方债", "固收", ["地方债"]),
    ("城投债", "固收", ["城投债"]),
    ("可转债", "固收", ["可转债"]),
    ("信用债", "固收", ["信用债"]),
    ("短融", "固收", ["短融"]),
    ("货币", "固收", ["货币基金"]),
    ("同业存单", "固收", ["同业存单"]),
    # --- Defense: Cross-border ---
    ("标普500", "跨境", ["标普500", "美股"]),
    ("纳斯达克", "跨境", ["纳斯达克", "美股科技"]),
    ("纳指", "跨境", ["纳指", "美股科技"]),
    ("道琼斯", "跨境", ["道琼斯", "美股"]),
    ("恒生", "跨境", ["恒生", "港股"]),
    ("H股", "跨境", ["H股", "港股"]),
    ("中概", "跨境", ["中概", "海外中国"]),
    ("日经", "跨境", ["日经", "日本"]),
    ("德国", "跨境", ["德国", "欧洲"]),
    ("法国", "跨境", ["法国", "欧洲"]),
    ("欧洲", "跨境", ["欧洲"]),
    ("全球", "跨境", ["全球"]),
    ("美元", "跨境", ["美元"]),
]

# Tracked index patterns (checked first, before name)
_INDEX_RULES: list[tuple[str, str, list[str]]] = [
    ("半导体芯片", "电子", ["半导体", "芯片"]),
    ("半导体", "电子", ["半导体"]),
    ("芯片", "电子", ["芯片"]),
    ("人工智能", "计算机", ["人工智能"]),
    # round14 P2-U: 同步索引规则（tracked_index 缺失走 name 路径的 589960 等 case）
    ("新能源", "新能源", ["新能源"]),
    ("医药卫生", "医药生物", ["医药"]),
    ("军工", "国防军工", ["军工"]),
    ("证券", "非银金融", ["证券"]),
    # O23 (round7 §7 P23): 「消费电子」精确规则前置（tracked_index 优先路径——
    # 562950 的 tracked_index="中证消费电子" 曾命中宽泛「消费」→ 误归食品饮料）
    ("消费电子", "电子", ["消费电子"]),
    ("消费", "食品饮料", ["消费"]),
    ("有色金属", "有色金属", ["有色"]),
    ("中证1000", "宽基指数", ["中证1000"]),
    ("中证500", "宽基指数", ["中证500"]),
    ("沪深300", "宽基指数", ["沪深300"]),
    ("创业板", "宽基指数", ["创业板"]),
    ("科创50", "宽基指数", ["科创50"]),
    ("纳斯达克", "跨境", ["纳斯达克", "美股科技"]),
]


def _match(text: str, rules: list[tuple[str, str, list[str]]]) -> tuple[str, str, list[str]] | None:
    """Return the first matching rule (keyword, industry, concepts) or None."""
    if not text:
        return None
    for keyword, industry, concepts in rules:
        if keyword in text:
            return keyword, industry, concepts
    return None


class ETFClassifier:
    """ETF 行业/概念分类器。"""

    def _classify_by_name(self, name: str, tracked_index: str) -> dict[str, Any]:
        """Classify a single ETF by name and tracked_index.

        Returns:
            {"industry": str, "concepts": list[str], "confidence": float}
        """
        # Check tracked_index first (higher confidence)
        match = _match(tracked_index, _INDEX_RULES)
        if match:
            keyword, industry, concepts = match
            return {
                "industry": industry,
                "concepts": concepts,
                "confidence": 0.85,
            }

        # Fallback to name matching
        match = _match(name, _NAME_RULES)
        if match:
            keyword, industry, concepts = match
            return {
                "industry": industry,
                "concepts": concepts,
                "confidence": 0.70,
            }

        # Unknown
        return {
            "industry": "unknown",
            "concepts": [],
            "confidence": 0.0,
        }

    def batch_classify(self, etfs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Classify multiple ETFs in batch.

        Args:
            etfs: List of dicts with keys "symbol", "name", "tracked_index"

        Returns:
            {symbol: {"industry": ..., "concepts": [...], "confidence": ...}}
        """
        results = {}
        for etf in etfs:
            symbol = etf.get("symbol", "")
            name = etf.get("name", "")
            tracked_index = etf.get("tracked_index", "") or etf.get("trackedIndex", "") or ""
            results[symbol] = self._classify_by_name(name, tracked_index)
        return results


# Global singleton
classifier = ETFClassifier()
