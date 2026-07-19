"""
全市场 ETF 数据采集与筛选引擎 (Full-Market ETF Scanner)

数据流:
  1. fetch_all_etfs_base(): 全量 ETF 基础数据 (带 TTL 缓存 60s)
  2. filter_etfs(): 硬性过滤
  3. classify_etf(): 三层自动分类
  4. layer_ranking(): 层内排序取 TOP N

数据来源: akshare fund_etf_spot_em (一次调用, ~5s)
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.async_utils import run_in_thread
from ..services.cache_service import sync_memory_cache

logger = logging.getLogger(__name__)

# ── 核心层关键词 ─────────────────────────────────────────────
CORE_KEYWORDS = [
    "沪深300", "中证A500",
    "上证50", "上证180", "中证800",
    "深证100", "深证50",
    "MSCI", "A50", "A100",
]


# ── 防御层关键词 ─────────────────────────────────────────────
DEFENSE_KEYWORDS = [
    "黄金", "白银", "原油", "商品",
    "国债", "国开", "进出口", "地方债", "城投债", "可转债", "信用债",
    "标普500", "纳斯达克", "纳指", "道琼斯",
    "恒生", "H股", "中概", "恒生科技",
    "日经", "德国", "法国", "欧洲",
    "全球", "美元", "短融", "货币", "同业存单",
]

# ── 过滤阈值 ─────────────────────────────────────────────────
MIN_FUND_SCALE = 1.0          # 亿元
MIN_AVG_AMOUNT = 10_000_000   # 元 (1000万)

# 强制保留的标的（即使不在 TOP N）
CORE_REQUIRED = ["510300", "560600"]   # 沪深300ETF, 中证A500ETF
DEFENSE_REQUIRED = ["518880", "511090"]  # 黄金ETF, 30年国债ETF


def fetch_all_etfs_base() -> list[dict[str, Any]]:
    """一次调用获取全量 ETF 基础数据。

    数据源: fund_etf_spot_em (东方财富)
    返回: 每只 ETF 包含 代码/名称/最新价/涨跌幅/成交额/换手率/PE/PB/基金规模
    """
    from ..core.ttl import CACHE_TTL
    cached = sync_memory_cache.get("all_etfs")
    if cached is not None:
        logger.debug("[etf_scanner] cache hit for all_etfs")
        return cached

    try:
        from ..utils.decode import decode_df as _decode_df

        def _p():
            import akshare as ak
            return ak.fund_etf_spot_em()
        df = run_in_thread(_p, timeout=8)
        if df is None or df.empty:
            logger.warning("[etf_scanner] fund_etf_spot_em returned empty")
            return []

        _decode_df(df)
        result = df.to_dict(orient="records")
        sync_memory_cache.set("all_etfs", result, CACHE_TTL.get("etf_scanner", 120))
        return result
    except Exception as e:
        logger.warning("[etf_scanner] fund_etf_spot_em failed: %s", e)
        stale = sync_memory_cache.get("all_etfs")
        if stale is not None:
            logger.info("[etf_scanner] using stale cache")
            return stale
        return []


def _normalize_columns(df: pd.DataFrame) -> None:
    """P4-a: 列名归一化——将 akshare 乱码列名映射为标准中文名。"""
    if df.empty:
        return
    STANDARD_KEYS = ["代码", "名称", "最新价", "涨跌幅", "成交额", "成交量", "换手率",
                      "最高价", "最低价", "今开", "昨收", "基金规模", "市盈率", "市净率"]
    renamed = {}
    for col in df.columns:
        col_s = str(col)
        if col_s in STANDARD_KEYS:
            continue
        for sk in STANDARD_KEYS:
            try:
                if col_s == sk.encode("utf-8").decode("latin1", errors="replace"):
                    renamed[col_s] = sk
                    break
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    if renamed:
        df.rename(columns=renamed, inplace=True)


def _get_col(row: dict, *names: str, default=0.0):
    """从行数据中取第一个存在的列名。"""
    for n in names:
        v = row.get(n)
        if v is not None and v != "":
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return default


def filter_etfs(raw_list: list[dict] | Any) -> list[dict[str, Any]]:
    """硬性过滤: 基金规模>1亿, 成交额>1000万, 非债券货币 ETF。

    输入可以是 DataFrame 或 list[dict]。
    """
    # 统一为 list[dict]
    if hasattr(raw_list, "to_dict"):
        _normalize_columns(raw_list)
        raw_list = raw_list.to_dict(orient="records")

    CODE_NAMES = ["代码", "symbol", "code", "证券代码"]
    NAME_NAMES = ["名称", "name", "证券简称"]
    AMOUNT_NAMES = ["成交额", "amount", "成交金额", "成交额(元)"]
    SCALE_NAMES = ["流通市值", "总市值", "fund_scale", "规模", "最新基金规模"]

    results = []
    seen = set()
    for row in raw_list:
        code = ""
        for k in CODE_NAMES:
            v = row.get(k)
            if v is not None and str(v).strip():
                code = str(v).strip()
                break
        if not code or code in seen:
            continue
        seen.add(code)

        name = ""
        for k in NAME_NAMES:
            v = row.get(k)
            if v is not None and str(v).strip():
                name = str(v).strip()
                break

        # 过滤: 排除纯债/货币 ETF
        name_lower = name.lower()
        skip_keywords = ["国债", "国开", "城投债", "可转债", "信用债", "货币", "短融", "同业存单"]
        if any(kw in name for kw in skip_keywords):
            # 只排除"纯"债/货币，保留黄金/跨境/商品等防御型
            # 国债/国开等纯债类排除（由债券模块管理）
            # 但黄金ETF、跨境ETF不排除
            is_pure_bond = any(kw in name for kw in ["国债ETF", "国开债", "城投债", "信用债", "可转债"])
            is_money_market = any(kw in name for kw in ["货币ETF", "短融ETF", "同业存单"])
            if is_pure_bond or is_money_market:
                continue

        amount = _get_col(row, *AMOUNT_NAMES)
        if amount < MIN_AVG_AMOUNT:
            continue

        scale = _get_col(row, *SCALE_NAMES)
        if scale < MIN_FUND_SCALE:
            continue

        results.append({
            "symbol": code,
            "name": name,
            "price": _get_col(row, "最新价", "price"),
            "change_pct": _get_col(row, "涨跌幅", "change_pct"),
            "amount": amount,
            "turnover": _get_col(row, "换手率", "turnover_rate"),
            "pe": _get_col(row, "市盈率-动态", "pe_ttm", "pe"),
            "pb": _get_col(row, "市净率", "pb"),
            "fund_scale": scale,
        })

    logger.info("[etf_scanner] filter_etfs: %d -> %d", len(raw_list), len(results))
    # P4-b: 候选池为空时输出 ERROR 日志
    if len(results) == 0 and len(raw_list) > 0:
        logger.error(
            "[etf_scanner] filter_etfs: ALL %d ETFs filtered out! "
            "Check column name matching (garbled keys). First raw keys: %s",
            len(raw_list), list(raw_list[0].keys()) if raw_list else "N/A"
        )
    return results


def classify_etf(name: str, tracked_index: str = "") -> str:
    """三层自动分类: core / satellite / defense。

    核心层: 宽基指数 (名称含沪深300/中证500/创业板等)
    防御层: 商品/跨境/固收 (名称含黄金/国债/纳指等)
    卫星层: 排除法 (以上都不匹配的全归卫星)
    """
    for kw in CORE_KEYWORDS:
        if kw in name or kw in tracked_index:
            return "core"
    for kw in DEFENSE_KEYWORDS:
        if kw in name:
            return "defense"
    return "satellite"


def layer_ranking(
    items: list[dict[str, Any]],
    top_n: int = 15,
    required: list[str] | None = None,
) -> list[dict[str, Any]]:
    """层内排序取 TOP N。

    评分: 50% 流动性(成交额) + 50% 规模(基金规模)
    required: 强制保留的代码列表（即使不在 TOP N）
    """
    if not items:
        return []

    required = required or []

    # 计算百分位排名 (最高值得 1.0, 最低值得 0.0)
    def _percentile(key: str) -> list[float]:
        vals = [item.get(key, 0) or 0 for item in items]
        sorted_vals = sorted(set(vals), reverse=True)
        n = len(sorted_vals)
        rank_map = {v: (n - 1 - i) / max(n - 1, 1) if n > 1 else 1.0 for i, v in enumerate(sorted_vals)}
        return [rank_map.get(v, 0) for v in vals]

    amount_pct = _percentile("amount")
    scale_pct = _percentile("fund_scale")

    scored = []
    for i, item in enumerate(items):
        score = 0.50 * amount_pct[i] + 0.50 * scale_pct[i]
        scored.append((score, item))

    scored.sort(key=lambda x: -x[0])

    # 取 TOP N
    result = [item for _, item in scored[:top_n]]

    # 强制插入 required
    result_codes = {r["symbol"] for r in result}
    for req_code in required:
        if req_code not in result_codes:
            # 从原集合找
            found = None
            for item in items:
                if item["symbol"] == req_code:
                    found = item
                    break
            if found:
                result.append(found)
                result_codes.add(req_code)

    return result


def full_pipeline(raw_etfs: list[dict] | None = None) -> dict[str, list[dict]]:
    """完整管道: 全量扫描 → 过滤 → 三层分类 → 每层 TOP 15。

    返回: {"core": [...], "satellite": [...], "defense": [...]}
    """
    if raw_etfs is None:
        raw_etfs = fetch_all_etfs_base()
    if not raw_etfs:
        return {"core": [], "satellite": [], "defense": []}

    # 过滤
    filtered = filter_etfs(raw_etfs)

    # 分类
    layers: dict[str, list[dict]] = {"core": [], "satellite": [], "defense": []}
    for etf in filtered:
        layer = classify_etf(etf["name"], "")
        layers.setdefault(layer, []).append(etf)

    # 每层排序取 TOP 15
    core = layer_ranking(layers.get("core", []), top_n=15, required=CORE_REQUIRED)
    satellite = layer_ranking(layers.get("satellite", []), top_n=15)
    defense = layer_ranking(layers.get("defense", []), top_n=15, required=DEFENSE_REQUIRED)

    # 标记 layer
    for e in core:
        e["layer"] = "core"
    for e in satellite:
        e["layer"] = "satellite"
    for e in defense:
        e["layer"] = "defense"

    return {"core": core, "satellite": satellite, "defense": defense}
