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

# round11 P1-5: TTL 归一——不再散落本地常量，统一读 core/ttl.py 的 CACHE_TTL["etf_list"]（3600s）。
# （旧实现硬编码 300s 与 CACHE_TTL 声明不一致；缓存机制本身已由 sync_memory_cache 接管。）
from ..core.ttl import CACHE_TTL as _CACHE_TTL
_etf_list_cache = {}
ETF_CACHE_TTL = _CACHE_TTL["etf_list"]

# ── Last-good 缓存兜底 ───────────────────────────────────────
_last_good_etfs: list[dict] | None = None

# ── 核心层关键词 ─────────────────────────────────────────────
CORE_KEYWORDS = [
    "沪深300", "中证A500", "中证500",
    "上证50", "上证180", "中证800",
    "深证100", "深证50",
    "科创50", "创业板",
    "MSCI", "A50", "A100",
    # M1 (combination-design-review): 红利类归 core，作防守型核心（用户决策 2026-08-01）
    "红利低波", "中证红利",
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
# round9 P0-8: 560600（幽灵锚）→ 159338（真实中证A500ETF）
CORE_REQUIRED = ["510300", "159338"]   # 沪深300ETF, 中证A500ETF
DEFENSE_REQUIRED = ["518880", "511090"]  # 黄金ETF, 30年国债ETF

# F0-5 步骤 B: 主流宽基静态兜底清单（不依赖当日涨幅榜，使 CORE_REQUIRED/
# DEFENSE_REQUIRED 的注入逻辑真正生效）。full_pipeline 组装候选池后，
# 将清单成员补录进对应层——否则涨幅榜 Top25 会把主流宽基挤出候选池，
# layer_ranking 的 required 注入（仅从候选池 items 查找）静默失效。
WIDE_BASIS_STATIC = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "tracked_index": "沪深300",
     "fund_scale": 900.0, "amount": 2_000_000_000, "price": 0.0, "change_pct": None},
    {"symbol": "510500", "name": "中证500ETF", "layer": "core", "tracked_index": "中证500",
     "fund_scale": 800.0, "amount": 1_500_000_000, "price": 0.0, "change_pct": None},
    {"symbol": "510050", "name": "上证50ETF", "layer": "core", "tracked_index": "上证50",
     "fund_scale": 700.0, "amount": 1_000_000_000, "price": 0.0, "change_pct": None},
    {"symbol": "588000", "name": "科创50ETF", "layer": "core", "tracked_index": "科创50",
     "fund_scale": 600.0, "amount": 800_000_000, "price": 0.0, "change_pct": None},
    {"symbol": "159915", "name": "创业板ETF", "layer": "core", "tracked_index": "创业板指",
     "fund_scale": 500.0, "amount": 700_000_000, "price": 0.0, "change_pct": None},
    # M1: 中证A500（round9 P0-8: 560600 幽灵锚删除，159338 真实可成交）
    {"symbol": "159338", "name": "中证A500ETF", "layer": "core", "tracked_index": "中证A500",
     "fund_scale": 550.0, "amount": 900_000_000, "price": 0.0, "change_pct": None},
    # M1: 红利类归 core，作防守型核心（用户决策 2026-08-01，防御型红利合计上限 15% 见 risk_controls）
    {"symbol": "512890", "name": "红利低波ETF", "layer": "core", "tracked_index": "红利低波",
     "fund_scale": 200.0, "amount": 300_000_000, "price": 0.0, "change_pct": None},
    {"symbol": "515080", "name": "中证红利ETF", "layer": "core", "tracked_index": "中证红利",
     "fund_scale": 150.0, "amount": 200_000_000, "price": 0.0, "change_pct": None},
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "tracked_index": "黄金",
     "fund_scale": 400.0, "amount": 1_200_000_000, "price": 0.0, "change_pct": None},
    {"symbol": "511090", "name": "30年国债ETF", "layer": "defense", "tracked_index": "国债",
     "fund_scale": 300.0, "amount": 500_000_000, "price": 0.0, "change_pct": None},
]

# F0-5 步骤 B: 静态兜底注入——优先复用 raw 数据（若有实时成交额/规模），
# 否则使用静态元数据。
def _inject_static_wide_basis(
    layer_items: list[dict[str, Any]],
    layer: str,
    raw_etfs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_by_code = {e.get("symbol"): e for e in raw_etfs or []}
    existing = {e["symbol"] for e in layer_items}
    injected: list[str] = []
    for item in WIDE_BASIS_STATIC:
        if item["layer"] != layer or item["symbol"] in existing:
            continue
        merged = dict(item)
        raw = raw_by_code.get(item["symbol"])
        if raw:
            for k in ("price", "change_pct", "amount", "fund_scale", "turnover", "volume", "name", "tracked_index"):
                if raw.get(k):
                    merged[k] = raw[k]
        layer_items.append(merged)
        injected.append(item["symbol"])
    if injected:
        logger.info(
            "WideBasisInject: layer=%s injected %d static fallbacks: %s",
            layer, len(injected), ",".join(sorted(injected)),
        )
    return layer_items


def _etf_cache_file() -> str:
    """ETF 列表文件缓存路径（R6-F7, round6 §十 R6-08）。

    优先级：①DATA_DIR 环境变量显式指定；②容器内 /app/data 挂载卷（与
    portfolio.db 同卷，容器重建不丢——旧实现在镜像层 /app/app/data 必丢）；
    ③宿主机开发回落 backend/data（现状路径）。
    """
    import os
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        return os.path.join(data_dir, "etf_list_cache.json")
    if os.path.exists("/app/data"):
        return os.path.join("/app/data", "etf_list_cache.json")
    # P1-11 (round9 §4.3-B 附带①): 宿主分支路径修正 `../../data`——旧实现
    # `os.path.dirname(__file__)/../data` 解析到 backend/app/data/（多带一层 app/，
    # 文件不存在）→ 宿主环境 _snapshot_change_pct 永远 None；正确为项目根 data/。
    return os.path.join(os.path.dirname(__file__), "..", "..", "data", "etf_list_cache.json")


def _log_missing_required(layer: str, required: list[str], pool_items: list[dict[str, Any]]) -> None:
    """M2: 强制标的注入后校验——required 未命中打 WARNING，消除静默失效。"""
    if not required:
        return
    in_pool = {e.get("symbol") for e in pool_items}
    missing = [c for c in required if c not in in_pool]
    if missing:
        logger.warning(
            "WideBasisInject: layer=%s REQUIRED codes missing from pool after injection: %s",
            layer, ",".join(missing),
        )

# P0-3: tracked_index 关键词映射（从 ETF 名称提取指数名）
INDEX_KEYWORDS = {
    "沪深300": "沪深300",
    "中证A500": "中证A500",
    # M3: 中证500 家族（价值/成长/增强）名称提取为基准指数，与归一化保持一致
    "中证500": "中证500",
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
    # O15 (round8 §7 §5.1A): 「消费电子」置于「消费」前——562950 名称含"消费"，
    # 无此键时 tracked_index 回填为"消费"（丢"电子"）→ 分类误归食品饮料。
    "消费电子": "消费电子",
    "消费": "消费",
    "军工": "军工",
}


def _extract_index_keyword(name: str) -> str:
    """从 ETF 名称中提取跟踪指数关键词——O15 最长匹配优先。

    旧实现按 dict 插入序遍历：'消费' 在 '消费电子' 前 → '消费电子ETF易方达'
    被截成 '消费'（丢 '电子'）→ 562950 tracked_index='消费' → 误分类食品饮料。
    """
    for kw, idx_name in sorted(INDEX_KEYWORDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if kw in name:
            return idx_name
    return ""


def _tencent_gtimg_chunk(chunk: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch a single gtimg chunk (sync HTTP). Returns code→metrics map."""
    import requests as _req
    partial: dict[str, dict[str, Any]] = {}
    try:
        prefix = "sh" if chunk[0][:2] in ("51", "58") else "sz"
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
                # round15 方案四 (P0): 单位契约——gtimg parts[37] 成交额单位=万元，
                # ×10000 统一为元。filter_etfs 的 MIN_AVG_AMOUNT=10_000_000（元）、
                # layer_ranking 的 max_amount>100000（元）、composite 的 amount*1e-9
                # 均按元口径（此前万元值被误当元比较 → 真实活跃 ETF 全被误杀，§4.6）。
                amount_wan = float(parts[37] or 0)
                amount = amount_wan * 10000.0
            except (ValueError, TypeError):
                amount = 0
            try:
                turnover = float(parts[38] or 0)
            except (ValueError, TypeError):
                turnover = 0
            try:
                # gtimg 总市值单位=亿，与 MIN_FUND_SCALE(亿) 匹配，无需换算；
                # composite 的 scale*1e-9 对此单位≈0（round15 方案二 _pct_rank 根治）。
                total_mv = float(parts[45] or 0)
            except (ValueError, TypeError):
                total_mv = 0
            try:
                pe = float(parts[47] or 0) if len(parts) > 47 else 0
            except (ValueError, TypeError):
                pe = 0
            partial[code_key] = {
                "amount": amount,
                "turnover": turnover,
                "fund_scale": total_mv,
                "pe": pe,
            }
    except Exception:
        return partial
    return partial


def _cross_check_amount_scale(gtimg_map: dict[str, dict[str, Any]], em_list: list[dict] | None) -> None:
    """round15 方案四: 跨源量级一致性校验（防单位错配复发）。

    腾讯 amount（已 ×10000 为元）与 EM 源（元）同标的交叉比对，差 >100 倍即告警。
    EM 列表获取失败/单标的缺失时静默跳过——校验是防御性的，不阻断主链路
    （§4.6.3：多源降级链防「源挂」，防不了「源没挂但数据单位错了」）。
    """
    if not gtimg_map or not em_list:
        return
    em_map: dict[str, float] = {}
    for row in em_list:
        code = str(row.get("symbol") or row.get("代码") or "").strip()
        amt = row.get("amount") or row.get("成交额") or 0
        if code:
            em_map[code] = float(amt or 0)
    checked = 0
    for code, gt in gtimg_map.items():
        tencent_amt = float(gt.get("amount", 0) or 0)
        em_amt = em_map.get(code, 0.0)
        if tencent_amt <= 0 or em_amt <= 0:
            continue
        ratio = tencent_amt / em_amt if tencent_amt > em_amt else em_amt / tencent_amt
        if ratio > 100:
            logger.warning(
                "[etf_scanner] 跨源量级不一致: %s 腾讯=%s元 EM=%s元 (ratio=%.0fx) — amount 单位契约被破坏",
                code, tencent_amt, em_amt, ratio,
            )
        checked += 1
        if checked >= 50:  # 抽样 50 只足够，避免全量比对日志
            break


# P0-23 (round16 3.25): 快照成交额实时补查缓存（30s TTL）——快照 amount 可能
# 低估 ~2000 倍（半日/盘中早段成交 vs 全天量）误杀活跃板块 ETF（159516/513010 等）。
_AMOUNT_FIX_CACHE: dict = {"ts": 0.0, "map": {}}
_AMOUNT_FIX_TTL = 30.0


def _real_amount_override(codes: list[str]) -> dict[str, float]:
    """P0-23①③: 对存疑成交额标的批量实时补查（gtimg），返回 code→真实成交额（元）。

    快照 amount 存疑（<MIN_AVG_AMOUNT）时用实时 gtimg 成交额覆盖判定，
    避免「虚拟低流动性」误杀活跃板块 ETF；失败返回 {}（调用方保持过滤）。
    """
    import os
    import time as _t
    if not codes:
        return {}
    # 测试隔离：ETF_SKIP_AMOUNT_OVERRIDE=1 时跳过网络补查（直接过滤存疑行）
    if os.environ.get("ETF_SKIP_AMOUNT_OVERRIDE", "").strip().lower() in ("1", "true", "yes"):
        return {}
    now = _t.time()
    if now - _AMOUNT_FIX_CACHE["ts"] > _AMOUNT_FIX_TTL:
        try:
            gt = _tencent_gtimg_batch(codes)
            _AMOUNT_FIX_CACHE["map"] = {
                c: float(g.get("amount", 0) or 0) for c, g in (gt or {}).items()
            }
            _AMOUNT_FIX_CACHE["ts"] = now
        except Exception as e:
            logger.warning("[etf_scanner] P0-23 real amount override failed: %s", e)
            _AMOUNT_FIX_CACHE["ts"] = now  # 冷却，避免热循环重试
    return {c: v for c, v in _AMOUNT_FIX_CACHE["map"].items() if c in codes}


def _tencent_gtimg_batch(codes: list[str]) -> dict[str, dict[str, Any]]:
    """通过腾讯 gtimg 批量查询 ETF 行情，返回 code→{amount, turnover, fund_scale, pe} 映射。
    gtimg 免费、稳定、一次返回 88 个字段，无需 token。

    F9: 将原来「逐块串行 HTTP」改为「分块后线程池并发请求」，把 ~18 个串行
    请求压缩为并发（典型 5~8 worker），显著缩短预热期 ETF 扫描耗时。
    单块失败不影响其他块（各自 try/except），行为向后兼容。
    """
    chunk_size = 100
    chunks = [codes[i:i + chunk_size] for i in range(0, len(codes), chunk_size)]
    if not chunks:
        return {}
    # 小批量直接串行，避免线程池开销
    if len(chunks) <= 2:
        merged: dict[str, dict[str, Any]] = {}
        for ch in chunks:
            merged.update(_tencent_gtimg_chunk(ch))
        return merged
    from concurrent.futures import ThreadPoolExecutor
    result: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as ex:
        for partial in ex.map(_tencent_gtimg_chunk, chunks):
            result.update(partial)
    return result


def _fetch_em_etf_list(host: str | None = None) -> list[dict] | None:
    """直连东方财富 push2 API 获取全量 ETF 列表（免 akshare，纯 HTTP+JSON）。

    字段映射：f12=代码  f14=名称  f2=最新价  f3=涨跌幅
             f62=换手率  f72=成交额  f184=基金规模  f66=市盈率  f45=成交量

    使用 m:1+t:2 覆盖沪深两市全部 ETF（~1843 只），免 akshare 封装。

    2026-07-27 修复: 新增 f72=成交额, 修正 f62→换手率, f45→成交量
    R5-2-6: host 参数化（push2 优先 → push2delay 兜底，双源路由）；两域名
    响应结构一致，解析层零改动。
    """
    from ..utils.proxy import no_proxy
    import requests as _req
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    fields = "f12,f14,f2,f3,f62,f72,f84,f85,f184,f66,f45,f168,f20,f21,f115,f116"
    all_items = []
    total = None
    # F0-5 步骤 A: fid=f3（涨跌幅）→ fid=f6（成交额）排序，
    # 主流宽基成交额/规模恒居前列，天然留在池内（不再被题材股涨幅榜挤出）。
    for page in range(1, 20):
        # R5-2-6: host 参数化（调用方经 registry.route 双源路由，传具体域名）
        if host is None:
            from ..core.market_context import EM_PUSH_HOST
            host = EM_PUSH_HOST
        url = (f"http://{host}/api/qt/clist/get?"
               f"pn={page}&pz=100&po=1&np=1&fs=m:1+t:2&fields={fields}&fid=f6")
        # F0-5 步骤 A: 分页失败重试 1 次，仍失败则记录 WARNING 继续下一页（不静默丢页）
        stop_paging = False
        for attempt in range(2):
            try:
                with no_proxy():
                    r = _req.get(url, timeout=5, headers=headers)
                data = r.json()
                diff = data.get("data", {}).get("diff", [])
                if page == 1:
                    total = data.get("data", {}).get("total", 0)
                if not diff:
                    stop_paging = True  # 无更多数据
                    break
                all_items.extend(diff)
                if total and len(all_items) >= total:
                    stop_paging = True  # 已取够全部
                    break
                break  # 本页成功且未取够 → 下一页
            except Exception:
                if attempt == 1:
                    logger.warning(
                        "[etf_scanner] EM ETF list page %d failed twice, skipping (not breaking)",
                        page,
                    )
        if stop_paging:
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
        "fund_shares": item.get("f85", 0) or 0,  # 基金份额 (S2: 用于 shares_change 因子)
        "fund_scale2": item.get("f84", 0) or 0,  # 基金规模备用
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
    # O1 (round7 §7 P1): 快照宽容——文件快照（len>50）无论新旧先返回。
    # 旧实现要求 ts < 14400s（4h）：容器重建/挂载卷时间戳跨阈值 → 每次启动
    # 全量 1618 只扫描（预热 128s 根因之一）。现在旧快照直接命中启动，
    # 数据新鲜度由 60s 周期刷新循环保证（内存缓存 TTL 过期后自然重扫）。
    import os, json, time
    _cache_file = _etf_cache_file()
    if os.path.exists(_cache_file):
        try:
            with open(_cache_file, "r", encoding="utf-8") as _f:
                _fc = json.load(_f)
            if len(_fc.get("etfs", [])) > 50:
                _age = time.time() - _fc.get("ts", 0)
                if _age >= 14400:
                    logger.info(
                        "[etf_scanner] file cache stale (age=%.0fs) — using snapshot for fast start, refresh via cycle",
                        _age,
                    )
                else:
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

    from ..core.source_registry import registry

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
            # round15 方案四: 绝对量级检查——修复后 amount 为元，正常 ETF 成交额
            # 远大于 1e6；0<amount<1e6 说明万元口径残留（防 ×10000 被回退）。
            _wan_residue = [
                c for c, g in gtimg_map.items()
                if 0 < float(g.get("amount", 0) or 0) < 1e6
            ]
            if _wan_residue:
                logger.warning(
                    "[etf_scanner] %d 标的 amount 疑似万元口径残留（<1e6 元，前 5: %s）",
                    len(_wan_residue), _wan_residue[:5],
                )
            # round15 方案四: 跨源量级一致性校验（与 EM 元口径交叉比对）
            try:
                _em_spot = _fetch_em_etf_list("push2delay.eastmoney.com")
                _cross_check_amount_scale(gtimg_map, _em_spot)
            except Exception:
                logger.debug("[etf_scanner] EM cross-check skipped (best-effort)", exc_info=True)
            logger.info("[etf_scanner] Sina+Tencent merged: %d ETFs", len(merged))
            return merged

        # gtimg 挂时退到新浪纯列表
        logger.info("[etf_scanner] using Sina-only ETF list (no amount/scale filtering)")
        return sina_result

    # Provider 2: East Money 直连 HTTP（R5-2-6: push2 优先 → push2delay 兜底，双源路由。
    # 指数退避匹配"限流按时段波动"：push2 连败 3 次冷却 60s → 自动用 push2delay；
    # push2 恢复后下次 route 自动回主源。两域名响应结构一致，解析层零改动。）
    def _eastmoney_provider():
        em_result = registry.route([
            ("em_push2", lambda: _fetch_em_etf_list("push2.eastmoney.com")),
            ("em_push2delay", lambda: _fetch_em_etf_list("push2delay.eastmoney.com")),
        ], route_name="em_etf_list", operation="list", target="etf_list") or []
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
    # P0-23: 存疑成交额标的（快照 amount < MIN_AVG_AMOUNT）先收集，循环后批量
    # 实时补查再判定——不静默按低值过滤（防「虚拟流动性误杀」活跃板块 ETF）。
    _suspicious: list[tuple[str, dict]] = []
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
        # P0-23①: amount>0 且 <MIN_AVG_AMOUNT → 存疑，收集后实时补查（不直接过滤）
        if amount > 0 and amount < MIN_AVG_AMOUNT:
            _suspicious.append((code, row))
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

    # P0-23①③: 存疑成交额标的实时补查——真实成交额 ≥ MIN_AVG_AMOUNT 则保留
    #（快照低估 ~2000 倍场景），仍低则过滤 + WARNING 护栏。
    if _suspicious:
        _susp_codes = [c for c, _ in _suspicious]
        _real_map = _real_amount_override(_susp_codes)
        _rescued = 0
        for code, row in _suspicious:
            _real = _real_map.get(code, 0) or 0
            if _real >= MIN_AVG_AMOUNT:
                _rescued += 1
                name = ""
                for k in NAME_NAMES:
                    v = row.get(k)
                    if v is not None and str(v).strip():
                        name = str(v).strip()
                        break
                scale = _get_col(row, *SCALE_NAMES)
                if scale > 0 and scale < MIN_FUND_SCALE:
                    continue
                results.append({
                    "symbol": code,
                    "name": name,
                    "price": _get_col(row, "最新价", "price"),
                    "change_pct": _get_col(row, "涨跌幅", "change_pct"),
                    "amount": _real,  # 用实时成交额覆盖快照
                    "turnover": _get_col(row, "换手率", "turnover_rate"),
                    "pe": _get_col(row, "市盈率-动态", "pe_ttm", "pe"),
                    "pb": _get_col(row, "市净率", "pb"),
                    "fund_scale": scale,
                })
            else:
                logger.warning(
                    "[etf_scanner] P0-23: %s 快照成交额 %.0f 元，实时补查仍 %.0f 元 < %d — 过滤（真实低流动性）",
                    code, _get_col(row, *AMOUNT_NAMES), _real, MIN_AVG_AMOUNT,
                )
        if _rescued:
            logger.info(
                "[etf_scanner] P0-23: %d 只存疑成交额标的经实时补查保留（快照低估误杀防护）",
                _rescued,
            )

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


# ── F4 (round6 §14.6): 卫星层非科技主题配额 ─────────────────────────────
# 卫星池被科创系包场的根因之一：纯规模排序 TOP N 被科创 ETF 占满，
# 非科技主题（医药/消费/金融/红利/新能源）代表被挤出。
# 主题配额：从全量卫星候选中按主题各保底 1 只（取规模最大者），
# 若不在 TOP N 中则强制注入，保证卫星层多赛道分散。
# 注：主题代表须排除科技系名称（科创医药ETF 是科创系，不算医药主题代表），
# 否则 588106 科创医药 会冒充 512010 医药ETF 的位置（§14.1 同型误判）。
_TECH_SATELLITE_KWS = ("科创", "半导体", "芯片", "AI", "人工智能")
_SATELLITE_THEME_QUOTA = [
    ("医药", ("医药", "医疗", "创新药")),
    ("消费", ("消费", "食品饮料", "白酒")),
    ("金融", ("金融", "银行", "券商", "证券")),
    ("红利", ("红利", "股息")),
    ("新能源", ("新能源", "光伏", "电池", "锂电", "碳中和")),
]


def _is_tech_satellite_name(name: str) -> bool:
    return any(k in (name or "") for k in _TECH_SATELLITE_KWS)


def _inject_satellite_theme_quota(
    satellite: list[dict[str, Any]],
    all_sat_cands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按非科技主题配额向卫星层注入代表（F4）。

    - 已在 TOP 内的主题代表不重复注入（幂等，返回原列表引用安全）。
    - 同一主题多只候选时取 fund_scale 最大者（排除科技系名称）。
    - 候选池本身缺少某主题时静默跳过（不注入）。
    """
    if not all_sat_cands:
        return satellite

    in_pool = {e.get("symbol") for e in satellite}
    result = list(satellite)
    for theme_name, kws in _SATELLITE_THEME_QUOTA:
        # 主题代表是否已在池中（名称匹配任一关键词，且非科技系）
        already = any(
            any(k in (e.get("name", "") or "") for k in kws)
            and not _is_tech_satellite_name(e.get("name", "") or "")
            for e in satellite
        )
        if already:
            continue
        # 从全量候选中找该主题规模最大者（排除科技系名称）
        reps = [
            e for e in all_sat_cands
            if any(k in (e.get("name", "") or "") for k in kws)
            and not _is_tech_satellite_name(e.get("name", "") or "")
        ]
        if not reps:
            logger.info(
                "[etf_scanner] satellite theme quota: no candidates for theme %s (skip)",
                theme_name,
            )
            continue
        best = max(reps, key=lambda e: e.get("fund_scale") or 0)
        if best.get("symbol") not in in_pool:
            best = dict(best)
            best["layer"] = "satellite"
            result.append(best)
            in_pool.add(best.get("symbol"))
            logger.info(
                "[etf_scanner] satellite theme quota: injected %s %s (scale=%.0f)",
                theme_name, best.get("name"), best.get("fund_scale") or 0,
            )
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

    # F4 (round6 §14.6): 卫星层非科技主题配额 — 纯规模排序被科创霸榜时，
    # 从全量卫星候选按医药/消费/金融/红利/新能源各保底注入 1 只代表，
    # 防止「卫星还是只有科创」（§14.1）。
    satellite = _inject_satellite_theme_quota(satellite, layers.get("satellite", []))

    # F0-5 步骤 B: 主流宽基静态兜底注入 — 涨幅榜 Top25 缺主流宽基时补录，
    # 使 CORE_REQUIRED/DEFENSE_REQUIRED 真正生效（层内 required 注入只查候选池 items）。
    core = _inject_static_wide_basis(core, "core", raw_etfs)
    defense = _inject_static_wide_basis(defense, "defense", raw_etfs)

    # M2: 注入后校验 required 未命中 → WARNING（消除静默失效）
    _log_missing_required("core", CORE_REQUIRED, core)
    _log_missing_required("defense", DEFENSE_REQUIRED, defense)

    # 标记 layer
    for e in core:
        e["layer"] = "core"
    for e in satellite:
        e["layer"] = "satellite"
    for e in defense:
        e["layer"] = "defense"

    return {"core": core, "satellite": satellite, "defense": defense}