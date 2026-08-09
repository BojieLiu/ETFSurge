"""Factor analysis and IC tracking routes."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.logging import get_logger
from ..factors.factor_registry import registry, ET_SPECIFIC_GAP_CODES

# F19 R70: code → 缺失字段名映射（泛化：ln_mcap 等非 etf_specific 因子也有缺口标注）
GAP_FIELD_MAP = {
    "style.size.ln_mcap": "fund_scale/total_mv",
    "style.size.ln_float_mcap": "float_mv",
}

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/factors", tags=["factors"])

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
}


def _status_of(code: str, ic_val: float | None, ic_threshold: float) -> tuple[str, str]:
    """Z03: 权威状态 + 原因说明（/active 与 /model 共用）。

    O20 (round7 §7 P20): 常量因子（截面 std=0 → IC 无法计算）给独立标注——
    与「数据源未接入」「IC 未累积」三分，消除「看起来像样本不足、实际是
    数据全缺」的误导。
    """
    if code in STATIC_FACTOR_CODES:
        return "static", "静态政策标识因子，不计算 IC"
    if code in MARKET_LEVEL_FACTOR_CODES:
        # P1-10: 市场级因子（全市场单一值/市态级降级）——截面恒等，移出截面 IC 池
        return "static", "市场级因子（全市场单一值），不参与截面 IC，仅作市态/组合层输入"
    if ic_val is None:
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
        return "no_data", "IC 未累积（样本 <3）"
    threshold = ic_threshold if ic_threshold and ic_threshold > 0 else 0.02
    samples = getattr(registry, "_sample_counts", {}).get(code, 0)
    # P1-3 (round9 §6.5): 文案统一 |IC| 口径——旧「IC -0.449 ≥ 阈值 0.02」负数不可能 ≥
    # 正阈值，逻辑自相矛盾；负 IC（预测反向）且 |IC|≥阈值 → warn（负向淘汰警示）而非 valid，
    # 满足「负 IC 标 valid 且文案 ≥阈值」矛盾项消除。
    if abs(ic_val) >= threshold:
        if ic_val < 0:
            # P1-C (round10 §5.5/§10): 负向因子降权警示——|IC|≥阈值且为负（预测反向）
            # reason 明示「负向预测已下架」，供 P3-E 门禁断言无「强负 IC 活跃项」。
            return "warn", f"负向预测已下架：|IC|={abs(ic_val):.4f} ≥ 阈值 {threshold}，预测方向与收益反向（建议降权/淘汰），样本数 {samples}"
        return "valid", f"|IC|={ic_val:.4f} ≥ 阈值 {threshold}，样本数 {samples}"
    return "warn", f"|IC|={abs(ic_val):.4f} < 阈值 {threshold}，样本数 {samples}"


def _build_health_summary() -> dict:
    """O6: 计算因子模型健康度聚合（valid/warn/no_data/static/avg_ic）。

    供 /factors/model 输出（与 /factors/active 的 summary 同口径）。
    """
    ic_batch = registry._last_ic_batch
    sample_counts = getattr(registry, "_sample_counts", {}) or {}
    total_valid = total_warn = total_no_data = total_static = 0
    ic_vals: list[float] = []
    for code in registry._computers:
        definition = registry.get_factor(code)
        ic_val = ic_batch.get(code)
        ic_threshold = definition.ic_threshold if definition else 0.02
        if code in STATIC_FACTOR_CODES or code in MARKET_LEVEL_FACTOR_CODES:
            # P1-10: 市场级因子与政策静态因子一样不参与截面 IC 计数/平均
            ic_val = None
            ic_threshold = 0.0
        status, _ = _status_of(code, ic_val, ic_threshold)
        if status == "valid":
            total_valid += 1
        elif status == "warn":
            total_warn += 1
        elif status == "no_data":
            total_no_data += 1
        else:
            total_static += 1
        if ic_val is not None:
            ic_vals.append(ic_val)
    avg_ic = round(sum(ic_vals) / len(ic_vals), 4) if ic_vals else None
    return {
        "valid": total_valid,
        "warn": total_warn,
        "no_data": total_no_data,
        "static": total_static,
        "avg_ic": avg_ic,
    }


@router.get("/model")
async def get_factor_model() -> JSONResponse:
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

    # Category breakdown
    cat_counts: dict[str, int] = defaultdict(int)
    cat_sub: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for f in all_factors:
        cat_counts[f.category] += 1
        if f.subcategory:
            cat_sub[f.category][f.subcategory] += 1

    categories = []
    for cat, count in sorted(cat_counts.items()):
        sub_list = [
            {"name": sub, "count": cnt}
            for sub, cnt in sorted(cat_sub[cat].items())
        ]
        categories.append({
            "name": cat,
            "count": count,
            "description": CATEGORY_DESCRIPTIONS.get(cat, ""),
            "subcategories": sub_list,
        })

    body = {
        "total": len(all_factors),
        "categories": categories,
        # O6 (round7 §7 P8): 聚合健康度——前端可直接读模型 valid/no_data/warn/static
        "summary": _build_health_summary(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    etag = f"\"{hash(str(body))}\""
    _set_cache(ck, etag, body, ttl=60)
    return JSONResponse(
        content=body,
        headers={"Cache-Control": "private, max-age=60", "ETag": etag},
    )


@router.get("/active")
async def get_active_factors() -> JSONResponse:
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
    sample_counts = getattr(registry, "_sample_counts", {}) or {}
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
        status, reason = _status_of(code, ic_val, ic_threshold)
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
            # Z03 新增字段
            "status": status,
            "reason": reason,
            "sample_count": 0 if code in STATIC_FACTOR_CODES else sample_counts.get(code, 0),
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
        avg_ic = round(sum(vals) / len(vals), 4) if vals else None
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
    avg_all_ic = round(sum(all_ic_vals) / len(all_ic_vals), 4) if all_ic_vals else None

    body = {
        "total": len(registry._computers),
        "categories": cat_list,
        "summary": {
            "valid": total_valid,
            "warn": total_warn,
            "no_data": total_no_data,
            "static": total_static,
            "avg_ic": avg_all_ic,
        },
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


@router.get("/ic")
async def get_factor_ic() -> JSONResponse:
    """Return current IC values for all core factors.

    Data comes from FactorRegistry._last_ic_batch, which is updated
    automatically after each compute() call when market_data is available.

    Cached for 60s — data changes only on background compute cycle.
    """
    ck = _build_cache_key("/api/v1/factors/ic")
    cached = _get_cached(ck, ttl=60)
    if cached:
        etag, body = cached
        return JSONResponse(
            content=body,
            headers={"Cache-Control": "private, max-age=60", "ETag": etag},
        )

    ic_batch = registry._last_ic_batch

    factors = [
        {
            "code": code,
            "name": _get_factor_name(code),
            "category": _get_factor_category(code),
            "ic_value": round(val, 4),
            # O6 (round8 §7 P6-新): sample_count 来自 registry._sample_counts
            # （compute() 在 IC 有信号时填充，line 1437）——不再硬编码 None，
            # IC 列表携带样本量/显著性信息。
            "sample_count": getattr(registry, "_sample_counts", {}).get(code, 0),
        }
        for code, val in sorted(ic_batch.items())
        if abs(val) > 0.0
    ]

    body = {
        "factors": factors,
        "total": len(factors),
        # F3-4 步骤D: 零值占比（1.0 = 全部样本为 0 → 数据源未接入；区分「数据缺失」与「IC 无效」）
        "zero_ratio": getattr(registry, "_zero_ratio", {}) or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    etag = f"\"{hash(str(body))}\""
    _set_cache(ck, etag, body, ttl=60)
    return JSONResponse(
        content=body,
        headers={"Cache-Control": "private, max-age=60", "ETag": etag},
    )
