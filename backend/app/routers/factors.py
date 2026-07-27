"""Factor analysis and IC tracking routes."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from ..core.logging import get_logger
from ..factors.factor_registry import registry

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/factors", tags=["factors"])

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


@router.get("/model")
async def get_factor_model() -> dict[str, Any]:
    """Return factor model overview: category breakdown, total counts, descriptions.

    Provides a structured view of the registered factor definitions for
    display in the FactorModelView frontend component.
    """
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

    return {
        "total": len(all_factors),
        "categories": categories,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/active")
async def get_active_factors() -> dict[str, Any]:
    """Return actively computed factors with IC values, grouped by category.

    Only includes factors that have a registered compute function
    (i.e., actually computed, not just YAML-defined).
    Each factor includes: code, name, category, subcategory, description,
    standardization, ic_threshold, and current ic_value if available.
    """
    ic_batch = registry._last_ic_batch
    categories: dict[str, dict[str, Any]] = {}

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
        factor_entry = {
            "code": code,
            "name": definition.name if definition and definition.name else _get_factor_name(code),
            "subcategory": sub_name,
            "description": definition.description if definition else "",
            "standardization": definition.standardization if definition else "zscore",
            "ic_threshold": definition.ic_threshold if definition else 0.02,
            "ic_value": round(ic_val, 4) if ic_val is not None else None,
        }
        categories[cat_name]["factors"].append(factor_entry)

    # Build sorted category list
    cat_list = []
    for cat_name in sorted(categories.keys()):
        cat = categories[cat_name]
        factors = cat["factors"]
        vals = [f["ic_value"] for f in factors if f["ic_value"] is not None]
        avg_ic = round(sum(vals) / len(vals), 4) if vals else None
        valid_count = sum(1 for f in factors if f["ic_value"] is not None and abs(f["ic_value"]) >= (f["ic_threshold"] or 0.02))
        warn_count = sum(1 for f in factors if f["ic_value"] is not None and abs(f["ic_value"]) < (f["ic_threshold"] or 0.02))
        no_data_count = sum(1 for f in factors if f["ic_value"] is None)

        cat_list.append({
            "name": cat_name,
            "count": len(factors),
            "description": cat["description"],
            "avg_ic": avg_ic,
            "valid_count": valid_count,
            "warn_count": warn_count,
            "no_data_count": no_data_count,
            "factors": factors,
        })

    # Compute global summary
    all_ic_vals = [f["ic_value"] for cat in cat_list for f in cat["factors"] if f["ic_value"] is not None]
    total_valid = sum(c["valid_count"] for c in cat_list)
    total_warn = sum(c["warn_count"] for c in cat_list)
    total_no_data = sum(c["no_data_count"] for c in cat_list)
    avg_all_ic = round(sum(all_ic_vals) / len(all_ic_vals), 4) if all_ic_vals else None

    return {
        "total": len(registry._computers),
        "categories": cat_list,
        "summary": {
            "valid": total_valid,
            "warn": total_warn,
            "no_data": total_no_data,
            "avg_ic": avg_all_ic,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _get_factor_name(code: str) -> str:
    """Extract a simple name from factor code."""
    parts = code.split(".")
    if len(parts) >= 2:
        raw = parts[-1].replace("_", " ")
        return raw[:1].upper() + raw[1:]
    return code


def _get_factor_category(code: str) -> str:
    """Extract category prefix from factor code."""
    parts = code.split(".")
    return parts[0] if parts else "unknown"


@router.get("/ic")
async def get_factor_ic() -> dict[str, Any]:
    """Return current IC values for all core factors.

    Data comes from FactorRegistry._last_ic_batch, which is updated
    automatically after each compute() call when market_data is available.
    """
    ic_batch = registry._last_ic_batch

    factors = [
        {
            "code": code,
            "name": _get_factor_name(code),
            "category": _get_factor_category(code),
            "ic_value": round(val, 4),
            "sample_count": None,  # not available from current batch data
        }
        for code, val in sorted(ic_batch.items())
        if abs(val) > 0.0
    ]

    return {
        "factors": factors,
        "total": len(factors),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
