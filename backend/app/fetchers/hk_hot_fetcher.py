"""F16 (round6 §16.4): 港股热点数据源——东财 push2delay 双源路由。

背景：行情分析切港股后热点板块/热门个股仍返回 A 股（三端点硬编码 A 股源）。
用户已决策：港股先做（push2delay m:128 全量港股 + f100 中文行业字段），
美股降级提示「该市场暂不支持热点排行」。

本模块：
- parse_hk_plates / parse_hk_hot_stocks：纯解析函数（可单测，不触网）；
- _fetch_hk_rows：真实网络拉取（push2 → push2delay 双源路由 + 冷却，
  复用 R5-2-6 在 etf_scanner 落地的机制思路）；
- get_hk_hot_plates / get_hk_hot_stocks：对外入口；
- get_us_unsupported：美股结构化降级提示。
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# R61/R63: 域名不散落硬编码——统一引用 market_context 集中常量
from ..core.market_context import EM_PUSH_HOST  # noqa: E402
from ..core.source_registry import registry  # noqa: E402

# P2-6: 双源路由 + 熔断由 SourceRegistry 统一接管（/admin/sources/circuit-breakers
# 可观测、可复位，与 A 股板块 sector_fetcher 一致）。原私有 _em_host_health 冷却
# 计数器删除——SourceHealth 指数退避（60s→120s→…→600s）接管同语义。
_EM_HOSTS = ("push2.eastmoney.com", EM_PUSH_HOST)
_EM_FALLBACK_SECONDS = 60
_EM_FAIL_STREAK = 3

# fltt=2&invt=2：东财 clist/get 不带该参数时 f2（价格）/f3（涨跌幅）返回 ×100 整数
# （盈富基金 f2=26160/f3=62 实为 26.16 港元/+0.62%）——港股热门个股与板块
# 热度曾全量 ×100 显示（用户反馈 round9 §7 港股涨跌幅异常），加参数修正语义。
# round14 P2-AI: fs=m:128 → fs=m:128+t:3（港股主板股票——排除基金/ETF/权证；
# t:1=基金/ETF、t:2=债券、t:6=权证）。热门个股榜曾混入盈富 02800/南方恒生科技 03033
# /杠杆做多 07709 等（docs/archived/round14 §2.17）。
_URL = "http://{host}/api/qt/clist/get?pn=1&pz=5000&po=1&np=1&fs=m:128+t:3&fields=f12,f14,f2,f3,f6,f100&fid=f6&fltt=2&invt=2"

# round14 P2-AI: 名称关键词兜底过滤（防东财 t:3 参数变更后基金/ETF 混入）。
# 注意勿用「恒生」前缀——会误杀普通股恒生银行 00011。
_FUND_NAME_HINTS = ("盈富", "南方恒生", "安硕", "道富", "标普", "纳指", "恒生中国企业", "恒生科技", "虚拟资产")


def _is_fund_like(name: str) -> bool:
    """t:3 之外的名称兜底：基金/ETF/杠杆工具特征。"""
    n = (name or "").upper()
    if "ETF" in n or "杠杆" in n or "做多" in n or "做空" in n or "两倍" in n:
        return True
    return any(kw in n for kw in _FUND_NAME_HINTS)

# 60s TTL 缓存 + last_ok：板块/个股两个端点各自触发 pz=5000 全量拉取，
# 同一分钟内多次大请求会触发东财限流（时好时坏 → 热门个股偶发 0 条）；
# 缓存共享避免重复拉取，失败时回退 last_ok 保证不空。
# round14 P2-AI: 缓存版本化——fs 参数变更（m:128 → m:128+t:3）时旧缓存
#（含基金/ETF 的 t:1 数据）不得回填新榜，key 不一致即忽略缓存重新拉取。
_HK_ROWS_CACHE: dict = {"ts": 0.0, "rows": [], "last_ok": [], "fs": ""}
_HK_ROWS_TTL = 60.0
_HK_FS = "m:128+t:3"


def _fetch_from_host(host: str) -> list[dict]:
    """单 host 拉取港股全量 spot；空 diff 视为失败（计入熔断阈值）。"""
    from ..utils.proxy import no_proxy
    import requests as _req
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    with no_proxy():
        r = _req.get(_URL.format(host=host), timeout=6, headers=headers)
    data = r.json()
    diff = (data.get("data") or {}).get("diff") or []
    if diff:
        return diff
    # 空 diff = 限流/风控异常态（非「查无数据」）——按失败计入熔断（原语义）
    raise ValueError(f"empty diff from {host}")


def _fetch_hk_rows() -> list[dict]:
    """真实拉取港股全量 spot（push2 优先 → push2delay 兜底）。

    60s TTL 缓存共享（板块/个股端点复用）+ 失败回退 last_ok——
    东财 pz=5000 大请求限流严格，无缓存时同分钟两次拉取第二次必空。
    P2-6: 双源路由与熔断经 SourceRegistry.route 统一接管（源名 hk_push2 /
    hk_push2delay，route=HK_hot），失败 3 次指数退避冷却，状态可在
    /admin/sources/circuit-breakers 观测与复位。
    """
    now = time.time()
    if now - _HK_ROWS_CACHE["ts"] < _HK_ROWS_TTL and _HK_ROWS_CACHE.get("fs") == _HK_FS:
        return _HK_ROWS_CACHE["rows"]
    rows = registry.route(
        [(f"hk_{host.split('.')[0]}", lambda h=host: _fetch_from_host(h))
         for host in _EM_HOSTS],
        route_name="HK_hot",
        operation="batch",
        target=_HK_FS,  # round14 P2-AI: target 与 URL fs 同步（熔断观测口径一致）
    )
    if rows:
        _HK_ROWS_CACHE.update({"ts": now, "rows": rows, "last_ok": rows, "fs": _HK_FS})
        return rows
    # 全失败 → last_ok 兜底（保证板块/个股端点不空），10s 后允许重试。
    # 版本化：last_ok 的 fs 与当前不一致（旧 t:1 基金数据）时不得回填
    if _HK_ROWS_CACHE["last_ok"] and _HK_ROWS_CACHE.get("fs") == _HK_FS:
        _HK_ROWS_CACHE["ts"] = now - (_HK_ROWS_TTL - 10)
        return _HK_ROWS_CACHE["last_ok"]
    logger.warning("[hk_hot] all hosts failed (registry.route returned None)")
    return []


def parse_hk_plates(rows: list[dict]) -> list[dict]:
    """按 f100 中文行业聚合涨跌幅/成交额 → 港股行业热点板块。

    返回按成交额降序的板块列表：
    [{name, change_pct(加权), amount, stock_count}]
    round14 P2-AI: 聚合前过滤基金/ETF 特征行（t:3 源头 + 名称兜底双保险）。
    """
    groups: dict[str, dict] = {}
    for r in rows or []:
        if _is_fund_like(str(r.get("f14", ""))):
            continue
        ind = _clean_industry(r.get("f100"))
        chg = _to_float(r.get("f3"))
        amt = _to_float(r.get("f6"))
        g = groups.setdefault(ind, {"name": ind, "amount": 0.0, "change_sum": 0.0, "stock_count": 0})
        g["amount"] += amt
        g["change_sum"] += chg
        g["stock_count"] += 1
    plates = []
    for g in groups.values():
        n = max(g["stock_count"], 1)
        plates.append({
            "name": g["name"],
            "change_pct": round(g["change_sum"] / n, 2),  # 简单平均涨跌幅
            "amount": round(g["amount"], 2),
            "stock_count": g["stock_count"],
        })
    plates.sort(key=lambda p: -p["amount"])
    return plates


def _clean_industry(raw) -> str:
    """P2-M (round10 §5.1): 东财 f100 无行业分类时返回 '-'（单连字符），
    旧兜底只处理空串 → '-' 成为虚假板块名。统一归一为「其他」。"""
    ind = (raw or "").strip()
    if not ind or ind in ("-", "--", "—", "0", "None", "nan", "N/A"):
        return "其他"
    return ind


def parse_hk_hot_stocks(rows: list[dict], top_n: int = 20) -> list[dict]:
    """按 f6（成交额）排序取前 N → 港股热门个股。

    round14 P2-AI: 名称关键词兜底过滤（t:3 之外的双保险）——防东财参数变更后
    基金/ETF/权证混入榜单；恒生银行 00011 等普通股不受影响（不用「恒生」前缀）。
    """
    stocks = []
    for r in rows or []:
        name = r.get("f14", "")
        if _is_fund_like(str(name)):
            continue
        stocks.append({
            "symbol": r.get("f12", ""),
            "name": name,
            "price": _to_float(r.get("f2")),
            "change_pct": _to_float(r.get("f3")),
            "amount": _to_float(r.get("f6")),
            "industry": _clean_industry(r.get("f100")),
        })
    stocks.sort(key=lambda s: -s["amount"])
    return stocks[:top_n]


def get_hk_hot_plates(limit: int = 15) -> list[dict]:
    """港股行业热点板块（入口）。"""
    rows = _fetch_hk_rows()
    plates = parse_hk_plates(rows)[:limit]
    for p in plates:
        p["market"] = "HK"
    return plates


def get_hk_hot_stocks(limit: int = 20) -> list[dict]:
    """港股热门个股（入口）。"""
    rows = _fetch_hk_rows()
    stocks = parse_hk_hot_stocks(rows, top_n=limit)
    for s in stocks:
        s["market"] = "HK"
    return stocks


def get_us_unsupported() -> dict:
    """美股降级提示（用户决策：先不做美股热点）。"""
    return {"support": False, "message": "该市场暂不支持热点排行"}


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
