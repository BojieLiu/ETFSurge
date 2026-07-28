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

# ── Last-good 缓存兜底 ───────────────────────────────────────
_last_good_etfs: list[dict] | None = None

# ── 核心层关键词 ─────────────────────────────────────────────
CORE_KEYWORDS = [
    "沪深300", "中证A500", "中证500",
    "上证50", "上证180", "中证800",
    "深证100", "深证50",
    "科创50", "创业板",
    "MSCI", "A50", "A100",
]


# ── 防御层关键词 ─────────────────────────────────────────────
DEFENSE_KEYWORDS = [
    "黄金", "白银", "原油", "商品",
    "国债", "国开", "进出口", "地方债", "城投债", "可转债", "信用债",
    "标普500", "纳斯达克", "纳指", "道琼斯",
    "日经", "德国", "法国", "欧洲",
    "全球", "美元", "短融", "货币", "同业存单",
]

# ── 过滤阈值 ─────────────────────────────────────────────────
MIN_FUND_SCALE = 1.0          # 亿元
MIN_AVG_AMOUNT = 10_000_000   # 元 (1000万)

# 强制保留的标的（即使不在 TOP N）
CORE_REQUIRED = ["510300", "560600"]   # 沪深300ETF, 中证A500ETF
DEFENSE_REQUIRED = ["518880", "511090"]  # 黄金ETF, 30年国债ETF

# P0-3: tracked_index 关键词映射（从 ETF 名称提取指数名）
INDEX_KEYWORDS = {
    "沪深300": "沪深300",
    "中证A500": "中证A500",
    "上证50": "上证50",
    "上证180": "上证180",
    "中证800": "中证800",
    "深证100": "深证100",
    "深证50": "深证50",
    "创业板": "创业板",
    "科创50": "科创50",
    "MSCI": "MSCI",
    "A50": "A50",
    "A100": "A100",
    "红利": "红利",
    "黄金": "黄金",
    "国债": "国债",
    "纳指": "纳斯达克100",
    "标普500": "标普500",
    "恒生": "恒生",
    "中概": "中概",
    "半导体": "半导体",
    "新能源": "新能源",
    "医药": "医药",
    "消费": "消费",
    "军工": "军工",
}


def _extract_index_keyword(name: str) -> str:
    """从 ETF 名称中提取跟踪指数关键词。"""
    for kw, idx_name in INDEX_KEYWORDS.items():
        if kw in name:
            return idx_name
    return ""


def _tencent_gtimg_batch(codes: list[str]) -> dict[str, dict[str, Any]]:
    """通过腾讯 gtimg 批量查询 ETF 行情，返回 code→{amount, turnover, fund_scale, pe} 映射。

    gtimg 免费、稳定、一次返回 88 个字段，无需 token。
    """
    import requests as _req
    chunk_size = 100
    result: dict[str, dict[str, Any]] = {}
    for i in range(0, len(codes), chunk_size):
        chunk = codes[i:i + chunk_size]
        try:
            prefix = "sh" if codes[0][:2] in ("51", "58") else "sz"
            query_codes = [f"{prefix}{c}" if not c.startswith(("sh", "sz", "SH", "SZ")) else c for c in chunk]
            url = "http://qt.gtimg.cn/q=" + ",".join(c.lower() for c in query_codes)
            resp = _req.get(url, timeout=5)
            for line in resp.text.strip().split(";"):
                if not line or "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) < 46:
                    continue
                code = parts[2]
                code_key = code[2:] if code[:2].lower() in ("sh", "sz") else code
                try:
                    amount = float(parts[37] or 0)
                except (ValueError, TypeError):
                    amount = 0
                try:
                    turnover = float(parts[38] or 0)
                except (ValueError, TypeError):
                    turnover = 0
                try:
                    total_mv = float(parts[45] or 0)
                except (ValueError, TypeError):
                    total_mv = 0
                try:
                    pe = float(parts[47] or 0) if len(parts) > 47 else 0
                except (ValueError, TypeError):
                    pe = 0
                result[code_key] = {
                    "amount": amount,
                    "turnover": turnover,
                    "fund_scale": total_mv,
                    "pe": pe,
                }
        except Exception:
            continue
    return result


def _fetch_em_etf_list() -> list[dict] | None:
    """直连东方财富 push2 API 获取全量 ETF 列表（免 akshare，纯 HTTP+JSON）。

    字段映射：f12=代码  f14=名称  f2=最新价  f3=涨跌幅
             f62=换手率  f72=成交额  f184=基金规模  f66=市盈率  f45=成交量

    使用 m:1+t:2 覆盖沪深两市全部 ETF（~1843 只），免 akshare 封装。

    2026-07-27 修复: 新增 f72=成交额, 修正 f62→换手率, f45→成交量
    """
    from ..utils.proxy import no_proxy
    import requests as _req
    headers = {"User-Agent": "Mozilla/5.0"}
    fields = "f12,f14,f2,f3,f62,f72,f184,f66,f45,f168,f20,f21,f115,f116"
    all_items = []
    total = None
    for page in range(1, 20):
        url = (f"http://push2.eastmoney.com/api/qt/clist/get?"
               f"pn={page}&pz=100&po=1&np=1&fs=m:1+t:2&fields={fields}&fid=f3")
        try:
            with no_proxy():
                r = _req.get(url, timeout=5, headers=headers)
            data = r.json()
            diff = data.get("data", {}).get("diff", [])
            if page == 1:
                total = data.get("data", {}).get("total", 0)
            if not diff:
                break
            all_items.extend(diff)
            # 已取够全部，提前跳出
            if total and len(all_items) >= total:
                break
        except Exception:
            break
    if not all_items:
        return None
    return [{
        "symbol": item["f12"],
        "name": item.get("f14", ""),
        "amount": item.get("f72", 0) or 0,
        "fund_scale": item.get("f184", 0) or 0,
        "price": item.get("f2", 0) or 0,
        "change_pct": item.get("f3", 0) or 0,
        "turnover": item.get("f62", 0) or 0,      # 换手率
        "volume": item.get("f45", 0) or 0,        # 成交量
        "pe": item.get("f66", 0) or 0,
        "pb": item.get("f115", 0) or 0,
        "tracked_index": item.get("f168", ""),
    } for item in all_items]


def fetch_all_etfs_base() -> list[dict[str, Any]]:
    """一次调用获取全量 ETF 基础数据（带熔断路由）。

    数据源链: Sina/Tencent → East Money 直连 → akshare spot (熔断路由)
    每层通过 SourceRegistry 熔断路由保护，失败后自动冷却，跳过不可用源。

    返回: 每只 ETF 包含 代码/名称/最新价/涨跌幅/成交额/换手率/PE/PB/基金规模
    """
    global _last_good_etfs
    from ..core.ttl import CACHE_TTL
    cached = sync_memory_cache.get("all_etfs")
    if cached is not None:
        logger.debug("[etf_scanner] cache hit for all_etfs")
        return cached

    # 0. 文件缓存：重启后加速首次加载
    import os, json, time
    _cache_file = os.path.join(os.path.dirname(__file__), "..", "data", "etf_list_cache.json")
    if os.path.exists(_cache_file):
        try:
            with open(_cache_file, "r", encoding="utf-8") as _f:
                _fc = json.load(_f)
            if time.time() - _fc.get("ts", 0) < 14400 and len(_fc.get("etfs", [])) > 50:
                logger.info("[etf_scanner] file cache hit: %d ETFs", len(_fc["etfs"]))
                sync_memory_cache.set("all_etfs", _fc["etfs"], CACHE_TTL["etf_list"])
                return _fc["etfs"]
        except Exception:
            pass

    def _save_cache(etfs):
        try:
            os.makedirs(os.path.dirname(_cache_file), exist_ok=True)
            with open(_cache_file, "w", encoding="utf-8") as _f:
                json.dump({"ts": time.time(), "etfs": etfs}, _f, ensure_ascii=False)
        except Exception:
            pass

    from ..services.source_registry import registry

    # Provider 1: Sina ETF 列表 + Tencent gtimg 补充指标
    def _sina_tencent_provider():
        from .china_market import fetch_etf_list
        sina_result = fetch_etf_list()
        if not sina_result or len(sina_result) < 50:
            raise ValueError(f"Sina returned only {len(sina_result) if sina_result else 0} ETFs")

        all_codes = [item["symbol"] for item in sina_result]
        gtimg_map = _tencent_gtimg_batch(all_codes)
        if gtimg_map:
            merged = []
            for item in sina_result:
                code = item["symbol"]
                gt = gtimg_map.get(code, {})
                item["amount"] = gt.get("amount", 0)
                item["turnover"] = gt.get("turnover", 0)
                item["fund_scale"] = gt.get("fund_scale", 0)
                item["pe"] = gt.get("pe", 0)
                item["pb"] = 0
                merged.append(item)
            logger.info("[etf_scanner] Sina+Tencent merged: %d ETFs", len(merged))
            return merged

        # gtimg 挂时退到新浪纯列表
        logger.info("[etf_scanner] using Sina-only ETF list (no amount/scale filtering)")
        return sina_result

    # Provider 2: East Money 直连 HTTP
    def _eastmoney_provider():
        em_result = _fetch_em_etf_list()
        if em_result and len(em_result) >= 50:
            return em_result
        return None

    # Provider 3: akshare spot（最终兜底）
    def _akshare_provider():
        from ..utils.decode import decode_df as _decode_df
        def _p():
            import akshare as ak
            return ak.fund_etf_spot_em()
        df = run_in_thread(_p, timeout=25, executor="long")
        if df is None or df.empty:
            return None
        _decode_df(df)
        return df.to_dict(orient="records")

    # 通过 SourceRegistry 熔断路由依次尝试三个源
    # 熔断语义: 连续失败 failure_threshold(3) 次后冷却 cooldown(60s)
    result = registry.route(
        [
            ("sina_tencent_etf", _sina_tencent_provider),
            ("eastmoney_etf", _eastmoney_provider),
            ("akshare_etf", _akshare_provider),
        ],
        route_name="etf_scan",
        operation="batch",
        target="all_etfs",
    )

    if result:
        sync_memory_cache.set("all_etfs", result, CACHE_TTL["etf_list"])
        _last_good_etfs = result
        _save_cache(result)
        logger.info("[etf_scanner] circuit-breaker routed: %d ETFs", len(result))
        return result

    # 所有源全部失败 → 返回缓存/上次成功数据
    stale = sync_memory_cache.get("all_etfs")
    logger.warning("[etf_scanner] all data sources via circuit breaker exhausted, "
                   "returning stale cache (len=%d)", len(stale) if stale else 0)
    return stale or _last_good_etfs or []


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
    SCALE_NAMES = ["流通市值", "总市值", "fund_scale", "规模", "最新基金规模", "基金规模"]

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
            # P1-2: 国债ETF是防御层资产（30年国债ETF等），不应被过滤掉
            is_pure_bond = any(kw in name for kw in ["国开债", "城投债", "信用债", "可转债"])
            is_money_market = any(kw in name for kw in ["货币ETF", "短融ETF", "同业存单"])
            if is_pure_bond or is_money_market:
                continue

        amount = _get_col(row, *AMOUNT_NAMES)
        # 降级模式：当 amount=0（新浪源无此字段）时跳过金额过滤
        if amount > 0 and amount < MIN_AVG_AMOUNT:
            continue

        scale = _get_col(row, *SCALE_NAMES)
        # 降级模式：当 scale=0（新浪源无此字段）时跳过规模过滤
        if scale > 0 and scale < MIN_FUND_SCALE:
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
    top_n: int = 25,
    required: list[str] | None = None,
) -> list[dict[str, Any]]:
    """层内排序取 TOP N。

    评分: 优先使用基金规模排序。当成交额数据可用（有正数）时，
          使用 30% 成交额 + 70% 规模加权；当成交额不可用时，
          仅用规模排序（非交易时段/数据缺失场景）。

    修复 P2: 改用 scale 做主排序依据，top_n 从 15 提升到 25
            (fix-plan-pool.md 修复 P2)
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

    # 检查 amount 是否可用（有正数）
    amount_vals = [item.get("amount", 0) or 0 for item in items]
    max_amount = max(amount_vals)

    if max_amount > 100000:  # 有实际成交数据
        amount_pct = _percentile("amount")
        scale_pct = _percentile("fund_scale")
        scored = []
        for i, item in enumerate(items):
            score = 0.30 * amount_pct[i] + 0.70 * scale_pct[i]
            scored.append((score, item))
    else:
        # 仅用规模排序（成交额不可用时的兜底）
        scale_pct = _percentile("fund_scale")
        scored = []
        for i, item in enumerate(items):
            score = 1.00 * scale_pct[i]
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


# ── F10 tracked_index enrichment ──────────────────────────────────────────
import requests as _requests
import re as _re
import json as _json
import os as _os
import concurrent.futures as _cf

_TRACKED_INDEX_CACHE = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
    "data", "etf_index_mapping.json"
)

def _load_tracked_index_cache() -> dict[str, str]:
    try:
        if _os.path.exists(_TRACKED_INDEX_CACHE):
            with open(_TRACKED_INDEX_CACHE, "r", encoding="utf-8") as f:
                return _json.load(f)
    except Exception:
        return {}
    return {}

def _save_tracked_index_cache(mapping: dict[str, str]) -> None:
    try:
        _dir = _os.path.dirname(_TRACKED_INDEX_CACHE)
        if not _os.path.exists(_dir):
            _os.makedirs(_dir, exist_ok=True)
        with open(_TRACKED_INDEX_CACHE, "w", encoding="utf-8") as f:
            _json.dump(mapping, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def enrich_tracked_indices(etfs: list[dict], cache: dict[str, str] | None = None) -> list[dict]:
    """批量补充 ETF tracked_index（东方财富概览页）。

    只补充 tracked_index 为空且不在缓存中的 ETF，结果写入本地 JSON 缓存。
    直接修改传入的 list 并返回。
    """
    local_cache = _load_tracked_index_cache() if cache is None else cache
    _headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}

    need_fetch = []
    for etf in etfs:
        sym = etf.get("symbol", "")
        if not sym:
            continue
        tidx = etf.get("tracked_index", "") or ""
        if not tidx:
            if sym in local_cache:
                etf["tracked_index"] = local_cache[sym]
            else:
                need_fetch.append(etf)

    if not need_fetch:
        return etfs

    def _fetch_one(sym: str) -> tuple[str, str | None]:
        try:
            url = f"https://fund.eastmoney.com/{sym}.html"
            r = _requests.get(url, timeout=8, headers=_headers)
            r.encoding = "utf-8"
            text = r.text
            # 跟踪标的：</a>上证科创板100指数 | <a href=...
            m = _re.search(r"跟踪标的[：:]?\s*</a>([^<｜]+)\s*[|｜]", text)
            if m:
                return sym, m.group(1).strip()
            m2 = _re.search(r"跟踪标的[：:]\s*([^<]{2,40})", text)
            if m2:
                return sym, m2.group(1).strip()
        except Exception:
            pass
        return sym, None

    updated = 0
    with _cf.ThreadPoolExecutor(max_workers=3) as executor:
        fut_map = {executor.submit(_fetch_one, e["symbol"]): e["symbol"] for e in need_fetch}
        for fut in _cf.as_completed(fut_map):
            try:
                sym, idx_name = fut.result()
                if idx_name:
                    local_cache[sym] = idx_name
                    for etf in etfs:
                        if etf.get("symbol") == sym:
                            etf["tracked_index"] = idx_name
                            updated += 1
                            break
            except Exception:
                pass

    _save_tracked_index_cache(local_cache)
    logger.info("TrackedIndexEnrich: %d/%d ETFs enriched via F10", updated, len(need_fetch))
    return etfs


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

    # 分类（P0-3: 从名称提取 tracked_index 并回填，使去重和分类更准确）
    layers: dict[str, list[dict]] = {"core": [], "satellite": [], "defense": []}
    for etf in filtered:
        tracked_idx = etf.get("tracked_index", "") or _extract_index_keyword(etf.get("name", ""))
        etf["tracked_index"] = tracked_idx
        layer = classify_etf(etf["name"], tracked_idx)
        layers.setdefault(layer, []).append(etf)

    # 每层排序取 TOP 15
    core = layer_ranking(layers.get("core", []), top_n=25, required=CORE_REQUIRED)
    satellite = layer_ranking(layers.get("satellite", []), top_n=25)
    defense = layer_ranking(layers.get("defense", []), top_n=25, required=DEFENSE_REQUIRED)

    # 标记 layer
    for e in core:
        e["layer"] = "core"
    for e in satellite:
        e["layer"] = "satellite"
    for e in defense:
        e["layer"] = "defense"

    return {"core": core, "satellite": satellite, "defense": defense}