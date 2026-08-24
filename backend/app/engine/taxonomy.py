"""engine/taxonomy.py — ETF 分类语义单点（round35 B3-F7）。

docs/round35-architecture-review.md §6.3-F7：三套「宽基」判定
（wide-basis / growth-style / large-cap-family）+ 科创系主题 + 近替代品族
此前散落 allocation_engine，关键词表与排除词表多处维护；本模块收敛为唯一
真相源：

- :func:`classify_etf` 一次计算五标签（:class:`Classification`）；
- allocation_engine 保留同名薄包装委托（risk_controls 与 14 个测试文件的
  import 路径不变）；
- 关键词/排除词表公开导出——新 ETF 命名变化只改这里（S2 收敛目标）；
- ``COMPANY_NAMES`` 公司名名单随迁（B1-F3 已并集+len 降序，B3 落位本模块，
  pool_balancing 直接 import）。

纯函数、零 I/O——check_engine_purity AST 门禁适用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── B3b: ETF 名称 → 指数概念兜底提取 ────────────────────────────────────
# 去除基金公司名 + ETF/联接 后缀 → 余下字符串即为指数概念。
COMPANY_NAMES = [
    # round19 P1-②: 长公司名优先语义已由 len 降序排序保证（见
    # extract_index_concept），不再依赖手工排序列表顺序。
    "华泰柏瑞", "柏瑞", "天弘基金", "广发基金",
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
    "惠升", "华宸", "富荣", "易米", "长江", "渤海", "爱建", "金元顺安",
]


def extract_index_concept(name: str) -> str:
    """从 ETF 名称提取指数概念（兜底，仅当外部 tracked_index 不可用时）。

    策略：顺次去除基金公司名 → 去除 ETF/联接/发起 后缀 → 剩余字符串即为指数概念。
    极端兜底：若清理后为空则返回原名的前 6 个字符。

    Examples:
        "科创100ETF汇添富" → "科创100"
        "沪深300ETF华夏"  → "沪深300"
    """
    clean = name
    # round35 B1-F3 (§4.3 D3): 长公司名优先（len 降序）——根治 round19 P1-② 类
    # 子串剥除 bug；pool_balancing 同款语义共用本名单。
    for cn in sorted(COMPANY_NAMES, key=len, reverse=True):
        clean = clean.replace(cn, "")
    for sfx in ["ETF", "联接", "LOF", "发起式", "发起", "场内", "场外"]:
        clean = clean.replace(sfx, "")
    clean = clean.strip()
    if not clean or len(clean) < 2:
        return name[:6] if len(name) >= 6 else name
    return clean


def normalize_segment(concept: str) -> str:
    """将指数概念归一化为板块级标识，用于跨层板块集中度控制。

    Examples:
        "科创50"/"科创100"/"科创新能源" → "科创"
        "中证500价值" → "中证500"（M3 家族归一化）
        "沪深300增强" → "沪深300"
    """
    for prefix in ["科创", "半导体", "芯片", "军工", "新能源"]:
        if concept.startswith(prefix):
            return prefix
    # M3: 中证500/沪深300 家族归一化——同指数不同风格切片视为同一板块。
    for base in ("中证500", "沪深300"):
        if concept.startswith(base) and concept != base:
            return base
    return concept


# ── 关键词表（单一真相源）───────────────────────────────────────────────

# F0-5 步骤 C: 科创系主题词（卫星层配额裁剪口径）
TECH_THEMES = ("科创", "半导体", "芯片", "AI", "人工智能")

# M5 (P1-1 子步骤 3): A 股宽基语义关键词——industry 缺失时按名称/tracked_index 补判。
WIDE_BASIS_KEYWORDS = (
    "中证A100", "A100", "中证A500", "中证A50", "中证500", "中证800",
    "沪深300", "上证50", "上证180", "上证综指", "科创50", "创业板",
    "中证100", "深证100", "MSCI中国",
    # round19 P1-②: 裸 A500/A50——「A500ETF华泰柏瑞」等无「中证」前缀漏判
    "A500", "A50",
)

# F6 (round6 §14.4): 高 beta 成长宽基——核心层风格集中度约束用。
# 注意与 WIDE_BASIS 的区别：宽基指全部 A 股宽基，成长仅指高 beta 子集
# （沪深300/中证A500 等价值/均衡宽基不在此列）。
GROWTH_WIDE_BASIS_KEYWORDS = (
    "科创50", "科创100", "科创200", "创业板50", "创业板",
    "双创50", "双创", "科创创业",
)

# O16 (round7 §7 P18) + R101 (round32): 大盘/超大盘宽基族——核心层数量上限约束用。
# R101（用户决策 2026-08-20）：数量上限 ≤4 含强制锚；中证500 纳入
# （实测 中证500×沪深300=0.857、×中证A500=0.935，中盘高相关需计入）。
LARGE_CAP_WIDE_BASIS_KEYWORDS = (
    "沪深300", "中证A500", "中证A50", "中证A100",
    "上证50", "上证180", "深证100", "中证100", "中证800", "MSCI中国",
    # R101: 中证500 纳入（含 价值/成长/增强 细分——"中证500" 子串命中）
    "中证500",
    # round19 P1-②: 裸 A500/A50
    "A500", "A50",
)

# 大盘宽基排除词——「中证1000」（中盘小盘）含 "中证100" 子串会被误判，
# 排除词优先于命中词。
LARGE_CAP_EXCLUDE_KEYWORDS = (
    "中证1000", "中证1000增强", "国证2000", "中证2000",
)


def _candidate_text(meta: dict[str, Any]) -> str:
    return f"{meta.get('name', '') or ''}{meta.get('tracked_index', '') or ''}"


def is_tech_theme_name(name: str) -> bool:
    """判断 ETF 名称是否属于科创系主题（卫星层配额裁剪）。"""
    return any(t in (name or "") for t in TECH_THEMES)


def wide_basis_of(meta: dict[str, Any]) -> bool:
    """M5: 是否 A 股宽基（core 属性）——industry 字段优先，名称/指数补判。"""
    ind = (meta.get("industry") or "").strip()
    if ind == "宽基指数" or "宽基" in ind:
        return True
    text = _candidate_text(meta)
    return any(k in text for k in WIDE_BASIS_KEYWORDS)


def growth_style_of(meta: dict[str, Any]) -> bool:
    """F6: 是否高 beta 成长宽基（科创50/创业板/科创100 等）。

    industry 能区分时（如"半导体"）直接判否——科创芯片是主题 ETF 非宽基。
    """
    ind = (meta.get("industry") or "").strip()
    if ind and ind != "宽基指数" and "宽基" not in ind:
        # 明确非宽基行业（半导体/医药等主题行业）→ 不是宽基
        return False
    text = _candidate_text(meta)
    return any(k in text for k in GROWTH_WIDE_BASIS_KEYWORDS)


def large_cap_family_of(meta: dict[str, Any]) -> bool:
    """O16 + R101: 是否大盘宽基族（大盘/超大盘 + 中证500），排除词优先。"""
    text = _candidate_text(meta)
    if any(k in text for k in LARGE_CAP_EXCLUDE_KEYWORDS):
        return False
    return any(k in text for k in LARGE_CAP_WIDE_BASIS_KEYWORDS)


# 近替代品族表（round24 R24②）：同主题不同发行商的 ETF 判定为近替代品——
# 独立于 K 线相关系数（降级盲时 r=None 也能识别）；关键词语义 + 归一化概念双路。
# (族名, 触发关键词)——顺序优先：先匹配更具体的族。
SUBSTITUTE_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("半导体", ("科创半导体", "科创芯片", "芯片", "半导体")),
    ("医药生物", ("创新药", "生物科技", "生物医药", "医药")),
    ("券商", ("证券", "券商")),
    ("大盘宽基", ("沪深300", "上证50", "中证A500", "中证100", "上证180")),
    ("科创成长", ("科创50", "科创100", "创业板", "双创")),
    ("黄金", ("黄金",)),
    ("国债", ("国债", "利率债", "政金债")),
]


def substitute_family_of(meta: dict[str, Any]) -> str | None:
    """round24 R24②: 近替代品族判定（纯函数）。

    双路判定：① SUBSTITUTE_FAMILIES 关键词族匹配；② 归一化概念兜底
    （normalize_segment(extract_index_concept(name)) ∈ 科创/半导体/芯片/军工/新能源）。
    返回族名或 None（黄金 vs 科创 不误报）。
    """
    text = (
        f"{meta.get('name', '') or ''} {meta.get('industry', '') or ''} "
        f"{meta.get('tracked_index', '') or ''}"
    )
    for fam, keywords in SUBSTITUTE_FAMILIES:
        if any(k in text for k in keywords):
            return fam
    seg = normalize_segment(extract_index_concept(meta.get("name") or ""))
    if seg in ("科创", "半导体", "芯片", "军工", "新能源"):
        return seg
    return None


@dataclass(frozen=True)
class Classification:
    """ETF 五维分类标签（§6.3-F7：classify_etf 一次算全，消费方按需取用）。"""

    wide_basis: bool                # M5：A 股宽基（含中盘/成长）
    growth_style: bool              # F6：高 beta 成长宽基子集
    large_cap_family: bool          # O16/R101：大盘宽基族（排除词优先）
    tech_theme: bool                # F0-5：科创系主题
    substitute_family: str | None   # R24②：近替代品族名（无族 None）


def classify_etf(meta: dict[str, Any]) -> Classification:
    """对单只候选 meta 计算全部分类标签（纯函数，文本单遍组装）。"""
    return Classification(
        wide_basis=wide_basis_of(meta),
        growth_style=growth_style_of(meta),
        large_cap_family=large_cap_family_of(meta),
        tech_theme=is_tech_theme_name(meta.get("name") or ""),
        substitute_family=substitute_family_of(meta),
    )
