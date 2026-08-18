"""Pure pool-balancing helpers — extracted from MarketDataHub (Batch 4).

Zero-I/O functions moved out of ``app/services/market_data_hub.py`` (plan A
Step 2). The facade keeps thin wrappers with the same public signatures; the
orchestration in ``_refresh_impl`` calls these directly via the wrappers.

Dependency direction: ``engine/`` (pure) <- ``hub/*`` <- facade. No imports
back into services/.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Layer constants (single source of truth; hub/_common re-exports from here)
LAYER_CORE = "core"
LAYER_SATELLITE = "satellite"
LAYER_DEFENSE = "defense"
LAYER_OPPORTUNISTIC = "opportunistic"
LAYER_RESEARCH = "research"
ALL_LAYERS = [LAYER_CORE, LAYER_SATELLITE, LAYER_DEFENSE, LAYER_OPPORTUNISTIC, LAYER_RESEARCH]

# Force-kept pool codes (truncation / balancing must never evict these)
MANDATORY_CODES = {"510300", "159338", "518880", "511090"}


def assign_layer(base_layer: str, industry: str) -> str:
    """行业→层映射（P1-2 防御层分类修复，R5 pool 归层）。"""
    base_layer = base_layer or LAYER_SATELLITE
    industry = industry or "unknown"
    # Core: 宽基指数
    if base_layer == "core" or industry == "宽基指数":
        return LAYER_CORE
    # Defense: 商品/固收（注意：跨境归卫星层，P1-2 修复）
    if base_layer == "defense" or industry in ("商品", "固收"):
        return LAYER_DEFENSE
    # 跨境 → 卫星层（非防御资产）
    if industry == "跨境":
        return LAYER_SATELLITE
    # Research: unknown industry
    if industry == "unknown":
        return LAYER_RESEARCH
    return LAYER_SATELLITE


def normalize_tracked_index(tidx: str) -> str:
    """M3: tracked_index 家族归一化——同一指数的风格/增强切片合并为基准指数。"""
    if not tidx:
        return tidx
    for base in ("中证500", "沪深300"):
        if tidx.startswith(base) and tidx != base:
            return base
    return tidx


def deduplicate_by_index(
    pool: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """B2: 候选池去重——同层同 tracked_index 的 ETF 只保留 fund_scale 最大的。"""
    # 名称中常见的"联接"类后缀
    _LINK_FUND_SUFFIXES = ("联接", "联", "LOF", "C")

    def _extract_index_concept(name: str) -> str:
        """从 ETF 名提取指数概念（去除基金公司名和联接/ETF 后缀）。"""
        _COMPANY_NAMES = [
            "华夏", "易方达", "汇添富", "嘉实", "富国", "招商", "博时", "南方",
            "广发", "华安", "国泰", "鹏华", "天弘", "工银", "建信", "中欧",
            "景顺", "长城", "泰康", "海富通", "光大", "兴全", "东证", "华宝",
            "银华", "大成", "长信", "国联", "申万", "上投", "中信", "华泰",
            "万家", "兴业", "民生", "浦银", "方正", "太平", "前海", "创金",
            "银河", "诺安", "交银", "融通", "泓德", "中加", "永赢", "西部",
            "浙商", "新华", "红土", "安信", "国寿", "英大", "汇丰", "恒生",
            "中银", "国投", "德邦", "华富", "金元", "国金", "九泰", "东方",
            "中泰", "湘财", "国融", "江信", "蜂巢", "东海", "中邮", "华融",
            "金鹰", "长城", "同泰", "红塔", "华润", "格林", "瑞达", "明亚",
            "惠升", "华宸", "富荣", "易米", "长江", "渤海",
        ]
        for company in sorted(_COMPANY_NAMES, key=len, reverse=True):
            name = name.replace(company, "")
        for suffix in ("ETF", "联接", "联", "LOF"):
            name = name.replace(suffix, "")
        return name.strip()

    result: dict[str, list[dict[str, Any]]] = {layer: [] for layer in ALL_LAYERS}
    for layer, items in pool.items():
        seen_indices: dict[str, dict[str, Any]] = {}
        name_seen: dict[str, dict[str, Any]] = {}
        for item in items:
            tidx = item.get("tracked_index", "") or ""
            if tidx:
                tidx = normalize_tracked_index(tidx)
                item["tracked_index"] = tidx
                existing = seen_indices.get(tidx)
                if existing is None:
                    seen_indices[tidx] = item
                else:
                    existing_scale = float(existing.get("fund_scale", 0) or 0)
                    new_scale = float(item.get("fund_scale", 0) or 0)
                    if new_scale > existing_scale:
                        seen_indices[tidx] = item
            else:
                raw_name = item.get("name", item.get("symbol", ""))
                concept = _extract_index_concept(raw_name)
                if not concept:
                    result[layer].append(item)
                    continue
                existing = name_seen.get(concept)
                if existing is None:
                    name_seen[concept] = item
                else:
                    existing_scale = float(existing.get("fund_scale", 0) or 0)
                    new_scale = float(item.get("fund_scale", 0) or 0)
                    existing_is_etf = not any(s in existing.get("name", "") for s in _LINK_FUND_SUFFIXES)
                    new_is_etf = not any(s in item.get("name", "") for s in _LINK_FUND_SUFFIXES)
                    if new_is_etf and not existing_is_etf:
                        name_seen[concept] = item
                    elif existing_is_etf and not new_is_etf:
                        pass  # keep existing
                    elif new_scale > existing_scale:
                        name_seen[concept] = item

        result[layer].extend(seen_indices.values())
        for concept, item in name_seen.items():
            code = item.get("symbol", item.get("code", ""))
            already_in = any(
                e.get("symbol") == code or e.get("code") == code
                for e in result[layer]
            )
            if not already_in:
                result[layer].append(item)

    return result


def ensure_mandatory(
    pool: dict[str, list[dict[str, Any]]],
    flat: list[dict[str, Any]],
) -> None:
    """确保 MANDATORY_CODES 在池中（如果全市场扫描有结果）。原地修改 pool。"""
    if not flat:
        return  # 扫描失败，不强行注入（直接报错）
    for code in MANDATORY_CODES:
        in_pool = any(
            e["symbol"] == code for layer in pool.values() for e in layer
        )
        if not in_pool:
            found = next((e for e in flat if e["symbol"] == code), None)
            if found:
                if code in ("510300", "159338"):
                    target = LAYER_CORE
                elif code in ("518880",):
                    target = LAYER_DEFENSE
                elif code == "511090":
                    target = LAYER_DEFENSE
                else:
                    target = LAYER_SATELLITE
                found["layer"] = target
                pool[target].append(found)
                logger.info("MarketDataHub: enforced mandatory %s -> %s", code, target)


def truncate_with_mandatory_protection(
    balanced: list[dict[str, Any]],
    max_n: int,
) -> list[dict[str, Any]]:
    """R5-0-1: MAX_PER_LAYER 截断时保护强制标的。"""
    mandatory = [e for e in balanced if e.get("symbol") in MANDATORY_CODES]
    rest = [e for e in balanced if e.get("symbol") not in MANDATORY_CODES]
    return mandatory + rest[:max_n]


def recheck_mandatory_after_truncate(
    pool: dict[str, list[dict[str, Any]]],
    flat: list[dict[str, Any]],
    required_codes: set[str] | None = None,
) -> None:
    """R5-0-1: 截断后强制标的二次校验（缺失时从 flat 找回注入）。原地修改 pool。

    ``required_codes`` 由调用方注入（MANDATORY_CODES ∪ etf_scanner.CORE_REQUIRED），
    保持本模块零外部依赖。
    """
    if not flat:
        return  # 扫描失败，不强行注入（与 ensure_mandatory 语义一致）
    required = required_codes or MANDATORY_CODES
    for code in sorted(required):
        in_pool = any(
            e["symbol"] == code for layer in pool.values() for e in layer
        )
        if in_pool:
            continue
        found = next((e for e in flat if e.get("symbol") == code), None)
        if not found:
            continue
        if code in ("510300", "159338"):
            target = LAYER_CORE
        elif code in ("518880", "511090"):
            target = LAYER_DEFENSE
        else:
            target = LAYER_SATELLITE
        found["layer"] = target
        pool.setdefault(target, []).append(found)
        logger.warning("MarketDataHub: re-injected mandatory %s -> %s after truncate", code, target)


def balance_by_industry(
    items: list[dict[str, Any]],
    max_n: int = 10,
) -> list[dict[str, Any]]:
    """P4 fix-plan-pool: 按行业/segment 均衡化候选池。"""
    if not items:
        return []
    if len(items) <= max_n:
        return items

    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        seg = item.get("segment", "") or item.get("industry", "unknown")
        groups[seg].append(item)

    selected: list[dict] = []
    selected_codes: set[str] = set()
    for seg, group in groups.items():
        group_sorted = sorted(group, key=lambda x: x.get("composite_score", 0), reverse=True)
        top = group_sorted[0]
        selected.append(top)
        selected_codes.add(top.get("symbol", ""))

    if len(selected) < max_n:
        remaining = []
        for item in items:
            if item.get("symbol", "") not in selected_codes:
                remaining.append(item)
        remaining.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        selected.extend(remaining[:max_n - len(selected)])

    return selected[:max_n]
