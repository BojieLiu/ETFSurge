"""
strategy_design.py — 轻量编排器（v5）

职责：调用数据管道（market_data_hub）→ 调用纯策略引擎（engine/）→ 持久化返回。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from ..engine.allocation_engine import (
    allocate as engine_allocate,
    enforce_max_correlation,
    check_structure_reasonableness,
)
from ..engine.budgets import STRATEGY_META
from ..engine.rationale import build_rationale
from ..engine.risk_controls import apply_risk_controls

logger = logging.getLogger(__name__)

# O22 (round7 §7 P22): 快照兜底——etf_list_cache.json 的 symbol → 条目映射（懒加载 + 缓存）。
# 真实 change_pct 为百分比形式（如 1.358 = +1.358%）；K 线兜底返回小数需 ×100。
_snapshot_cache: dict[str, dict] | None = None


def _etf_cache_file() -> str:
    """ETF 列表文件缓存路径（委托 etf_scanner，含 DATA_DIR/容器卷优先级）。"""
    try:
        from ..fetchers.etf_scanner import _etf_cache_file as _scanner_path
        return _scanner_path()
    except Exception:
        return ""


def _market_data_fetched_at(market_data_hub) -> str | None:
    """P0-9 (round9 §4.3-A): 行情数据采集时刻（market_data_hub pool 刷新完成时刻）。

    设计报告「今日涨跌」列标注「截至 HH:MM」即此值——盘中生成的值可追溯，
    不再被误读为最新收盘（#427 11:58 生成 vs 收盘对照必错位）。
    """
    try:
        ts = getattr(market_data_hub, "_last_refresh_ts", 0.0) or time.time()
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def _load_snapshot_cache() -> dict[str, dict]:
    """懒加载 etf_list_cache.json → {symbol: entry}。失败返回 {}（不阻塞主流程）。"""
    global _snapshot_cache
    if _snapshot_cache is not None:
        return _snapshot_cache
    _snapshot_cache = {}
    try:
        import json
        import os
        path = _etf_cache_file()
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for e in (data.get("etfs", []) if isinstance(data, dict) else (data or [])):
                if isinstance(e, dict) and e.get("symbol"):
                    _snapshot_cache[str(e["symbol"])] = e
    except Exception as e:
        logger.warning("[strategy_design] snapshot cache load failed: %s", e)
    return _snapshot_cache


def _snapshot_change_pct(symbol: str) -> float | None:
    """快照兜底：etf_list_cache.json 的真实 change_pct（百分比，如 1.358）。

    显式 None 判断（同 F3 R8：丢弃 falsy 的 0.0 会误伤真实 0 涨跌）。
    """
    entry = _load_snapshot_cache().get(symbol)
    if not entry:
        return None
    dcp = entry.get("change_pct")
    if dcp is None:
        dcp = entry.get("daily_change_pct")
    return dcp if isinstance(dcp, (int, float)) else None


def _kline_change_pct(market_data_hub, symbol: str) -> float | None:
    """K 线兜底：(close[-1]-close[-2])/close[-2]（返回小数，复用 _compute_change_pct 逻辑）。

    P1-12 (round9 §4.3-B 附带②): 因子分用实时 `fetch_history`（300s 缓存）而涨跌用
    `get_kline_rows_any`（任意年龄缓存）→ 口径不一致（因子有分的标的涨跌莫名
    「数据源不可用」）。统一走 get_history 同通道：有历史 ⇒ 涨跌可算。
    """
    try:
        rows = None
        if hasattr(market_data_hub, "get_history"):
            rows = market_data_hub.get_history(symbol, "A", "daily")
        # 实时通道失败 → 降级任意年龄缓存（旧路径，最后兜底）
        if not rows and hasattr(market_data_hub, "get_kline_rows_any"):
            rows = market_data_hub.get_kline_rows_any(symbol)
        closes = [float(r.get("close")) for r in (rows or []) if r.get("close") is not None]
        if len(closes) >= 2 and closes[-2]:
            return round((closes[-1] - closes[-2]) / closes[-2], 4)
    except Exception as e:
        logger.debug("[strategy_design] kline change_pct fallback failed for %s: %s", symbol, e)
    return None


# O18/O5 (round8 §7 P5-新/R7-P22): 涨跌幅口径统一为「百分比」+ 值域校验。
# 注入层三源（pool 缓存 / etf_list_cache 快照 / K 线差×100）均为百分比口径；
# 渲染层（design_report.py）曾用 `abs(dcp)<1 → ×100` 猜测口径，把 ±1% 内的
# 百分比值放大 100 倍（-0.234% → -23.40%）。此处按代码形态判定交易所涨跌幅限制，
# 超范围视为「数据源异常」→ None（报告显示「数据源不可用/异常」而非透传荒谬数值）。
def change_pct_limit(code: str) -> float:
    """按代码形态判定涨跌幅限制（百分比值）：A 股 ±10%、港股 ±30%、美股 ±50%。"""
    c = str(code or "").upper().strip()
    for prefix in ("SH", "SZ", "BJ"):
        if c.startswith(prefix) and c[len(prefix):].isdigit():
            return 10.0  # A 股带交易所前缀（sh688981/sz000001/bj430047）
    c = c.split(".")[0]
    if any(ch.isalpha() for ch in c):
        return 50.0  # US（含字母，如 AAPL）
    if len(c) == 5 and c.isdigit():
        return 30.0  # HK（5 位纯数字，如 00700/09988）
    return 10.0      # A 股（6 位数字）


def sanitize_change_pct(code: str, dcp) -> float | None:
    """O5: 涨跌幅值域校验——超交易所限制视为数据源异常 → None。"""
    if dcp is None:
        return None
    try:
        val = float(dcp)
    except (TypeError, ValueError):
        return None
    limit = change_pct_limit(code)
    if abs(val) > limit:
        logger.warning(
            "[strategy_design] change_pct %.4f out of range (limit ±%.0f%%) for %s — treating as data-source anomaly",
            val, limit, code,
        )
        return None
    return val


# Z11: 静态兜底核心池（非交易时段 / 数据管道断裂时使用）
STATIC_CORE_POOL = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "510050", "name": "上证50ETF", "layer": "core",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "511010", "name": "国债ETF", "layer": "defense",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "159915", "name": "创业板ETF", "layer": "satellite",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
    {"symbol": "588000", "name": "科创50ETF", "layer": "satellite",
     "factor_score": 0.5, "trend_1m": 0.0, "trend_3m": 0.0,
     "fund_flow_20d": 0, "market_cap": 1e10},
]

# Z11: 静态政策标识因子之外，静态池每层内等权分配
def _build_static_pool_strategies(capital: float) -> list[dict]:
    """基于 STRATEGY_META.layer_budget 等权分配静态核心池，生成 3 套方案。

    Z11: 不再硬编码权重（0.4/0.35/0.25），统一引用 STRATEGY_META。
    """
    strategies: list[dict] = []
    for profile in ("defensive", "balanced", "aggressive"):
        meta = STRATEGY_META.get(profile, STRATEGY_META["balanced"])
        budget = meta.get("layer_budget", {"core": 0.40, "satellite": 0.30, "defense": 0.10})

        layer_groups: dict[str, list[dict]] = {"core": [], "satellite": [], "defense": []}
        for e in STATIC_CORE_POOL:
            layer = e.get("layer")
            if isinstance(layer, str) and layer in layer_groups:
                layer_groups[layer].append(e)

        allocs: list[dict] = []
        for layer, items in layer_groups.items():
            if not items:
                continue
            layer_weight = budget.get(layer, 0.0)
            per_item = round(layer_weight / len(items), 4)
            for it in items:
                allocs.append({
                    "symbol": it["symbol"],
                    "name": it["name"],
                    "layer": layer,
                    "weight": per_item,
                    "target_amount": round(capital * per_item, 2),
                    "selection_rationale": "静态核心池兜底（非交易时段/数据受限）",
                })

        used = sum(a["weight"] for a in allocs)
        cash = round(1.0 - used, 4)
        if cash > 0:
            allocs.append({
                "symbol": "CASH", "name": "现金", "layer": "cash",
                "weight": cash, "target_amount": round(capital * cash, 2),
                "selection_rationale": "流动性管理",
            })

        strategies.append({
            "id": profile,
            "name": meta.get("label", profile),
            "description": f"{meta.get('positioning', '')}（静态池兜底方案）",
            "risk_profile": profile,
            "expected_return": f"{meta.get('expected_return', 0.1)*100:.0f}-{meta.get('expected_return', 0.1)*100+4:.0f}%",
            "expected_volatility": "12-20%",
            "etfs": allocs,
        })
    return strategies


async def generate_enhanced_design(
    capital: float = 500000,
    constraints: dict | None = None,
    market: str = "A",
) -> dict:
    """
    v5 编排器：数据管道 → 策略引擎 → 持久化返回。

    Phase 5.1: 增加 market 参数入口，当前仅 A 股有候选池。
    """
    import time
    start_time = time.monotonic()
    constraints = constraints or {}
    _elapsed_logged = False

    # 1. 刷新数据管道（pipeline Stage 1 负责超时保护）
    from ..services.market_data_hub import market_data_hub
    _t1 = time.monotonic()
    try:
        await market_data_hub.refresh()
    except Exception as e:
        logger.warning("[strategy_design] market_data_hub.refresh failed — pool may be stale; _by_code=%d: %s",
                       len(market_data_hub._by_code), e)
    _t2 = time.monotonic()
    if _t2 - _t1 > 0.1:
        logger.info("[strategy_design] refresh took %.2fs, elapsed_total=%.2fs",
                     _t2 - _t1, time.monotonic() - start_time)

    # 2. 读取管道产出
    try:
        factor_matrix = market_data_hub.get_factor_matrix() or {}
    except Exception as e:
        logger.warning("[strategy_design] get_factor_matrix failed: %s", e)
        factor_matrix = {}
    candidates = {
        "core": market_data_hub.get_pool("core") or [],
        "satellite": market_data_hub.get_pool("satellite") or [],
        "defense": market_data_hub.get_pool("defense") or [],
    }

    # 2b. 检查候选池是否为空（Z11: 空池 → 静态池兜底 + degradation 标记）
    total_candidates = sum(len(v) for v in candidates.values())
    factor_matrix_empty = not bool(factor_matrix)
    pool_empty = total_candidates == 0
    static_pool_used: list[str] = []
    if total_candidates == 0:
        logger.warning("[strategy_design] empty candidate pool, falling back to static pool")
        pool_attr = getattr(market_data_hub, 'etf_pool', None)
        static_etfs: list[dict] = pool_attr if isinstance(pool_attr, list) else STATIC_CORE_POOL
        candidates = {
            "core": [e for e in static_etfs if e.get("layer") == "core"],
            "satellite": [e for e in static_etfs if e.get("layer") == "satellite"],
            "defense": [e for e in static_etfs if e.get("layer") == "defense"],
        }
        total_candidates = sum(len(v) for v in candidates.values())
        static_pool_used = [str(e.get("symbol", "")) for e in static_etfs if e.get("symbol")]

    market_regime = market_data_hub.get_market_regime() or "range_bound"
    market_context = await _build_market_context(market_data_hub)
    # P0-9: 行情采集时刻并入 market_context——随 market_snapshot_json 持久化，
    # 详情接口可查（报告「今日涨跌（截至 HH:MM）」与表格标注同源）
    try:
        market_context.setdefault("data_fetched_at", _market_data_fetched_at(market_data_hub))
    except Exception:
        pass

    # Z11: 降级模式判定（normal / static_pool / partial_data）
    _now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _degradation(mode: str, reason: str) -> dict:
        return {
            "mode": mode,
            "reason": reason,
            "factor_matrix_empty": factor_matrix_empty,
            "pool_empty": pool_empty,
            # P0-13②: 候选池冷却期/受限 refresh 降级标记（last-good 保留时非空但降级）
            "pool_degraded": bool(getattr(market_data_hub, "_degraded", False)),
            "static_pool_used": static_pool_used if mode == "static_pool" else [],
            "timestamp": _now_iso,
        }

    # 静态池兜底：直接生成 3 套方案（不进 allocate，避免二次降级）
    if pool_empty:
        strategies = _build_static_pool_strategies(capital)
        elapsed = time.monotonic() - start_time
        logger.info("[strategy_design] static pool fallback generated %d strategies in %.1fs",
                    len(strategies), elapsed)
        return {
            "strategies": strategies,
            "market_context": market_context,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "design_metadata": {
                "version": "v5-engine-static-pool",
                "elapsed_seconds": round(elapsed, 1),
                "regime": market_regime,
                "fallback": True,
                # P0-9: 行情数据采集时刻（market_data_hub pool 刷新完成时刻）
                "data_fetched_at": _market_data_fetched_at(market_data_hub),
            },
            "degradation": _degradation(
                "static_pool",
                "非交易时段/数据管道为空：候选池为空，使用静态核心池兜底",
            ),
        }

    try:
        # 3. 策略引擎：一次调用生成所有方案
        _t3 = time.monotonic()
        # 扁平化候选池：allocate() 预期 list[dict]，每项含 layer 字段
        flat_candidates: list = []
        for layer_list in candidates.values():
            flat_candidates.extend(layer_list)
        if _t3 - start_time > 0.2:
            logger.info("[strategy_design] pre-allocate %.2fs candidates=%d",
                         _t3 - start_time, len(flat_candidates))
        # P1-7 (round20): 当日板块涨幅榜传给引擎——aggressive 对强势板块 ETF 动态奖励
        # （医药/CRO 等非科技板块当日领涨不再被静态 _RISKY_THEMES 盲区忽略）
        try:
            _sector_momentum = market_data_hub.get_sector_momentum() or []
        except Exception:
            _sector_momentum = []
        strategies_raw = engine_allocate(
            risk_profile="balanced",
            factor_matrix=factor_matrix,
            candidates=flat_candidates,
            regime=market_regime,
            sector_momentum=_sector_momentum,
        )

        _t4 = time.monotonic()
        if _t4 - _t3 > 0.1:
            logger.info("[strategy_design] allocate took %.2fs", _t4 - _t3)

        # 4. 转换为前端期望的 etfs 字段名
        strategies = []
        _degraded_core: list[str] = []  # P1-5: 数据缺失被剔除核心权重的标的
        for s in strategies_raw:
            allocs = s.pop("allocations", [])
            # Apply risk controls before assembling
            # round15 9-F1: 透传 regime 与 layer_budget（core 层市态绝对防线依赖）
            risk_allocations = apply_risk_controls(
                [{"allocations": allocs, "layer_budget": s.get("layer_budget", {})}],
                factor_matrix,
                regime=market_regime,
            )
            allocs = risk_allocations[0]["allocations"] if risk_allocations else allocs

            # round19 P1-② (2026-08-12): 方案内标的与同方案其它持仓的中位数相关性
            # （低相关措辞数据源，缺失/失败时为空 dict → correlation_median=None 不影响）
            corr_medians = _correlation_medians_for(allocs, candidates)

            # round20 P1-1: 方案内两两相关性矩阵（复用 _correlation_medians_for 预热缓存，
            # 不重复拉 K 线）——供 enforce_max_correlation 高相关对权重约束
            corr_matrix = _correlation_matrix_for(allocs, candidates)

            # enrich rationale using engine/rationale.py
            for a in allocs:
                if a.get("symbol") == "CASH":
                    continue
                code = a["symbol"]
                sym_meta = _find_candidate_meta(code, candidates)
                a["selection_rationale"] = build_rationale(
                    code=code,
                    layer=a.get("layer", "satellite"),
                    strategy=s.get("id", "balanced"),
                    meta=sym_meta,
                    factor_scores=a.get("factor_breakdown", {}),
                    regime=market_regime,
                    industry=sym_meta.get("industry", "") if sym_meta else None,
                    correlation_median=corr_medians.get(code),
                )

            # round20 P1-1: 高相关对（r>=0.9）合计权重约束——削减低因子分标的并回补。
            # 注意：allocs 是 s.pop 出来的独立引用，enforce/check 在代理 dict 上写
            # risk_metrics；需把 warning 回写到真实 s（报告/前端消费）。
            _strat_proxy: dict[str, Any] = {"id": s.get("id"), "allocations": allocs}
            if corr_matrix:
                try:
                    enforce_max_correlation([_strat_proxy], corr_matrix)
                except Exception as _e:
                    logger.debug("[strategy_design] enforce_max_correlation skipped: %s", _e)
            else:
                # round22 E5 (engine-refactor-spec-round22.md §1 E5): 非交易窗口 / K 线相关性
                # 矩阵缺失（_correlation_matrix_for 返回空）——相关性约束**不得静默跳过**，
                # 降级标注 correlation_unchecked=True（前端提示「关联度未校验」），不阻塞主链路。
                _strat_proxy.setdefault("risk_metrics", {})["correlation_unchecked"] = True

            # round20 P2-5: 结构合理性检查——负信号防御层/进攻现金/防御层 median_r 标注
            try:
                check_structure_reasonableness(
                    [_strat_proxy], correlation_medians=corr_medians,
                )
            except Exception as _e:
                logger.debug("[strategy_design] structure check skipped: %s", _e)
            if _strat_proxy.get("risk_metrics"):
                s.setdefault("risk_metrics", {})
                for _k, _v in _strat_proxy["risk_metrics"].items():
                    if _k not in s["risk_metrics"]:
                        s["risk_metrics"][_k] = _v
                if s["risk_metrics"].get("correlation_warnings"):
                    logger.info(
                        "[strategy_design] %s correlation_warnings=%d",
                        s.get("id"), len(s["risk_metrics"]["correlation_warnings"]),
                    )

            # S6: Inject daily_change_pct and price from market_data_hub market data
            for a in allocs:
                if a.get("symbol") == "CASH":
                    continue
                code = a["symbol"]
                pool_entry = market_data_hub.get_by_code(code) if hasattr(market_data_hub, 'get_by_code') else {}
                if pool_entry:
                    # F3 R8: 显式 None 判断（旧 `or` 会丢弃 falsy 的 0.0——
                    # 静态兜底条目 change_pct 曾为 0.0 → "—" 误显示）
                    dcp = pool_entry.get("change_pct")
                    if dcp is None:
                        dcp = pool_entry.get("daily_change_pct")
                    if dcp is not None:
                        # O5 (round8 §7): 值域校验——超交易所限制（A ±10%）视为数据源异常
                        a["daily_change_pct"] = sanitize_change_pct(code, dcp)
                    price = pool_entry.get("price")
                    if price is None:
                        price = pool_entry.get("last_price")
                    if price is not None:
                        a["price"] = price
                    fs = pool_entry.get("factor_score")
                    if fs is not None:
                        a["factor_score"] = fs                # O22 (round7 §7 P22): fallback 修复——旧代码查 factor_matrix["change_pct"]
                # 键名不匹配（实际键是 "etf.change_pct"）且该值是 z-score 归一化值
                # （恒 ≠ 真实涨跌幅）→ 删除该 fallback，改为「快照 → K 线」两级兜底：
                # ① etf_list_cache.json 快照真实 change_pct（百分比，如 1.358）；
                # ② K 线 close 序列 (close[-1]-close[-2])/close[-2]（×100 转百分比）。
                # round10 P2-G: K 线差分（实时 K 线序列）优先于文件快照——快照可能滞后
                # 多个交易日（非交易日/缓存 TTL 内），K 线总是拉最近交易日，更「新」。
                if a.get("daily_change_pct") is None:
                    kcp = _kline_change_pct(market_data_hub, code)
                    if kcp is not None:
                        a["daily_change_pct"] = sanitize_change_pct(code, round(kcp * 100, 4))
                if a.get("daily_change_pct") is None:
                    dcp = _snapshot_change_pct(code)
                    if dcp is not None:
                        a["daily_change_pct"] = sanitize_change_pct(code, dcp)

            # round18 P1-4 (2026-08-12): design etfs[].price=None——候选池条目无
            # price 字段（S6 取 pool_entry.price/last_price 均 None）→ 前端持仓表
            # 价格列「—」。批量回查实时价（缺失标的统一 gather，单只超时 3s）。
            _missing_price = [
                a["symbol"] for a in allocs
                if a.get("symbol") != "CASH" and a.get("price") is None
            ]
            if _missing_price:
                async def _rt_price(code: str):
                    try:
                        _rt = await market_data_hub.get_asset_realtime(code, "A")
                        _p = (_rt or {}).get("price") if _rt else None
                        return code, float(_p) if _p else None
                    except Exception:
                        return code, None
                _prices = dict(await asyncio.gather(*[_rt_price(c) for c in _missing_price]))
                for a in allocs:
                    if a.get("symbol") != "CASH" and a.get("price") is None and a["symbol"] in _prices:
                        if _prices[a["symbol"]] is not None:
                            a["price"] = _prices[a["symbol"]]

            # P1-5 (round9 §4.1-1/§4.3-B): 数据缺失标的不得带核心权重——候选池正常时，
            # 三源（pool 缓存/快照/K线）全拿不到涨跌的核心层标的：权重清零（现金吸收）+
            # data_unavailable 标注 + 理由追加说明。旧实现 560600 类幽灵锚永远以 6% 权重
            # 入核心层且「今日涨跌：数据源不可用」——专业不可接受。
            # 判定窗口：核心层涨跌命中率 ≥50% 才执行清零（数据源整体挂时保留权重+标注，
            # 避免全方案变 CASH；个别缺失才剔除——幽灵锚场景命中率高，判定必触发）。
            if not pool_empty:
                _core_all = [a for a in allocs
                             if a.get("symbol") != "CASH" and a.get("layer") == "core"]
                _core_hit = sum(1 for a in _core_all if a.get("daily_change_pct") is not None)
                _hit_ratio = (_core_hit / len(_core_all)) if _core_all else 1.0
                if _hit_ratio >= 0.5:
                    for a in allocs:
                        if a.get("symbol") == "CASH" or a.get("layer") != "core":
                            continue
                        if a.get("daily_change_pct") is None:
                            a["weight"] = 0.0
                            a["data_unavailable"] = True
                            a["selection_rationale"] = (
                                (a.get("selection_rationale") or "")
                                + "【数据缺失：行情源不可用，已剔除核心权重，标注不参与配置】"
                            )
                            _degraded_core.append(str(a.get("symbol", "")))

            # Calculate cash
            total_weight = sum(a.get("weight", 0) for a in allocs if a.get("symbol") != "CASH")
            cash_weight = round(1.0 - total_weight, 4)
            if cash_weight > 0:
                allocs.append({
                    "symbol": "CASH", "name": "现金", "layer": "cash",
                    "weight": cash_weight, "selection_rationale": "流动性管理",
                })

            s["etfs"] = allocs
            # Add target_amount for each allocation
            for a in s["etfs"]:
                a["target_amount"] = round(capital * a.get("weight", 0), 2)
            strategies.append(s)

        # 5. target_amount 一致性校验
        _validate_target_amount_consistency(strategies, capital)

        # round22: 跨方案不变量 INV-3/5/6 校验（需三方案齐全；INV-4 已在逐方案
        # check_structure_reasonableness 内校验）。倒挂组合（卫星/标的数/进攻压舱）
        # 在此被捕获并写入 aggressive 的 risk_metrics.structure_warnings。
        try:
            check_structure_reasonableness(strategies, cross_profile_only=True)
        except Exception as _e:
            logger.debug("[strategy_design] cross-profile structure check skipped: %s", _e)

        # 6. 组装返回
        elapsed = time.monotonic() - start_time
        logger.info("[strategy_design] v5 orchestrator generated %d strategies in %.1fs",
                    len(strategies), elapsed)

        # Z11: 部分候选缺因子分 → partial_data 模式
        missing_symbols: list[str] = []
        for layer_list in candidates.values():
            for c in layer_list:
                if not isinstance(c, dict):
                    continue
                sym = c.get("symbol")
                if sym and sym not in (factor_matrix or {}):
                    missing_symbols.append(str(sym))
        partial_data = bool(missing_symbols) and not pool_empty
        return {
            "strategies": strategies,
            "market_context": market_context,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "design_metadata": {
                "version": "v5-engine",
                "elapsed_seconds": round(elapsed, 1),
                "regime": market_regime,
                # P0-9: 行情数据采集时刻（market_data_hub pool 刷新完成时刻）——
                # 报告「今日涨跌（截至 HH:MM）」与此对齐，盘中值可追溯
                "data_fetched_at": _market_data_fetched_at(market_data_hub),
                # P1-5: 数据缺失被剔除核心权重的标的清单（pool 正常时三源全拿不到涨跌）
                "degraded_core_symbols": sorted(set(_degraded_core)),
            },
            # Z11: 正常路径也暴露 degradation（mode=normal / partial_data）
            "degradation": _degradation(
                "partial_data" if partial_data else "normal",
                "部分候选标的缺因子分：缺失因子按 0 填充"
                if partial_data else "正常数据管道",
            ),
        }
    except (asyncio.TimeoutError, ValueError, KeyError, ConnectionError, OSError, RuntimeError) as e:
        logger.exception("[strategy_design] generate_enhanced_design failed — attempting static pool fallback")
        # Z11: Fallback to static ETF pool when design pipeline fails
        try:
            fallback_strategies = _build_static_pool_strategies(capital)
            elapsed = time.monotonic() - start_time
            logger.info("[strategy_design] fallback generated %d strategies in %.1fs",
                        len(fallback_strategies), elapsed)
            return {
                "strategies": fallback_strategies,
                "market_context": market_context,
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "design_metadata": {
                    "version": "v5-engine-static-pool",
                    "elapsed_seconds": round(elapsed, 1),
                    "regime": market_regime,
                    "fallback": True,
                    "data_fetched_at": _market_data_fetched_at(market_data_hub),
                },
                "warning": "使用静态池兜底，因子数据不可用",
                "degradation": _degradation(
                    "static_pool",
                    f"设计管线异常（{type(e).__name__}），使用静态核心池兜底",
                ),
            }
        except Exception as fallback_e:
            logger.exception("[strategy_design] fallback also failed")
            return {
                "strategies": [],
                "market_context": market_context,
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "design_metadata": {"version": "v5-engine", "elapsed_seconds": round(time.monotonic() - start_time, 1), "regime": market_regime},
                "error": "策略生成失败",
                "detail": str(e),
            }


# OPT-04: 资金流向并发限流，最多 8 个并发请求
_fund_flow_sem = asyncio.Semaphore(8)


async def _compute_fund_flow(market_data_hub) -> dict:
    """聚合全市场候选 ETF 资金流向（带并发限流 + 熔断器保护）。

    OPT-02: push2 熔断时快速返回空数据（不等 8s 超时）。
    OPT-04: Semaphore(8) 限制并发，防止线程池耗尽。

    返回:
      {"total_net_inflow": float, "positive_flow_count": int,
       "negative_flow_count": int, "total_symbols": int}
    """
    # OPT-02: 熔断器检查——F17 R62: fund_flow 走 market_data_hub.get_fund_flow（akshare），
    # 旧 gate 查 push2delay 健康是语义错位（fund_flow 被涨跌家数路径熔断 gate 误伤），
    # 改为检查 akshare 源健康；push2delay gate 仅适用于直接走 HTTP 的路径
    from ..services.source_registry import registry as _source_registry
    import time
    from ..core.market_context import EM_PUSH_HOST
    _ = EM_PUSH_HOST  # 域名集中常量引用（避免散落）
    akshare_h = _source_registry._health("akshare")
    if not akshare_h.available(time.time()):
        logger.info("[strategy_design] _compute_fund_flow: akshare circuit open, returning empty")
        return {"total_net_inflow": 0.0, "positive_flow_count": 0,
                "negative_flow_count": 0, "total_symbols": 0}

    from ..core.async_utils import run_sync

    pool = market_data_hub.get_pool()
    if not isinstance(pool, dict):
        logger.warning(
            "[strategy_design] _compute_fund_flow: pool is not a dict (%s), skipping",
            type(pool).__name__,
        )
        return {"total_net_inflow": 0.0, "positive_flow_count": 0,
                "negative_flow_count": 0, "total_symbols": 0}

    # 收集所有 symbol
    all_symbols = []
    for layer, items in pool.items():
        for item in items:
            sym = item.get("symbol", "")
            if sym:
                all_symbols.append(sym)

    if not all_symbols:
        return {"total_net_inflow": 0.0, "positive_flow_count": 0,
                "negative_flow_count": 0, "total_symbols": 0}

    # 并发获取所有 fund flow（Semaphore 限流）
    from ..services.market_data_hub import market_data_hub

    async def _fetch_one(sym: str) -> dict | None:
        async with _fund_flow_sem:  # OPT-04: 最多 8 个并发
            try:
                return await run_sync(market_data_hub.get_fund_flow, sym, timeout=8)
            except Exception:
                return None

    results = await asyncio.gather(*[_fetch_one(s) for s in all_symbols],
                                  return_exceptions=True)

    total_net_inflow = 0.0
    positive_count = 0
    negative_count = 0

    for flow in results:
        if isinstance(flow, dict) and flow.get("main_net_inflow") is not None:
            inflow = flow["main_net_inflow"]
            total_net_inflow += inflow
            if inflow >= 0:
                positive_count += 1
            else:
                negative_count += 1

    return {
        "total_net_inflow": total_net_inflow,
        "positive_flow_count": positive_count,
        "negative_flow_count": negative_count,
        "total_symbols": len(all_symbols),
    }


async def _build_market_context(market_data_hub) -> dict:
    """从 market_data_hub 构建市场上下文（真异步）。

    F1-3: ①index_realtime 为空时从全球指数分组兜底（缓存未刷新场景）；
    ②benchmark_stocks 填充领涨/领跌指数成分（此前恒为空数组，LLM 无大盘龙头信号）。
    """
    fund_flow = await _compute_fund_flow(market_data_hub)

    index_realtime = market_data_hub.get_index_realtime() or []
    # F1-3: 缓存未刷新/为空时从全球指数分组兜底（A 股区域）
    if not index_realtime:
        try:
            global_idx = await asyncio.wait_for(market_data_hub.get_global_indices(), timeout=15) or {}
            index_realtime = global_idx.get("A股", []) or []
        except Exception as e:
            logger.debug("[strategy_design] global indices fallback failed: %s", e)

    # F1-3: 领涨/领跌板块头部成分作为 benchmark_stocks（龙头股信号）
    benchmark_stocks: list[dict] = []
    try:
        sector_momentum = market_data_hub.get_sector_momentum() or []
        top_sectors = sorted(
            [s for s in sector_momentum if isinstance(s.get("change_pct"), (int, float))],
            key=lambda s: -s["change_pct"],
        )[:2] + sorted(
            [s for s in sector_momentum if isinstance(s.get("change_pct"), (int, float))],
            key=lambda s: s["change_pct"],
        )[:1]
        for sec in top_sectors:
            code = sec.get("sector_code") or sec.get("code") or ""
            if not code:
                continue
            try:
                stocks = market_data_hub.get_sector_stocks(code) or []
                for st in stocks[:3]:
                    benchmark_stocks.append({
                        "symbol": st.get("stock_code") or st.get("code", ""),
                        "name": st.get("stock_name") or st.get("name", ""),
                        "sector": sec.get("sector_name") or sec.get("name", ""),
                    })
            except Exception:
                continue
    except Exception as e:
        logger.debug("[strategy_design] benchmark_stocks build failed: %s", e)

    # P1-7 (round20): 池层覆盖对照——当日强势板块（涨幅前 3）vs 候选池 ETF 覆盖。
    # 当日领涨板块（如医药 +7%）若无对应主题 ETF 在候选池 → 报告显性标注
    # （「强势板块无对应候选 → WARN」），避免「板块榜进 market_context 但不参与
    # 候选筛选」的隐形脱节（round20 D-A3）。
    _pool_coverage: list[dict] = []
    try:
        _pool = market_data_hub.get_pool()
        _pool_flat = [it for lst in (_pool or {}).values() for it in (lst or [])]
        _pool_texts = [
            f"{it.get('name', '')} {it.get('industry', '')} {it.get('tracked_index', '')}"
            for it in _pool_flat
        ]
        _sm = market_data_hub.get_sector_momentum() or []
        _top3 = sorted(
            [s for s in _sm if isinstance(s.get("change_pct"), (int, float))],
            key=lambda s: -s["change_pct"],
        )[:3]
        for _sec in _top3:
            _sn = str(_sec.get("sector_name") or _sec.get("name") or "")
            if not _sn:
                continue

            def _cov(texts, sn, n=2):
                sn_ng = {sn[i:i + n] for i in range(max(1, len(sn) - n + 1))}
                for _t in texts:
                    tx_ng = {_t[i:i + n] for i in range(max(1, len(_t) - n + 1))}
                    if sn_ng & tx_ng:
                        return True
                return False

            _covered = _cov(_pool_texts, _sn) if _pool_texts else False
            _pool_coverage.append({
                "sector_name": _sn,
                "change_pct": _sec.get("change_pct"),
                "covered_in_pool": _covered,
                "note": "" if _covered else "强势板块无对应候选ETF（WARN）",
            })
    except Exception as _e:
        logger.debug("[strategy_design] pool coverage report failed (non-fatal): %s", _e)

    return {
        "market_regime": market_data_hub.get_market_regime() or "range_bound",
        "market_sentiment": market_data_hub.get_market_sentiment() or {"sentiment_index": 50, "sentiment_label": "中性"},
        "index_realtime": index_realtime,
        "sector_momentum": market_data_hub.get_sector_momentum() or [],
        "fund_flow": fund_flow,
        "benchmark_stocks": benchmark_stocks[:9],
        # P1-7: 强势板块 vs 候选池覆盖对照（D-A3 显性化）
        "strong_sector_pool_coverage": _pool_coverage,
        # P1-9 (round20 §五 P1-9): 因子数据完整性降级标注——valid 率 < 60% 时
        # 方案显式标注「因子数据不完整，方案仅供参考」；基准样本 < MIN 时不标注
        # （避免数据积累期误报）。
        "factor_data_quality": _factor_data_quality_report(),
    }


def _factor_data_quality_report() -> dict:
    """P1-9 (round20 §五 P1-9): 因子 valid 率统计 + 完整性降级标注。

    复用 factors router 的 _status_of 判定（权威状态来源），统计 valid/warn/
    static/no_data 分布；valid 率 = valid / 非 static 因子数（static 为「设计为
    静态」，不参与有效性评估）。valid 率 < 60% → degraded=True + 降级说明。
    纯计算，无 I/O（IC 值从 registry 内存/DB 读）。
    """
    try:
        from ..factors.factor_registry import registry as _freg
        from ..routers.factors import _status_of, STATIC_FACTOR_CODES, MARKET_LEVEL_FACTOR_CODES

        _factors = getattr(_freg, "_factors", {}) or {}
        _design_static = STATIC_FACTOR_CODES | MARKET_LEVEL_FACTOR_CODES
        _ic_series = getattr(_freg, "_ic_series_cache", {}) or {}
        counts = {"valid": 0, "warn": 0, "static": 0, "no_data": 0}
        for _code in _factors:
            _ic = _ic_series.get(_code)
            _icv = None
            if isinstance(_ic, dict):
                _icv = _ic.get("ic")
            elif isinstance(_ic, (list, tuple)) and _ic:
                # 真实结构：{code: [ic_float, ...]}（最新在前）；取最近一个非 None
                for _v in reversed(_ic):
                    if _v is not None:
                        _icv = float(_v)
                        break
            _st, _ = _status_of(_code, _icv, 0.02)
            counts[_st] = counts.get(_st, 0) + 1
        _non_static = counts["valid"] + counts["warn"] + counts["no_data"]
        _valid_rate = round(counts["valid"] / _non_static, 4) if _non_static else 0.0
        _degraded = _non_static > 0 and _valid_rate < 0.6
        return {
            "total": len(_factors),
            "valid": counts["valid"],
            "warn": counts["warn"],
            "static": counts["static"],
            "no_data": counts["no_data"],
            "valid_rate": _valid_rate,
            "degraded": _degraded,
            "note": (
                f"因子数据完整性降级：valid 率 {_valid_rate:.0%} < 60%，方案仅供参考"
                if _degraded else
                f"因子数据完整性正常（valid 率 {_valid_rate:.0%}）"
            ),
        }
    except Exception as _e:
        logger.debug("[strategy_design] factor data quality report failed (non-fatal): %s", _e)
        return {"total": 0, "valid": 0, "warn": 0, "static": 0, "no_data": 0,
                "valid_rate": 0.0, "degraded": False, "note": "因子数据质量统计不可用"}


def _validate_target_amount_consistency(strategies: list[dict], capital: float) -> list[str]:
    """验证所有策略的 target_amount = capital * weight，返回不一致的警告列表。"""
    warnings: list[str] = []
    for s in strategies:
        sid = s.get("id", "unknown")
        for a in s.get("etfs", []):
            if a.get("symbol") == "CASH":
                continue
            w = a.get("weight", 0)
            expected = round(capital * w, 2)
            actual = a.get("target_amount", 0)
            if abs(actual - expected) > 0.01:
                msg = (
                    f"[target_amount] {sid}/{a.get('symbol')}: "
                    f"expected {expected} (capital={capital} * weight={w}), "
                    f"got {actual}"
                )
                warnings.append(msg)
                logger.warning(msg)
    return warnings


def _find_candidate_meta(symbol: str, candidates: dict) -> dict | None:
    """在候选池中查找 ETF 元数据。"""
    for layer_list in candidates.values():
        for c in layer_list:
            if c.get("symbol") == symbol:
                return c
    return None


def _correlation_medians_for(allocs: list[dict], candidates: dict) -> dict[str, float | None]:
    """round19 P1-② (2026-08-12): 方案内非 CASH 标的与同方案其它持仓的中位数相关性。

    数据源：market_data_hub.get_history（日 K，含 fallback 链）→ engine/correlation.py
    correlation_matrix。供 build_rationale 的 correlation_median 参数——黄金/防御型
    标的「与组合低相关」措辞依赖它（此前参数恒 None → 措辞恒禁用，review 接线）。
    性能控制：会话内缓存 closes（5min）+ 4 并发拉取（design 冷态不逐标的串行 5s），
    失败跳过（缺失标的不参与，返回空 dict → correlation_median=None 不影响）。
    """
    from ..engine.correlation import correlation_matrix, median_correlation_for
    from ..fetchers.china_market import run_in_thread
    from ..services.market_data_hub import market_data_hub
    import concurrent.futures

    codes: list[str] = [
        str(a.get("symbol"))
        for a in allocs
        if a.get("symbol") not in (None, "CASH")
    ]
    if len(codes) < 2:
        return {}

    global _CORR_CLOSES_CACHE, _CORR_CLOSES_TS
    _now = time.time()
    if _now - _CORR_CLOSES_TS > 300:
        _CORR_CLOSES_CACHE = {}
        _CORR_CLOSES_TS = _now

    missing = [c for c in codes if c not in _CORR_CLOSES_CACHE]
    if missing:

        def _fetch(code: str) -> tuple[str, list[float]]:
            try:
                meta = _find_candidate_meta(code, candidates) or {}
                mkt = str(meta.get("asset_type") or "A").upper()
                if mkt in ("ETF", "FUND", "A-SHARE"):
                    mkt = "A"
                rows = run_in_thread(
                    lambda c=code, m=mkt: market_data_hub.get_history(c, market=m),
                    timeout=5, executor="short",
                ) or []
                closes = [float(r.get("close")) for r in rows if r.get("close") is not None]
                return code, closes
            except Exception:
                return code, []

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as _ex:
            for _code, _closes in _ex.map(_fetch, missing):
                if len(_closes) >= 20:
                    _CORR_CLOSES_CACHE[_code] = _closes

    closes_by_symbol = {c: _CORR_CLOSES_CACHE[c] for c in codes if c in _CORR_CLOSES_CACHE}
    if len(closes_by_symbol) < 2:
        return {}
    try:
        matrix = correlation_matrix(closes_by_symbol, window=60)
    except Exception:
        return {}
    others_by_code: dict[str, list[str]] = {c: [x for x in codes if x != c] for c in codes}
    return {c: median_correlation_for(matrix, c, others_by_code[c]) for c in codes}


def _correlation_matrix_for(allocs: list[dict], candidates: dict) -> dict[tuple[str, str], float | None]:
    """round20 P1-1: 方案内两两标的的相关性矩阵（复用 _correlation_medians_for 的
    _CORR_CLOSES_CACHE，不重复拉 K 线）。供 enforce_max_correlation 高相关对约束。

    数据缺失（缓存空 / <2 只 / 计算失败）→ 返回 {}，enforce_max_correlation 静默跳过
    （correlation_warnings 不出现，不影响方案有效性）。
    """
    from ..engine.correlation import correlation_matrix as _cm

    codes = [
        str(a.get("symbol")) for a in allocs
        if a.get("symbol") not in (None, "CASH")
    ]
    if len(codes) < 2:
        return {}
    closes_by_symbol = {c: _CORR_CLOSES_CACHE[c] for c in codes if c in _CORR_CLOSES_CACHE}
    if len(closes_by_symbol) < 2:
        return {}
    try:
        matrix = _cm(closes_by_symbol, window=60)
    except Exception:
        return {}
    return matrix


_CORR_CLOSES_CACHE: dict[str, list[float]] = {}
_CORR_CLOSES_TS = 0.0
