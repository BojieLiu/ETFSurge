"""Factor analysis and IC tracking routes."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database import get_db
from ..factors.factor_registry import registry, ET_SPECIFIC_GAP_CODES
from ..factors.ic_tracker import ic_tracker as _ic_tracker
from ..factors.ic_tracker import compute_series_stats

# F19 R70: code → 缺失字段名映射（泛化：ln_mcap 等非 etf_specific 因子也有缺口标注）
GAP_FIELD_MAP = {
    "style.size.ln_mcap": "fund_scale/total_mv",
    "style.size.ln_float_mcap": "float_mv",
}

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/factors", tags=["factors"])

# F25② (round23 §8): IC 显著性判据业内对齐——替换旧 `MIN_IC_SAMPLES=30`（刷新次数
# 冒充交易日，开机 1h 即跨过 →「有效 16」无统计含义）。
# - MIN_OBSERVABLE_DAYS=60: 可观察下限（UI 标「积累中（可观察）」）
# - MIN_TRADING_DAYS=250: 有效门槛（约 1 年交易日，对齐业内 t≥2 所需样本量）
# - 且必须 t≥2（95% 置信）AND |IR|≥0.5 才标 valid（文档 F25 设计要点②）
MIN_OBSERVABLE_DAYS = 60
MIN_TRADING_DAYS = 250

# ── Simple TTL-based response cache (60s refresh) ──────────────
_CACHE: dict[str, tuple[float, str, dict]] = {}  # key -> (expiry_ts, etag, body)


def _get_cached(key: str, ttl: int = 60) -> tuple[str, dict] | None:
    """Return (etag, body) if cache is still fresh, else None."""
    entry = _CACHE.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1], entry[2]
    return None


def _set_cache(key: str, etag: str, body: dict, ttl: int = 60) -> None:
    _CACHE[key] = (time.monotonic() + ttl, etag, body)


def _build_cache_key(path: str, params: frozenset | None = None) -> str:
    return f"{path}:{hash(params) if params else ''}"

# 因子模型的科普描述
CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "technical": "技术指标因子：基于价格和成交量的技术分析指标，如均线、MACD、RSI、KDJ、布林带等，用于捕捉价格趋势和反转信号",
    "style": "风格因子：涵盖规模、价值、波动率、流动性、质量、成长六大类，对标 MSCI Barra 和华证因子体系，用于刻画个股的稳定特征",
    "sentiment": "情绪因子：基于新闻舆情和市场情绪数据，捕捉投资者情绪变化对资产价格的影响",
    "momentum": "动量因子：基于历史收益率的延续性，捕捉趋势跟踪和板块轮动效应",
    "valuation": "估值因子：基于基本面数据的估值指标，衡量资产价格相对其内在价值的偏离程度",
    "alternative": "另类数据因子：基于信用卡消费、ESG、专利、招聘、供应链和网络流量等非传统数据源",
    "china_specific": "中国特有因子：针对 A 股市场的特殊特征，如股息质量、政策契合度、国企属性",
    "etf_specific": "ETF 特有因子：针对 ETF 品类的专属分析维度，如折溢价率、规模、跟踪误差",
    "microstructure": "微观结构因子：基于日内交易数据的市场微观结构分析，如订单流、反转效应",
    "theme": "主题因子：聚焦国家战略新兴产业的板块轮动和主题投资信号",
    "macro": "宏观环境因子：基于宏观/政策数据的市场环境维度（M2 货币松紧 / PMI 荣枯线 / LPR 利率周期 / GDP 增速分位），慢变量调节快变量，仅作市态/组合层输入，不参与截面 IC",
}


# Z03: 静态政策标识因子（不计算 IC，status='static'）
STATIC_FACTOR_CODES = {
    "china.policy.five_year_plan",
    "china.policy.strategic_emerging",
    "china.policy.dual_circulation",
}

# P1-10 (round9 §6.5.1-C): 市场级因子——注入的是全市场单一值（sentiment_index/涨跌家数比/
# 全市场新闻）→ 截面恒等（std=0 → IC 不可计算）→ 旧实现标 no_data 误导。
# 设计缺陷：宏观/市场级数据不能作为「每只 ETF 打分」的截面因子。
# 处置：移出截面因子池——不参与截面 IC 判定（参照 static 政策因子），仅作 regime/
# 组合层输入；因子页 reason 明示「市场级因子不参与截面 IC」；待 ETF 级舆情/板块级
# 情绪数据源接入后恢复截面计算。
MARKET_LEVEL_FACTOR_CODES = {
    "sentiment.panic_greed_diff",
    "sentiment.stock_divergence",
    "sentiment.news_direction",
    # round13 §3.1 P2: 宏观环境因子——全市场单一值（M2/PMI/LPR/GDP/两融），截面恒等，
    # 不参与截面 IC，仅作市态/组合层输入（与 sentiment 市场级因子同处置）
    "macro.m2_trend",
    "macro.pmi_level",
    "macro.lpr_direction",
    "macro.gdp_trend",
    "macro.margin_leverage_trend",
}


def _status_of(code: str, samples: int, t_stat: float | None, ir: float | None,
               ic_val: float | None = None) -> tuple[str, str]:
    """Z03: 权威状态 + 原因说明（/active 与 /model 共用）。

    F25② (round23 §8): 显著性判据业内对齐——由「|IC|≥threshold 且 samples≥30」改为
    「交易日数 + t/IR」三档：
    - samples < 60            → no_data（积累中）
    - 60 ≤ samples < 250      → no_data（积累中（可观察））
    - samples ≥ 250 且 t≥2 且 |IR|≥0.5 → valid（统计显著）
    - samples ≥ 250 但 t<2 或 |IR|<0.5 → warn（有样本但统计不显著）

    旧 `MIN_IC_SAMPLES=30`（刷新次数冒充交易日）已废弃——18 天自相关刷新数据
    连 t≥2 的零头都不够，按任何标准都不可能有「有效因子」（文档 §2.5 结论）。
    """
    if code in STATIC_FACTOR_CODES:
        return "static", "静态政策标识因子，不计算 IC"
    if code in MARKET_LEVEL_FACTOR_CODES:
        # P1-10: 市场级因子（全市场单一值/市态级降级）——截面恒等，移出截面 IC 池
        return "static", "市场级因子（全市场单一值），不参与截面 IC，仅作市态/组合层输入"
    if samples <= 0:
        # F3-4 步骤D + F19 R70: 区分「数据源未接入（缺字段）」与「IC 未累积（样本不足）」
        gaps = getattr(registry, "_data_source_gaps", {}) or {}
        missing = gaps.get(code, [])
        if missing:
            field = GAP_FIELD_MAP.get(code, ET_SPECIFIC_GAP_CODES.get(code, "必要字段"))
            return "no_data", f"数据源未接入（{len(missing)} 只样本缺 {field}）"
        # O20: 常量因子独立标注——截面输出全 0/常量 → 无区分度，非样本不足
        constant_gaps = getattr(registry, "_constant_factor_codes", set()) or set()
        if code in constant_gaps:
            return "no_data", "截面无差异（常量输出），检查底层数据"
        return "no_data", "IC 未累积（0 个交易日）"
    if samples < MIN_OBSERVABLE_DAYS:
        return "no_data", f"IC 积累中（{samples}/{MIN_TRADING_DAYS} 交易日，未达可观察下限 {MIN_OBSERVABLE_DAYS}）"
    if samples < MIN_TRADING_DAYS:
        return "no_data", f"IC 积累中（{samples}/{MIN_TRADING_DAYS} 交易日，可观察）"
    # samples ≥ 250：显著性判定（t≥2 且 |IR|≥0.5）
    if t_stat is None or ir is None:
        return "no_data", f"IC 序列不可用（{samples} 交易日但无 t/IR 统计）"
    if abs(ir) >= 0.5 and t_stat >= 2.0:
        return "valid", f"统计显著：t={t_stat:.2f}，IR={ir:.2f}，样本 {samples} 交易日（≥{MIN_TRADING_DAYS}）"
    return "warn", (
        f"有样本但统计不显著：t={t_stat:.2f}，|IR|={abs(ir):.2f}"
        f"（需 t≥2 且 |IR|≥0.5），样本 {samples} 交易日"
    )


async def _db_ic_sample_counts(db) -> dict[str, int]:
    """F25①: 一次查询取全因子 IC 累计交易日数（factor_ic_records 按 code 分组
    `count(distinct trade_date)`——日频 1 行语义）。DB 不可用回退空 dict（调用方回退内存）。"""
    try:
        from ..models.factor_ic import FactorICRecord
        from sqlalchemy import select, func
        rows = (await db.execute(
            select(FactorICRecord.factor_code, func.count(func.distinct(FactorICRecord.trade_date)))
            .group_by(FactorICRecord.factor_code)
        )).all()
        return {r[0]: int(r[1]) for r in rows}
    except Exception as e:  # noqa: BLE001 - DB 查询失败不阻断端点
        logger.warning("[factors] DB IC sample counts failed: %s", e)
        return {}


async def _db_ic_series_stats(db) -> dict[str, dict[str, float]]:
    """F25②: 读 factor_ic_records 日频 IC 序列 → 每因子 {ic_mean,ic_std,ir,t_stat}。

    序列按 (factor_code, trade_date) 排序；signal_absent（近零批次）行 IC 计 0 纳入
    序列（F25③「参与有效天数统计但 IC 计 0」，修复生存者偏差）。DB 不可用返回 {}。
    """
    try:
        from ..models.factor_ic import FactorICRecord
        from sqlalchemy import select
        rows = (await db.execute(
            select(FactorICRecord.factor_code, FactorICRecord.ic_value)
            .order_by(FactorICRecord.factor_code, FactorICRecord.trade_date)
        )).all()
        by_code: dict[str, list[float]] = {}
        for code, icv in rows:
            if icv is None:
                continue
            by_code.setdefault(code, []).append(float(icv))
        out: dict[str, dict[str, float]] = {}
        for code, vals in by_code.items():
            st = compute_series_stats(vals)
            if st:
                out[code] = st
        return out
    except Exception as e:  # noqa: BLE001 - DB 查询失败不阻断端点
        logger.warning("[factors] DB IC series stats failed: %s", e)
        return {}


def _build_health_summary(sample_counts: dict[str, int] | None = None,
                          series_stats: dict[str, dict[str, float]] | None = None) -> dict:
    """O6: 计算因子模型健康度聚合（valid/warn/no_data/static/avg_ic）。

    供 /factors/model 输出（与 /factors/active 的 summary 同口径）。
    F25②: sample_counts 为日频交易日数（distinct trade_date），series_stats 为
    每因子 {ic_mean,ic_std,ir,t_stat}——status 判定用「交易日 + t/IR」而非 |IC| 阈值。
    """
    ic_batch = registry._last_ic_batch
    total_valid = total_warn = total_no_data = total_static = 0
    total_observable = 0
    ic_vals: list[float] = []
    for code in registry._computers:
        definition = registry.get_factor(code)
        ic_val = ic_batch.get(code)
        if code in STATIC_FACTOR_CODES or code in MARKET_LEVEL_FACTOR_CODES:
            # P1-10: 市场级因子与政策静态因子一样不参与截面 IC 计数/平均
            ic_val = None
        _sc = (sample_counts or {}).get(code, 0)
        _st = (series_stats or {}).get(code, {})
        status, _ = _status_of(
            code,
            samples=_sc,
            t_stat=_st.get("t_stat"),
            ir=_st.get("ir"),
            ic_val=ic_val,
        )
        if status == "valid":
            total_valid += 1
        elif status == "warn":
            total_warn += 1
        elif status == "no_data":
            total_no_data += 1
        else:
            total_static += 1
        if MIN_OBSERVABLE_DAYS <= _sc < MIN_TRADING_DAYS:
            total_observable += 1
        if ic_val is not None:
            ic_vals.append(ic_val)
    # F26: 「平均 |IC|」应为绝对值均值，旧实现为带符号均值（与同屏 IC 卡差 5.3×）。
    avg_ic = round(sum(abs(v) for v in ic_vals) / len(ic_vals), 4) if ic_vals else None
    return {
        "valid": total_valid,
        "warn": total_warn,
        "no_data": total_no_data,
        "static": total_static,
        "avg_ic": avg_ic,
        # F25②④/F32: 门槛与分档计数——前端「统计显著因子 N」与「积累中（可观察）」标签
        "min_samples": MIN_TRADING_DAYS,
        "observable_days": MIN_OBSERVABLE_DAYS,
        "significant": total_valid,
        "observable": total_observable,
    }


@router.get("/model")
async def get_factor_model(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Return factor model overview: category breakdown, total counts, descriptions.

    Provides a structured view of the registered factor definitions for
    display in the FactorModelView frontend component.

    Cached for 60s — data changes only when factors are re-registered.
    """
    ck = _build_cache_key("/api/v1/factors/model")
    cached = _get_cached(ck, ttl=60)
    if cached:
        etag, body = cached
        return JSONResponse(
            content=body,
            headers={"Cache-Control": "private, max-age=60", "ETag": etag},
        )

    all_factors = registry.list_factors()
    _computers = set(registry._computers or {})

    # Category breakdown
    cat_counts: dict[str, int] = defaultdict(int)
    cat_sub: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # F33 (round23 §8): implemented_count——该分类「已接入可用」因子数
    # （YAML 定义 193 vs 实际实现 38，alternative/theme/microstructure 整类零实现）。
    cat_impl: dict[str, int] = defaultdict(int)

    for f in all_factors:
        cat_counts[f.category] += 1
        if f.subcategory:
            cat_sub[f.category][f.subcategory] += 1
        if f.code in _computers:
            cat_impl[f.category] += 1

    categories = []
    for cat, count in sorted(cat_counts.items()):
        sub_list = [
            {"name": sub, "count": cnt}
            for sub, cnt in sorted(cat_sub[cat].items())
        ]
        _impl = cat_impl.get(cat, 0)
        categories.append({
            "name": cat,
            "count": count,
            # F33: 宣称=可用——分类级区分「定义数」与「已接入数」，0 实现类标「规划中」
            "implemented_count": _impl,
            "planned_count": count - _impl,
            "description": CATEGORY_DESCRIPTIONS.get(cat, ""),
            "subcategories": sub_list,
        })

    body = {
        "total": len(all_factors),
        # F33 (round23): 宣称=可用——total 为 YAML 定义数（193），implemented 为已接入数
        # （38），planned 为未实现（规划中）数。前端不得再把 193 当「可用因子」。
        "implemented": len(_computers),
        "planned": len(all_factors) - len(_computers),
        "categories": categories,
        # O6 (round7 §7 P8): 聚合健康度——前端可直接读模型 valid/no_data/warn/static；
        # F25②: summary 用日频交易日数（distinct date）+ t/IR 序列统计（对齐 /active）
        "summary": _build_health_summary(
            await _db_ic_sample_counts(db),
            await _db_ic_series_stats(db),
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    etag = f"\"{hash(str(body))}\""
    _set_cache(ck, etag, body, ttl=60)
    return JSONResponse(
        content=body,
        headers={"Cache-Control": "private, max-age=60", "ETag": etag},
    )


@router.get("/active")
async def get_active_factors(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Return actively computed factors with IC values, grouped by category.

    Only includes factors that have a registered compute function
    (i.e., actually computed, not just YAML-defined).
    Each factor includes: code, name, category, subcategory, description,
    standardization, ic_threshold, and current ic_value if available.

    Cached for 60s — data changes only on background compute cycle.
    """
    ck = _build_cache_key("/api/v1/factors/active")
    cached = _get_cached(ck, ttl=60)
    if cached:
        etag, body = cached
        return JSONResponse(
            content=body,
            headers={"Cache-Control": "private, max-age=60", "ETag": etag},
        )

    ic_batch = registry._last_ic_batch
    categories: dict[str, dict[str, Any]] = {}

    # Z03: 静态政策标识因子（不计算 IC，status='static'）
    # F25①: sample_count 改读 DB 日频交易日数（factor_ic_records 按 code 分组
    # count(distinct trade_date)）；DB 不可用/无记录时回退内存计数（registry._sample_counts）
    db_sample_counts = await _db_ic_sample_counts(db)
    db_series_stats = await _db_ic_series_stats(db)
    memory_sample_counts = getattr(registry, "_sample_counts", {}) or {}
    last_computed_at = getattr(registry, "_last_computed_at", None)

    for code in registry._computers:
        definition = registry.get_factor(code)
        cat_name = definition.category if definition else _get_factor_category(code)
        sub_name = definition.subcategory if definition else ""

        if cat_name not in categories:
            categories[cat_name] = {
                "name": cat_name,
                "description": CATEGORY_DESCRIPTIONS.get(cat_name, ""),
                "factors": [],
            }

        ic_val = ic_batch.get(code)
        ic_threshold = definition.ic_threshold if definition else 0.02
        if code in STATIC_FACTOR_CODES:
            # Z03: 静态因子 ic_value=null（不再硬编码 0）、threshold=0
            ic_val = None
            ic_threshold = 0.0
        _db_count = db_sample_counts.get(code) if db_sample_counts else None
        # F25①: 优先 DB 日频交易日数，DB 无记录/不可用回退内存计数
        _sample_count = _db_count if _db_count is not None else memory_sample_counts.get(code, 0)
        _ser = (db_series_stats or {}).get(code, {})
        # F25②: status 用「交易日 + t/IR」判定（替换旧 |IC|≥阈值 且 samples≥30）
        status, reason = _status_of(
            code,
            samples=_sample_count,
            t_stat=_ser.get("t_stat"),
            ir=_ser.get("ir"),
            ic_val=ic_val,
        )
        factor_entry = {
            "code": code,
            "name": definition.name if definition and definition.name else _get_factor_name(code),
            # P2-4 (R4-11d): 注入 category 字段——前端 FactorModelView tooltip 读
            # item.category（旧实现无此字段 → tooltip 分类显示空；父级 categories[].name
            # 在 flatMap 渲染时丢失）。
            "category": cat_name,
            "subcategory": sub_name,
            "description": definition.description if definition else "",
            "standardization": definition.standardization if definition else "zscore",
            "ic_threshold": ic_threshold,
            "ic_value": round(ic_val, 4) if ic_val is not None else None,
            # F25②④: IC 序列统计（来自 factor_ic_records 日频序列）
            "ic_mean": _ser.get("ic_mean"),
            "ic_std": _ser.get("ic_std"),
            "ir": _ser.get("ir"),
            "t_stat": _ser.get("t_stat"),
            # Z03 新增字段
            "status": status,
            "reason": reason,
            # F25①: sample_count = 累计交易日数（distinct trade_date），非刷新次数
            "sample_count": 0 if code in STATIC_FACTOR_CODES else _sample_count,
            "last_computed_at": None if code in STATIC_FACTOR_CODES else last_computed_at,
        }
        categories[cat_name]["factors"].append(factor_entry)

    # Build sorted category list
    cat_list = []
    for cat_name in sorted(categories.keys()):
        cat = categories[cat_name]
        factors = cat["factors"]
        # Z03: 静态因子不计入 valid/warn/no_data/avg_ic 统计，但单独计数
        computed = [f for f in factors if f["status"] != "static"]
        vals = [f["ic_value"] for f in computed if f["ic_value"] is not None]
        # F26: 「平均 |IC|」= 绝对值均值（非带符号均值）
        avg_ic = round(sum(abs(v) for v in vals) / len(vals), 4) if vals else None
        valid_count = sum(1 for f in computed if f["status"] == "valid")
        warn_count = sum(1 for f in computed if f["status"] == "warn")
        no_data_count = sum(1 for f in computed if f["status"] == "no_data")
        static_count = sum(1 for f in factors if f["status"] == "static")

        cat_list.append({
            "name": cat_name,
            "count": len(factors),
            "description": cat["description"],
            "avg_ic": avg_ic,
            "valid_count": valid_count,
            "warn_count": warn_count,
            "no_data_count": no_data_count,
            "static_count": static_count,
            "factors": factors,
        })

    # Compute global summary
    all_ic_vals = [f["ic_value"] for cat in cat_list for f in cat["factors"]
                   if f["status"] != "static" and f["ic_value"] is not None]
    total_valid = sum(c["valid_count"] for c in cat_list)
    total_warn = sum(c["warn_count"] for c in cat_list)
    total_no_data = sum(c["no_data_count"] for c in cat_list)
    total_static = sum(c["static_count"] for c in cat_list)
    # F25②④: 可观察档计数（交易日 ≥60 但 <250）——「积累中（可观察）」
    total_observable = sum(
        1 for cat in cat_list for f in cat["factors"]
        if f["status"] != "static" and MIN_OBSERVABLE_DAYS <= (f["sample_count"] or 0) < MIN_TRADING_DAYS
    )
    # F26 (round23 P0-B): 全局 avg_ic 同样必须为绝对值均值——与同屏 IC 卡/per-category 一致，
    # 否则再次出现「同屏两个相差 5× 的 平均|IC|」（实测 0.0449 vs 0.2461）。
    avg_all_ic = round(sum(abs(v) for v in all_ic_vals) / len(all_ic_vals), 4) if all_ic_vals else None

    body = {
        "total": len(registry._computers),
        "categories": cat_list,
        "summary": {
            "valid": total_valid,
            "warn": total_warn,
            "no_data": total_no_data,
            "static": total_static,
            "avg_ic": avg_all_ic,
            # F25②④/F32: 门槛与分档——前端「统计显著因子 N」「积累中（可观察）」
            # 标签与引导文案（旧代码读 summary.min_samples 但后端无此键 → 静默回退 30）
            "min_samples": MIN_TRADING_DAYS,
            "observable_days": MIN_OBSERVABLE_DAYS,
            "significant": total_valid,
            "observable": total_observable,
        },
        # P2-1: zero_ratio 从 /factors/ic 并入（F3-4 步骤D：零值占比
        # 1.0 = 全部样本为 0 → 数据源未接入；区分「数据缺失」与「IC 无效」）
        # F27: zero_ratio 实际挂在 ic_tracker 实例上（ic_tracker.py:179），
        # 旧代码误读 registry → 恒 {}，使「区分数据缺失 vs IC 无效」能力永久失效。
        "zero_ratio": getattr(_ic_tracker, "_zero_ratio", {}) or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    etag = f"\"{hash(str(body))}\""
    _set_cache(ck, etag, body, ttl=60)
    return JSONResponse(
        content=body,
        headers={"Cache-Control": "private, max-age=60", "ETag": etag},
    )


def _get_factor_name(code: str) -> str:
    """Extract a simple name from factor code."""
    parts = code.split(".")
    if len(parts) >= 2:
        raw = parts[-1].replace("_", " ")
        return raw[:1].upper() + raw[1:]
    return code


def _get_factor_category(code: str) -> str:
    """Extract category prefix from factor code.

    Normalizes known short prefixes to their canonical category names
    to avoid duplicate categories when some factors lack YAML definitions.
    """
    CATEGORY_PREFIX_MAP = {
        "etf": "etf_specific",
        "china": "china_specific",
    }
    parts = code.split(".")
    raw = parts[0] if parts else "unknown"
    return CATEGORY_PREFIX_MAP.get(raw, raw)


