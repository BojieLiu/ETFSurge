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

from ..core.market_calendar import market_session
from ..engine.allocation_engine import (
    MANDATORY_CODES,
    apply_near_substitute_warnings,
    check_structure_reasonableness,
    enforce_max_correlation,
    wide_basis_high_corr_warnings,
)
from ..engine.allocation_engine import (
    allocate as engine_allocate,
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
            "description": f"{meta.get('positioning', '')}（静态池兜底方案，预期收益未测算）",
            "risk_profile": profile,
            # round23 遗留修复：原为 f"{...*100:.0f}-{...}%" str 展示串——数值消费方
            # （design_report._build_plan_tables）会 ValueError → 设计任务 failed。
            # 改为 None（诚实：兜底方案无历史收益测算），展示层渲染 "—"。
            "expected_return": None,
            "expected_volatility": "12-20%",
            "etfs": allocs,
        })
    return strategies


def build_static_degraded_design(capital: float, reason: str) -> dict:
    """R69 (round29): 零网络的降级方案（数据采集连续超时后的最后一层兜底）。

    旧行为：`design_pipeline` 二次采集也超时 → `status=failed, error="方案生成超时"`，
    盘后/冷启动首呼拿不到任何方案。本函数用静态核心池（纯 CPU、无 I/O）产出 3 套
    可执行方案 + `degradation.mode="degraded"`，诚实标注数据源降级而非伪装正常。
    """
    strategies = _build_static_pool_strategies(capital)
    _now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "strategies": strategies,
        "market_context": {"degradation_note": reason},
        "generated_at": _now_iso,
        "design_metadata": {
            "version": "v5-engine-static-degraded",
            "elapsed_seconds": 0.0,
            "fallback": True,
        },
        "degradation": {
            "mode": "degraded",
            "reason": reason,
            "factor_matrix_empty": True,
            "pool_empty": True,
            "pool_degraded": True,
            "static_pool_used": [str(e.get("symbol", "")) for e in STATIC_CORE_POOL if e.get("symbol")],
            "timestamp": _now_iso,
        },
    }


async def generate_enhanced_design(
    capital: float = 500000,
    constraints: dict | None = None,
    market: str = "A",
    skip_refresh: bool = False,
) -> dict:
    """
    v5 编排器：数据管道 → 策略引擎 → 持久化返回。

    Phase 5.1: 增加 market 参数入口，当前仅 A 股有候选池。
    R59② (round28): 增加 skip_refresh 参数——数据采集超时后的**降级重试**路径。
    task_manager 的 DESIGN_DATA_TIMEOUT 超时后不再直接 failed，而是以
    skip_refresh=True 重试：跳过 market_data_hub.refresh()（避免再次撞慢源），
    用内存 last-good pool / T-1 快照 / 静态池产出降级方案（degradation 标记），
    使盘后/冷启动首呼 design 永远能拿到「可用方案」而非「方案生成超时」失败。
    """
    import time
    start_time = time.monotonic()
    constraints = constraints or {}
    _elapsed_logged = False

    # 1. 刷新数据管道（pipeline Stage 1 负责超时保护）
    from ..services.market_data_hub import market_data_hub
    _t1 = time.monotonic()
    if skip_refresh:
        # R59② (round28): 降级重试路径——跳过 refresh()（避免再次撞慢源/超时），
        # 直接用内存 last-good pool；若内存为空则靠 T-1 快照/静态池兜底（下方 2b）。
        # 标记 degraded 供 degradation 输出与前端「数据源冷却」提示。
        market_data_hub._degraded = True
        logger.info("[strategy_design] skip_refresh=True — using last-good/snapshot pool (R59② degrade retry)")
    else:
        # R59⑤ (round28): 盘后显式降级——非交易时段且已有 last-good pool 时，
        # 主动走快照/缓存路径（不尝试实时源干等超时，避免盘后四源冷却叠加冷缓存
        # 把 90s 预算吃光）。仅当 pool 为空（首启）才尝试 refresh()（内部有 T-1
        # 快照兜底）。is_market_hours 复用 market_data_hub 的 A 股交易时段判断。
        _off_hours = True
        try:
            _off_hours = not market_data_hub._is_market_hours()
        except Exception:
            _off_hours = False
        # R59⑤: 用 getattr 防御——测试注入的假 hub 可能无 _pool 属性
        #（test_portfolio_precision / test_round25_r41 用 _FakeHub 替换单例）
        _pool_nonempty = bool(
            getattr(market_data_hub, "_pool", None)
            and any(v for v in (getattr(market_data_hub, "_pool", None) or {}).values() if v)
        )
        if _off_hours and _pool_nonempty:
            market_data_hub._degraded = True
            logger.info(
                "[strategy_design] off-hours + pool cached — skipping realtime refresh, "
                "using last-good pool (R59⑤ off-hours degrade, %d by_code)",
                len(market_data_hub._by_code),
            )
        else:
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

    # 2b. 检查候选池 / 因子矩阵是否为空（Z11: 空池或因子矩阵全空 → 静态池兜底 + degradation 标记）
    # R77 修复（round29）：factor_matrix_empty 改判内层——
    # {"510300":{}} 等「外层非空、内层全空」的矩阵视为因子数据不可用，触发静态池兜底，
    # 从源头避免进入 allocate 产出现金（100% 现金假失败）。
    total_candidates = sum(len(v) for v in candidates.values())
    factor_matrix_empty = not any(v for v in factor_matrix.values())
    pool_empty = total_candidates == 0
    static_pool_used: list[str] = []
    if total_candidates == 0 or factor_matrix_empty:
        reason = "empty candidate pool" if total_candidates == 0 else "factor matrix empty (data source unavailable)"
        logger.warning("[strategy_design] %s — falling back to static pool", reason)
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
                "非交易时段/数据管道为空：候选池为空，使用静态核心池兜底" if pool_empty
                else "因子数据源不可用（因子矩阵全空），使用静态核心池兜底",
            ),
        }

    try:
        # 3. 策略引擎：一次调用生成所有方案
        _t3 = time.monotonic()
        # A1 (round23 §10.1): 引擎纯度——definitions/ic_series 在此从 registry 读一次注入
        from ..factors.factor_registry import registry as _freg_global
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
            # A1 (round23 §10.1): engine 纯度参数化——从 registry 读一次注入
            #（definitions/ic_series），engine 内不再 import factor_registry 私有态。
            factor_definitions=getattr(_freg_global, "_factors", None) or {},
            ic_series=getattr(_freg_global, "_ic_series_cache", None),
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
                # round35 B1-F5 (§4.5 D5): 转发引擎侧 rank_info（层内排名 N/M +
                # 主驱动因子）——恢复 O24 归因链；pop 防内部键泄漏到 API 输出。
                _rank_info = a.pop("_rank_info", None)
                a["selection_rationale"] = build_rationale(
                    code=code,
                    layer=a.get("layer", "satellite"),
                    strategy=s.get("id", "balanced"),
                    meta=sym_meta,
                    factor_scores=a.get("factor_breakdown", {}),
                    regime=market_regime,
                    industry=sym_meta.get("industry", "") if sym_meta else None,
                    correlation_median=corr_medians.get(code),
                    rank_info=_rank_info,
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
                # round22 E5 (docs/archived/engine-refactor-spec-round22.md §1 E5): 非交易窗口 / K 线相关性
                # 矩阵缺失（_correlation_matrix_for 返回空）——相关性约束**不得静默跳过**，
                # 降级标注 correlation_unchecked=True（前端提示「关联度未校验」），不阻塞主链路。
                _strat_proxy.setdefault("risk_metrics", {})["correlation_unchecked"] = True

            # round25 R41-a: 近替代品冗余控制——独立冗余控制层，**无条件执行**（不依赖
            # corr_matrix）。盘后/非交易窗口 corr_matrix 为空时近替代品检测不再被连带跳过
            #（旧实现嵌套在 enforce_max_correlation 内，该函数只在 `if corr_matrix:` 时
            # 调用 → 盘后「芯片+半导体设备」等同主题双入选无告警）。r 缺失标 unevaluated。
            try:
                apply_near_substitute_warnings([_strat_proxy], corr_matrix or {})
            except Exception as _e:
                logger.debug("[strategy_design] near-substitute warnings skipped: %s", _e)

            # R101 (round32): 核心层宽基 >0.95 高相关配对提示（软约束，非硬剔除）——
            # 与 enforce_max_correlation 的高相关权重削减正交：即使合计权重未超阈值，
            # 沪深300×中证A500 等不同宽基指数并存也显式提示「分散有限」（不静默）。
            # corr_matrix 为空（盘后无相关性数据）→ 无提示（诚实，不误报）。
            try:
                _wb_warnings = wide_basis_high_corr_warnings(allocs, corr_matrix or {})
                if _wb_warnings:
                    _strat_proxy.setdefault("risk_metrics", {})
                    _strat_proxy["risk_metrics"]["correlation_warnings"] = (
                        _strat_proxy["risk_metrics"].get("correlation_warnings", [])
                        + _wb_warnings
                    )
            except Exception as _e:
                logger.debug("[strategy_design] wide-basis high-corr warnings skipped: %s", _e)

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
                            # R105 A'-2 (round34): 强制锚豁免清零——三源拿不到涨跌时锚
                            # 保留权重 + WARNING（degraded），否则防御型方案核心层宽基
                            # 锚被剥除 → M7/P1-1 四连 FAIL（round34 §4.3 段二备选嫌疑）。
                            if a.get("symbol") in MANDATORY_CODES:
                                logger.warning(
                                    "[design] mandatory anchor %s lacks daily change — "
                                    "core weight kept (degraded)",
                                    a.get("symbol"),
                                )
                                continue
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
            # round27 R47: coarse 态结构化字段桶化（与 data_precision 一致）；
            # exact 态原值不变。此后按桶后权重重算 target_amount 保持内部一致。
            _prec = market_context.get("data_precision") or {}
            if _prec.get("mode") == "coarse":
                _apply_precision_bucketing(allocs, _prec)
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

        # R77 收口 (round29): 因子矩阵全空时 allocate 无评分可算，产出往往是
        # 「100% 现金」空壳（task_manager 判 valid_count==0 → failed）。此处后置
        # 守卫：确认全现金后改用静态等权方案（诚实可执行），并标 static_pool。
        # 注：仅当策略确为全现金才替换——E5 类测试 stub 出的非现金方案不受影响。
        if factor_matrix_empty and strategies:
            _all_cash = all(
                not [e for e in (s.get("etfs") or []) if e.get("symbol") != "CASH"]
                for s in strategies
            )
            if _all_cash:
                logger.warning(
                    "[strategy_design] factor matrix empty + allocate produced 100%% cash — "
                    "replacing with static pool strategies (R77 guard)"
                )
                strategies = _build_static_pool_strategies(capital)
                return {
                    "strategies": strategies,
                    "market_context": market_context,
                    "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "design_metadata": {
                        "version": "v5-engine-static-pool",
                        "elapsed_seconds": round(time.monotonic() - start_time, 1),
                        "regime": market_regime,
                        "fallback": True,
                    },
                    "degradation": _degradation(
                        "static_pool",
                        "因子数据源不可用（因子矩阵全空且引擎产出全现金），使用静态核心池兜底",
                    ),
                }

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
            # Z11: 正常路径也暴露 degradation（mode=normal / partial_data / degraded）
            "degradation": _degradation(
                "degraded" if skip_refresh else ("partial_data" if partial_data else "normal"),
                "盘后数据源冷却/采集超时，使用最近缓存快照（R59② 降级重试）"
                if skip_refresh
                else ("部分候选标的缺因子分：缺失因子按 0 填充"
                      if partial_data else "正常数据管道"),
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
        except Exception:
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
    import time

    from ..core.market_context import EM_PUSH_HOST
    from ..core.source_registry import registry as _source_registry
    _ = EM_PUSH_HOST  # 域名集中常量引用（避免散落）
    akshare_h = _source_registry.health("akshare")
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
    for _layer, items in pool.items():
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

    # R104 (round34): fdq 样本数改读 DB 口径（count distinct trade_date）——旧实现读
    # registry 内存 `_sample_counts`（compute 截面计数 ≤池规模 ~15），与 /factors/active
    # 的 DB 口径（444-502 交易日）分裂 30×+，note 恒「积累中」永不翻转。DB 不可用回退
    # 内存（db_sample_counts=None → 旧行为），不阻断设计主链路。
    _db_counts: dict | None = None
    try:
        from ..database import async_session
        from ..factors.ic_tracker import ic_tracker as _ic_tracker

        async with async_session() as _db:
            _db_counts = await _ic_tracker.get_sample_counts_by_code(_db)
    except Exception as _e:  # noqa: BLE001 - 元数据查询失败不阻断设计
        logger.debug("[strategy_design] db sample counts unavailable: %s", _e)
    _fdq = _factor_data_quality_report(db_sample_counts=_db_counts)
    # round24 R26③: 显式盘后模式 + 数据时效——透传 session 与 data_as_of（反 R3 假实时）。
    # 盘后/熔断设计必须标注「数据截至 T-1（15:30）」，避免精确数字冒充实时。
    try:
        from ..services.market_data_hub import _snapshot_as_of_for
        data_as_of = _snapshot_as_of_for()
    except Exception:
        data_as_of = None
    _session = market_session()
    return {
        "market_regime": market_data_hub.get_market_regime() or "range_bound",
        "market_sentiment": market_data_hub.get_market_sentiment() or {"sentiment_index": 50, "sentiment_label": "中性"},
        "index_realtime": index_realtime,
        "sector_momentum": market_data_hub.get_sector_momentum() or [],
        "fund_flow": fund_flow,
        "benchmark_stocks": benchmark_stocks[:9],
        # round24 R26③: 显式盘后模式与数据时效
        "session": _session,
        "data_as_of": data_as_of,
        # P1-7: 强势板块 vs 候选池覆盖对照（D-A3 显性化）
        "strong_sector_pool_coverage": _pool_coverage,
        # P1-9 (round20 §五 P1-9): 因子数据完整性降级标注——valid 率 < 60% 时
        # 方案显式标注「因子数据不完整，方案仅供参考」；基准样本 < MIN 时不标注
        # （避免数据积累期误报）。
        "factor_data_quality": _fdq,
        # round24 R3: 精度降级标识——降级态不得再以「精确到 1% 的权重 + 两位小数因子分」
        # 呈现（契约 api-contracts/portfolio/design-precision.md）。只影响呈现，
        # allocations[].target_weight 原值不变。
        "data_precision": _data_precision_report(_fdq),
    }


# round24 R3: 因子 valid 率降级阈值（与 _factor_data_quality_report 的 0.6 同源）
_PRECISION_VALID_RATE_FLOOR = 0.6
# round24 R3: 降级态权重呈现档位（百分点）——5% 步进，杜绝「21.0%」假精确
_COARSE_WEIGHT_STEP_PCT = 5.0


def _data_precision_report(factor_quality: dict | None) -> dict:
    """round24 R3: 由因子数据质量派生「呈现精度」标识（纯函数，无 I/O）。

    背景（round24 §2.1 实证）：design 570 `valid_rate=0.0%` + 「方案仅供参考」横幅，
    但 UI 仍给出 5%/15%/21% 精确权重与 -0.99/-0.96 精确因子分——降级诚实了、数字
    没诚实，专业投资者无法分辨「哪个数字可信」。

    判定：`degraded=True` 或 `valid_rate < 0.6` → mode=coarse（权重按 5% 档位、
    因子分按强弱分档呈现 + 缺失百分比红字）；否则 exact（现状不变）。
    输入缺失/不可用（None/空 dict/无 valid_rate）→ exact，**不误报降级**。
    """
    _fq = factor_quality if isinstance(factor_quality, dict) else {}
    _rate_raw = _fq.get("valid_rate")
    if not isinstance(_rate_raw, (int, float)):
        # 统计不可用：无从判断完整性，按 exact 处理（负向：不得误报降级）
        return {
            "mode": "exact",
            "factor_valid_rate": None,
            "factor_missing_pct": None,
            "weight_display": "exact",
            "weight_step_pct": None,
            "factor_score_display": "exact",
            "note": "因子数据质量统计不可用，权重与因子分按原值呈现",
        }
    _rate = max(0.0, min(1.0, float(_rate_raw)))
    _missing_pct = round((1.0 - _rate) * 100, 1)
    _degraded = bool(_fq.get("degraded")) or _rate < _PRECISION_VALID_RATE_FLOOR
    if _degraded:
        return {
            "mode": "coarse",
            "factor_valid_rate": _rate,
            "factor_missing_pct": _missing_pct,
            "weight_display": "coarse",
            "weight_step_pct": _COARSE_WEIGHT_STEP_PCT,
            "factor_score_display": "bucket",
            "note": (
                f"因子数据缺失 {_missing_pct:g}%：权重按 "
                f"{_COARSE_WEIGHT_STEP_PCT:g}% 档位粗略呈现、因子分仅显示强弱分档，"
                "不代表精确配置"
            ),
        }
    return {
        "mode": "exact",
        "factor_valid_rate": _rate,
        "factor_missing_pct": _missing_pct,
        "weight_display": "exact",
        "weight_step_pct": None,
        "factor_score_display": "exact",
        "note": f"因子数据完整性正常（valid 率 {_rate:.0%}），权重与因子分为精确值",
    }


def _factor_data_quality_report(db_sample_counts: dict | None = None) -> dict:
    """P1-9 (round20 §五 P1-9): 因子数据质量统计 + 完整性降级标注。

    R96 (round31): 拆「数据可用性」与「IC 积累」两维——旧实现复用 F25② `_status_of`
    IC 样本门禁（样本<250 交易日 → no_data），数据积累期 valid_rate 恒 0%、报
    「缺失 100%」，而 rationale 已引用真实 RSI/动量 → meta 与正文自相矛盾（§4.4
    实证）。R85 修复后**数据可用 ≠ IC 积累**，指标未拆两维。
      - 数据可用性（valid_rate 口径）：所需数据字段是否就位（无 `_data_source_gaps`
        缺口、非 `_constant_factor_codes` 常量）。R85 后技术因子有值 → 可用率 >0，
        不再误导；
      - IC 积累：独立标注「样本 N/250 交易日」（`_status_of` 判定，随运行逐步翻绿）。

    R100 (round32): 数据可用性口径从「定义层 _data_source_gaps」改为「compute()
    实际产出」（`_last_compute_produced`）——盘后 etf.return_* 未产出但无 gap 标注，
    旧口径报「97% 可用」掩盖 factor_breakdown 占位退化（设计 697 实证）。新增
    `definition_ready_pct`（定义就位率）与 `actual_output_rate`（实际产出率）并列，
    口径脱节显性化。

    R104 (round34): 样本数单一事实源=DB——调用方（_build_market_context）注入 DB
    口径 counts（ic_tracker.get_sample_counts_by_code，与 /factors/active 同源）；
    None（未注入/DB 不可用）回退 registry 内存 `_sample_counts`（旧行为兼容）。

    保留 total/valid/warn/static/no_data 键（向后兼容）；新增 data_available /
    data_available_pct / ic_accumulation / definition_ready* / actual_output_rate。
    纯计算，无 I/O（IC 值从 registry 内存/DB 读）。
    """
    try:
        import statistics

        from ..factors.factor_registry import registry as _freg
        from ..factors.factor_status import (  # round35 B1-C3: 单源（原 routers 反向 import）
            MARKET_LEVEL_FACTOR_CODES,
            MIN_TRADING_DAYS,
            STATIC_FACTOR_CODES,
            status_of,
        )
        from ..factors.ic_tracker import compute_series_stats

        _factors = getattr(_freg, "_factors", {}) or {}
        _design_static = STATIC_FACTOR_CODES | MARKET_LEVEL_FACTOR_CODES
        _ic_series = getattr(_freg, "_ic_series_cache", {}) or {}
        # R104 (round34): 样本数单一事实源=DB（count distinct trade_date）；调用方未注入
        # （None）时回退 registry 内存 `_sample_counts`（旧行为，兼容单测/无 DB 场景）。
        # 内存值语义是「compute 截面计数」（≤池规模），非累计交易日——不得与 DB 口径混用。
        _sample_counts = (
            dict(db_sample_counts) if db_sample_counts is not None
            else getattr(_freg, "_sample_counts", {}) or {}
        )
        _gaps = getattr(_freg, "_data_source_gaps", {}) or {}
        _constant: set[str] = set(getattr(_freg, "_constant_factor_codes", set()) or set())
        # R100 (round32): compute() 实际产出（非 None 数值）的因子键数——
        # 数据可用性统计以此为准（对齐 factor_breakdown 真实值），而非定义层
        # _data_source_gaps（盘后 etf.return_* 未产出但无 gap 标注 → 97% 掩盖占位）。
        _produced = getattr(_freg, "_last_compute_produced", None) or {}
        _have_produced = bool(_produced)
        counts = {"valid": 0, "warn": 0, "static": 0, "no_data": 0}
        definition_ready = 0
        _ic_samples: list[int] = []
        for _code in _factors:
            _ic = _ic_series.get(_code)
            _icv = None
            _ser = None
            if isinstance(_ic, dict):
                _icv = _ic.get("ic")
            elif isinstance(_ic, (list, tuple)) and _ic:
                # 真实结构：{code: [ic_float, ...]}；round35 FM1 起缓存契约=旧→新，
                # reversed 后从新到旧遍历 → 首个非 None = 最新非 None 值
                for _v in reversed(_ic):
                    if _v is not None:
                        _icv = float(_v)
                        break
                _ser = compute_series_stats([float(v) for v in _ic if v is not None])
            _st, _ = status_of(
                _code,
                samples=int(_sample_counts.get(_code, 0)),
                t_stat=_ser.get("t_stat") if _ser else None,
                ir=_ser.get("ir") if _ser else None,
                ic_val=_icv,
            )
            counts[_st] = counts.get(_st, 0) + 1
            if _st == "static":
                continue
            _n = int(_sample_counts.get(_code, 0) or 0)
            if _n > 0:
                _ic_samples.append(_n)
            # R96: 数据可用性判定——所需字段无缺口（非 _data_source_gaps）且非常量
            # （截面有区分度，非 O20 常量占位）——R100 起此口径为「定义就位率」
            if _code not in _gaps and _code not in _constant:
                definition_ready += 1
        _non_static = counts["valid"] + counts["warn"] + counts["no_data"]
        # R100: 实际产出率 = compute() 产出（非 None 数值）的因子键数 / 定义键数。
        # compute() 未跑过（_produced 空）→ 回退定义就位率（旧行为，不误报降级）。
        _produced_count = 0
        if _have_produced:
            _produced_count = sum(
                1 for _code in _factors
                if int(_produced.get(_code, 0) or 0) > 0
            )
        if _have_produced:
            _actual_output_rate = round(_produced_count / _non_static, 4) if _non_static else 0.0
        else:
            # compute() 未跑过：产出率无从统计——None（诚实「未知」而非假 0%）
            _actual_output_rate = None
        _definition_ready_rate = round(definition_ready / _non_static, 4) if _non_static else 0.0
        # 数据可用性（valid_rate 口径）：R100 A——优先用实际产出口径；compute() 未跑时
        # 回退定义就位率（保持既有测试/无 compute 场景行为）。
        _availability = _produced_count if _have_produced else definition_ready
        _availability_rate = round(_availability / _non_static, 4) if _non_static else 0.0
        _degraded = _non_static > 0 and _availability_rate < 0.6
        _median_samples = int(statistics.median(_ic_samples)) if _ic_samples else 0
        _max_samples = max(_ic_samples) if _ic_samples else 0
        return {
            "total": len(_factors),
            "valid": counts["valid"],
            "warn": counts["warn"],
            "static": counts["static"],
            "no_data": counts["no_data"],
            "valid_rate": _availability_rate,
            "degraded": _degraded,
            # R96/R100: 数据可用性维度——R100 A 起以 compute() 实际产出口径为准
            #（对齐 factor_breakdown 真实值）；compute() 未跑时回退定义就位率
            "data_available": _availability,
            "data_available_pct": _availability_rate,
            # R100 B: 「定义就位率」（字段无缺口/非常量）与「实际产出率」并列——
            # 口径脱节显性化：factor_breakdown 退化为占位值时 actual_output_rate 骤降，
            # 不再被 definition_ready_pct 的 97% 掩盖。
            "definition_ready": definition_ready,
            "definition_ready_pct": _definition_ready_rate,
            "actual_output_rate": _actual_output_rate,
            # R96: IC 积累维度独立标注（样本 N/250 交易日）
            "ic_accumulation": {
                "median_samples": _median_samples,
                "max_samples": _max_samples,
                "target_days": MIN_TRADING_DAYS,
                "note": (
                    f"IC 积累中（中位 {_median_samples}/{MIN_TRADING_DAYS} 交易日，"
                    f"最高 {_max_samples}）；t/IR 达标后逐因子翻绿"
                    if _max_samples < MIN_TRADING_DAYS
                    else f"IC 样本充足（中位 {_median_samples} 交易日），待 t/IR 显著"
                ),
            },
            "note": (
                f"因子数据完整性降级：数据可用率 {_availability_rate:.0%} < 60%，方案仅供参考"
                if _degraded else
                f"因子数据完整性正常（数据可用率 {_availability_rate:.0%}）"
            ),
        }
    except Exception as _e:
        logger.debug("[strategy_design] factor data quality report failed (non-fatal): %s", _e)
        return {"total": 0, "valid": 0, "warn": 0, "static": 0, "no_data": 0,
                "valid_rate": 0.0, "degraded": False, "note": "因子数据质量统计不可用"}


# round27 R47: 降级态（coarse）结构化字段桶化——etfs[].weight / etfs[].factor_score
# 须与 data_precision（coarse/bucket）保持一致（此前 design_text 已桶化、结构化字段仍精确，
# 与元数据矛盾）。exact 态原值不变。target_amount 由调用方按桶后权重重算以保持一致。
def _bucket_factor_score_label(fs: float) -> str:
    """因子分强弱分档（与 design_report._build_plan_tables / 前端 factorBucket 同源）。"""
    if fs >= 0.5:
        return "偏强"
    if fs <= -0.5:
        return "偏弱"
    return "中性"


def _apply_precision_bucketing(etfs: list[dict], precision: dict) -> None:
    """R47: mode=coarse 时把结构化字段按呈现精度桶化（in-place，无 I/O）。

    - etfs[].weight → 5% 档位（0.2067 → 0.20）；
    - etfs[].factor_score → 强弱分档字符串（偏强/中性/偏弱）。
    exact 态（或字段缺失/非数字）原值不变。
    """
    if not isinstance(precision, dict) or precision.get("mode") != "coarse":
        return
    step = (precision.get("weight_step_pct") or 5.0) / 100.0
    for a in etfs:
        if a.get("symbol") == "CASH":
            continue
        w = a.get("weight")
        if isinstance(w, (int, float)):
            a["weight"] = round(round(w / step) * step, 4)
        fs = a.get("factor_score")
        if isinstance(fs, (int, float)):
            a["factor_score"] = _bucket_factor_score_label(fs)


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
    import concurrent.futures

    from ..engine.correlation import correlation_matrix, median_correlation_for
    from ..fetchers.china_market import run_in_thread
    from ..services.market_data_hub import market_data_hub

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
