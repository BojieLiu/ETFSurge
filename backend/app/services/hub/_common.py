"""Shared module-level functions & constants — split from market_data_hub (Batch 3)."""

import ast
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.market_calendar import market_session

logger = logging.getLogger(__name__)

# Layer/pool constants live in the pure engine modules (single source of truth,
# dependency direction engine/ <- hub/ <- facade); re-exported here.
# ⚠️ round36：ALL_LAYERS/MANDATORY_CODES/_LAYER_WEIGHTS/_BASE_WEIGHTS 虽在本文件无
# 直接消费，但经 market_data_hub → hub/__init__ 门面链被跨模块消费——ruff F401 曾误删，
# noqa = 有意保留的 re-export 面。
from app.engine.composite_signal import _BASE_WEIGHTS, _LAYER_WEIGHTS  # noqa: E402, F401
from app.engine.pool_balancing import (  # noqa: E402, F401
    ALL_LAYERS,
    LAYER_CORE,
    LAYER_DEFENSE,
    LAYER_OPPORTUNISTIC,
    LAYER_RESEARCH,
    LAYER_SATELLITE,
    MANDATORY_CODES,
)

SECTOR_ETF_MAP: dict[str, dict] = {
    "半导体": {"symbol": "512480", "name": "半导体ETF", "layer": "satellite", "tracked_index": "半导体"},
    "芯片": {"symbol": "159995", "name": "芯片ETF", "layer": "satellite", "tracked_index": "芯片"},
    "人工智能": {"symbol": "515980", "name": "人工智能ETF", "layer": "satellite", "tracked_index": "人工智能"},
    "AI": {"symbol": "515980", "name": "人工智能ETF", "layer": "satellite", "tracked_index": "人工智能"},
    "5G": {"symbol": "515050", "name": "5G通信ETF", "layer": "satellite", "tracked_index": "5G"},
    "通信": {"symbol": "515880", "name": "通信ETF", "layer": "satellite", "tracked_index": "通信"},
    "云计算": {"symbol": "516630", "name": "云计算ETF", "layer": "satellite", "tracked_index": "云计算"},
    "大数据": {"symbol": "516630", "name": "大数据ETF", "layer": "satellite", "tracked_index": "大数据"},
    "机器人": {"symbol": "562500", "name": "机器人ETF", "layer": "satellite", "tracked_index": "机器人"},
    "新能源车": {"symbol": "515030", "name": "新能源车ETF", "layer": "satellite", "tracked_index": "新能源车"},
    "新能源": {"symbol": "516160", "name": "新能源ETF", "layer": "satellite", "tracked_index": "新能源"},
    "光伏": {"symbol": "515790", "name": "光伏ETF", "layer": "satellite", "tracked_index": "光伏"},
    "电池": {"symbol": "159755", "name": "电池ETF", "layer": "satellite", "tracked_index": "电池"},
    "军工": {"symbol": "512660", "name": "军工ETF", "layer": "satellite", "tracked_index": "军工"},
    "证券": {"symbol": "512880", "name": "证券ETF", "layer": "satellite", "tracked_index": "证券公司"},
    "券商": {"symbol": "512880", "name": "证券ETF", "layer": "satellite", "tracked_index": "证券公司"},
    "银行": {"symbol": "512800", "name": "银行ETF", "layer": "satellite", "tracked_index": "银行"},
    "保险": {"symbol": "512070", "name": "保险ETF", "layer": "satellite", "tracked_index": "保险"},
    "地产": {"symbol": "512200", "name": "地产ETF", "layer": "satellite", "tracked_index": "房地产"},
    "医药": {"symbol": "512010", "name": "医药ETF", "layer": "satellite", "tracked_index": "医药"},
    "创新药": {"symbol": "159992", "name": "创新药ETF", "layer": "satellite", "tracked_index": "创新药"},
    "中药": {"symbol": "560080", "name": "中药ETF", "layer": "satellite", "tracked_index": "中药"},
    "医疗器械": {"symbol": "159883", "name": "医疗器械ETF", "layer": "satellite", "tracked_index": "医疗器械"},
    "消费": {"symbol": "159928", "name": "消费ETF", "layer": "satellite", "tracked_index": "消费"},
    "白酒": {"symbol": "161725", "name": "白酒基金", "layer": "satellite", "tracked_index": "中证白酒"},
    "食品饮料": {"symbol": "515170", "name": "食品饮料ETF", "layer": "satellite", "tracked_index": "食品饮料"},
    "煤炭": {"symbol": "515220", "name": "煤炭ETF", "layer": "satellite", "tracked_index": "煤炭"},
    "有色": {"symbol": "159980", "name": "有色ETF", "layer": "satellite", "tracked_index": "有色金属"},
    "稀土": {"symbol": "516780", "name": "稀土ETF", "layer": "satellite", "tracked_index": "稀土"},
    "化工": {"symbol": "159870", "name": "化工ETF", "layer": "satellite", "tracked_index": "化工"},
    "钢铁": {"symbol": "515210", "name": "钢铁ETF", "layer": "satellite", "tracked_index": "钢铁"},
    "石油": {"symbol": "561760", "name": "石油ETF", "layer": "satellite", "tracked_index": "石油"},
    "电力": {"symbol": "561560", "name": "电力ETF", "layer": "satellite", "tracked_index": "电力"},
    "传媒": {"symbol": "512980", "name": "传媒ETF", "layer": "satellite", "tracked_index": "传媒"},
    "游戏": {"symbol": "159869", "name": "游戏ETF", "layer": "satellite", "tracked_index": "游戏"},
    "养殖": {"symbol": "159865", "name": "养殖ETF", "layer": "satellite", "tracked_index": "养殖"},
    "农业": {"symbol": "159825", "name": "农业ETF", "layer": "satellite", "tracked_index": "农业"},
    "软件": {"symbol": "159899", "name": "软件ETF", "layer": "satellite", "tracked_index": "软件"},
    "计算机": {"symbol": "159998", "name": "计算机ETF", "layer": "satellite", "tracked_index": "计算机"},
    "汽车": {"symbol": "516110", "name": "汽车ETF", "layer": "satellite", "tracked_index": "汽车"},
    "家电": {"symbol": "561120", "name": "家电ETF", "layer": "satellite", "tracked_index": "家电"},
    "港股通": {"symbol": "513180", "name": "恒生科技ETF", "layer": "satellite", "tracked_index": "恒生科技"},
    "恒生科技": {"symbol": "513180", "name": "恒生科技ETF", "layer": "satellite", "tracked_index": "恒生科技"},
    "恒生": {"symbol": "513660", "name": "恒生ETF", "layer": "satellite", "tracked_index": "恒生指数"},
    "红利": {"symbol": "510880", "name": "红利ETF", "layer": "satellite", "tracked_index": "红利"},
    "沪深300": {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "tracked_index": "沪深300"},
    "中证500": {"symbol": "510500", "name": "中证500ETF", "layer": "core", "tracked_index": "中证500"},
    "中证1000": {"symbol": "512100", "name": "中证1000ETF", "layer": "satellite", "tracked_index": "中证1000"},
    "创业板": {"symbol": "159915", "name": "创业板ETF", "layer": "core", "tracked_index": "创业板指"},
    "科创50": {"symbol": "588000", "name": "科创50ETF", "layer": "core", "tracked_index": "科创50"},
    "科创板": {"symbol": "588000", "name": "科创50ETF", "layer": "core", "tracked_index": "科创50"},
    "黄金": {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "tracked_index": "黄金"},
    "国债": {"symbol": "511010", "name": "国债ETF", "layer": "defense", "tracked_index": "国债"},
}


MAX_PER_LAYER = {
    LAYER_CORE: 8,
    LAYER_SATELLITE: 20,
    LAYER_DEFENSE: 10,
    LAYER_OPPORTUNISTIC: 8,
    LAYER_RESEARCH: 10,
}


def _snapshot_db_path() -> str:
    """快照 SQLite 文件路径（与 database.py 同源）。"""
    from ...config import settings
    return settings.database_url.replace("sqlite+aiosqlite:///", "")


def _snapshot_as_of_for(dt: datetime | None = None) -> str | None:
    """R26: 返回快照 as_of 时点；盘中返回 None（实时源，不写快照）。

    - after_hours (15:05-15:30): as_of=当日 15:00（盘中最后快照，盘后固定价格交易未结束）
    - post_market (≥15:30):      as_of=当日 15:30（含盘后成交量，完整当日数据）
    - open / pre_market / closed: None（盘中实时或无可写新数据）

    语义（round24 §12.1 R26）：盘后快照 as_of 用 15:30 而非 15:00——
    A股盘后固定价格交易 2026-07-06 起扩展到全市场，窗口 15:05-15:30 以收盘价
    逐笔撮合，成交量计入当日总量，故「完整当日数据」要等到 15:30。
    """
    if dt is None:
        dt = datetime.now()
    session = market_session(dt)
    if session == "after_hours":
        return dt.replace(hour=15, minute=0, second=0, microsecond=0).isoformat(sep="T")
    if session == "post_market":
        return dt.replace(hour=15, minute=30, second=0, microsecond=0).isoformat(sep="T")
    return None


def _persist_snapshot_sync(kind: str, payload: Any, as_of: str) -> None:
    """落盘快照（同步 raw sqlite）。同一 kind 仅保留最近 2 条。"""
    try:
        db_path = _snapshot_db_path()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute(
                "INSERT INTO market_snapshots (kind, payload, as_of, created_at) "
                "VALUES (?, ?, ?, ?)",
                (kind, payload_json, as_of, datetime.utcnow().isoformat()),
            )
            # 仅保留最近 2 条同 kind（幂等刷新不会无限增长）
            conn.execute(
                "DELETE FROM market_snapshots WHERE kind=? AND id NOT IN "
                "(SELECT id FROM market_snapshots WHERE kind=? ORDER BY id DESC LIMIT 2)",
                (kind, kind),
            )
    except Exception as e:
        logger.warning("[hub] _persist_snapshot_sync(%s) failed: %s", kind, e)


def _load_latest_snapshot_sync(kind: str) -> dict | None:
    """读最近一条同 kind 快照 payload（同步 raw sqlite）。失败返回 None。"""
    try:
        db_path = _snapshot_db_path()
        with sqlite3.connect(db_path, timeout=10) as conn:
            row = conn.execute(
                "SELECT payload FROM market_snapshots WHERE kind=? "
                "ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
        if row:
            return json.loads(row[0])
    except Exception as e:
        logger.warning("[hub] _load_latest_snapshot_sync(%s) failed: %s", kind, e)
    return None


def _parse_stock_list(s: Any) -> list:
    """安全解析 stock_list 字符串为数组（F2-6 步骤A；§9.8.3 伪代码）。

    数据源以字符串化列表存于行内，前端无解析层 → 在此统一转数组。
    非法字符串返回 []，绝不 eval。
    """
    if isinstance(s, list):
        return s
    if not s:
        return []
    try:
        parsed = ast.literal_eval(s)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _parse_concept_tags(tag: Any) -> list[str]:
    """解析热门个股 tag 为 concept_tags 数组（F2-6 步骤A）。

    O9 (round8 §7 P9-新): 数据源 tag 是嵌套 dict {"concept_tag": [...],
    "popularity_tag": "..."}——旧实现对 dict 输入直接返回 [] → concept_tags
    50/50 全空。统一平铺：dict 取 concept_tag 键，list 元素若是 dict 取内层
    concept_tag，str dict 字面量走 ast.literal_eval。
    """
    def _flatten(value) -> list[str]:
        out: list[str] = []
        if isinstance(value, dict):
            # 嵌套 dict：优先取 concept_tag 键（可再嵌套 list）
            inner = value.get("concept_tag") or value.get("tags") or []
            out.extend(_flatten(inner))
        elif isinstance(value, list):
            for t in value:
                out.extend(_flatten(t))
        elif isinstance(value, str):
            s = value.strip()
            if s:
                out.append(s)
        return out

    if isinstance(tag, str):
        # 字符串可能是 dict/list 字面量（历史缓存格式）
        try:
            parsed = ast.literal_eval(tag)
            if isinstance(parsed, (dict, list)):
                return _flatten(parsed)[:6]
        except Exception:
            pass
        # 朴素逗号分隔兜底
        if "," in tag:
            return [t.strip() for t in tag.split(",") if t.strip()][:6]
        # O9: 无法解析的字符串不产出 tag（坏 tag 不落 concept_tags，保持旧行为）
        return []
    return _flatten(tag)[:6]


def _normalize_hot_plate(r: dict) -> dict:
    """热点板块行字段归一化（F2-6 步骤A，保持前端契约稳定）。

    secu_name→name、up_reason→reason、plate_stock_up_num→stock_count、
    stock_list(字符串)→lead_stocks(数组)。
    """
    item = dict(r)
    if "secu_name" in item and "name" not in item:
        item["name"] = item.pop("secu_name")
    if "up_reason" in item and "reason" not in item:
        item["reason"] = item.pop("up_reason")
    if "plate_stock_up_num" in item and "stock_count" not in item:
        item["stock_count"] = item.pop("plate_stock_up_num")
    if "stock_list" in item:
        item["lead_stocks"] = _parse_stock_list(item.pop("stock_list"))
    return item


def _strong_sector_etfs(sector_momentum, existing_symbols=None, top_n=8, min_change_pct=0.0):
    """round24 R1: 强板块动量 TopN → 代表性 ETF 候选（注入 flat/候选池）。

    纯函数，无 I/O。输入 sector_momentum 为 compute_sector_momentum 的输出
    （[{sector, sector_code, type, change_pct, ...}]）；按 change_pct 降序取 TopN，
    经 SECTOR_ETF_MAP 映射其代表 ETF，跳过已存在的标的，返回需追加进 flat 的候选 dict
    （hot_sector=True，composite_score 保底值防被截断挤出）。

    验收：强板块（change_pct 居前）的代表 ETF 进入候选池；熔断/无板块动量时返回 []。
    """
    if not sector_momentum:
        return []
    ranked = sorted(
        sector_momentum,
        key=lambda x: (x.get("change_pct", 0) or 0),
        reverse=True,
    )
    out = []
    seen = set(existing_symbols or set())
    for sec in ranked[:top_n]:
        name = (sec.get("sector") or "").strip()
        if (sec.get("change_pct", 0) or 0) < min_change_pct:
            continue
        etf = SECTOR_ETF_MAP.get(name)
        if not etf:
            continue
        sym = etf["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        out.append({
            "symbol": sym,
            "name": etf["name"],
            "amount": 0,
            "fund_scale": 0,
            "fund_shares": 0,
            "layer": etf.get("layer", "satellite"),
            "tracked_index": etf.get("tracked_index", ""),
            "hot_sector": True,
            "composite_score": 0.6,  # 保底值：确保强板块不被后续截断挤出候选池
            "sector_source": name,
        })
    return out


def _rule_news_summary(item: dict) -> str | None:
    """R65 (round28): 规则摘要兜底——LLM 失败/配额空窗时保证重要条目 ai_summary 非 null。

    取 content 首句（≤80 字截断）；无 content 回落标题。确定性纯函数，无 IO，
    供 enrich_news_summaries 在 LLM 调用失败后降级使用（来源标注 ai_summary_source="rule"）。
    """
    content = str(item.get("content") or "").strip()
    if content:
        import re as _re
        _first = _re.split(r"[。！？!?\n]", content)[0].strip()
        if len(_first) > 80:
            _first = _first[:80] + "…"
        if _first:
            return _first
    title = str(item.get("title") or "").strip()
    if title:
        return title
    return None


@dataclass
class PoolDiff:
    """差异报告：跟踪两次 refresh 之间的变化。"""

    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    version: int = 0
    timestamp: str = ""
