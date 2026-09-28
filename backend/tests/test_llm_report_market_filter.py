"""
P0-2 (R4-13 / N04 补全): HK/US llm-report 指数过滤。

- _filter_indices_for_market: HK/US 报告 indices 按 market_ctx.index_symbols 白名单过滤
  （^ 前缀归一化），A/GLOBAL 保持全量。
- _filter_commodities_for_market: HK/US 不注入 A 股期货商品数据。
- 完整 llm_report 路径：market=HK + mock indices 含 A/HK → 传入 prompt 的 indices 仅 HK。

mock 数据源与 LLM，无网络。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.market_context import resolve_market_context
from app.routers.analysis import (
    _filter_commodities_for_market,
    _filter_indices_for_market,
)

_INDICES_A_HK = [
    {"symbol": "000001", "name": "上证指数", "price": 3832.26, "change_pct": 0.72},
    {"symbol": "399001", "name": "深证成指", "price": 12000.0, "change_pct": 0.5},
    {"symbol": "000300", "name": "沪深300", "price": 4100.0, "change_pct": 0.3},
    {"symbol": "^HSI", "name": "恒生指数", "price": 23000.0, "change_pct": 0.8},
    {"symbol": "^HSTECH", "name": "恒生科技指数", "price": 4829.22, "change_pct": 0.53},
]


def test_filter_indices_hk_excludes_a_stock():
    """P0-2: HK 报告 indices 只保留恒生系，A 股指数全部排除。"""
    mctx = resolve_market_context("HK")
    filtered = _filter_indices_for_market(mctx, _INDICES_A_HK)
    syms = {i["symbol"] for i in filtered}
    assert syms == {"^HSI", "^HSTECH"}, f"HK 过滤结果: {syms}"
    names = [i["name"] for i in filtered]
    assert not any("上证" in n or "深证" in n or "沪深" in n for n in names), \
        "A 股指数仍混入 HK 报告"


def test_filter_indices_hk_tolerates_bare_symbol():
    """P0-2: 数据侧无 ^ 前缀（HSI）与配置侧 ^HSI 等价。"""
    mctx = resolve_market_context("HK")
    data = [{"symbol": "HSI", "name": "恒生指数", "price": 1.0, "change_pct": 0.0},
            {"symbol": "000001", "name": "上证指数", "price": 1.0, "change_pct": 0.0}]
    filtered = _filter_indices_for_market(mctx, data)
    assert [i["symbol"] for i in filtered] == ["HSI"]


def test_filter_indices_us():
    """P0-2: US 报告只保留美股指数。"""
    mctx = resolve_market_context("US")
    data = _INDICES_A_HK + [
        {"symbol": "^GSPC", "name": "标普500", "price": 5500.0, "change_pct": 0.5},
        {"symbol": "^IXIC", "name": "纳斯达克", "price": 18000.0, "change_pct": 0.9},
    ]
    filtered = _filter_indices_for_market(mctx, data)
    syms = {i["symbol"] for i in filtered}
    assert syms == {"^GSPC", "^IXIC"}, f"US 过滤结果: {syms}"


def test_filter_indices_a_keeps_all():
    """P0-2: A 市场报告保持全量（含日经/美股等关联信息，不回归）。"""
    mctx = resolve_market_context("A")
    data = _INDICES_A_HK + [{"symbol": "^N225", "name": "日经225", "price": 39000.0, "change_pct": 1.0}]
    filtered = _filter_indices_for_market(mctx, data)
    assert len(filtered) == len(data)


def test_filter_commodities_market():
    """P0-2: HK/US 不注入 A 股期货商品；A/GLOBAL 保留。"""
    comms = [{"name": "沪金", "price": 800.0, "change_pct": 0.2}]
    assert _filter_commodities_for_market(resolve_market_context("HK"), comms) == []
    assert _filter_commodities_for_market(resolve_market_context("US"), comms) == []
    assert _filter_commodities_for_market(resolve_market_context("A"), comms) == comms
    assert _filter_commodities_for_market(resolve_market_context("GLOBAL"), comms) == comms

# ── R01 (round58 §1 M2): sector 三件套注入报告 prompt ──────────────────────
# M2 根因：build_full_context 采了 sector_momentum/hot_plates/sector_heat，
# llm_report_stream 从不取、_build_report_prompt 无参数 → 采完即丢，
# LLM 写「输入未提供行业涨跌」。本组钉住接线 + 负向（空数据不得编造涨跌幅）。


def _prompt(**kw):
    from app.analysis.llm import _build_report_prompt
    base = dict(
        indices=[], commodities=[], market_data=[], indicators={},
        news=[], macro_news=[],
    )
    base.update(kw)
    return _build_report_prompt(**base)


def test_r01_sector_section_injected_with_real_names_and_pct():
    """R01: sector_momentum 有值 → prompt 含强势/弱势 Top5 + 真实名与涨跌幅。"""
    p = _prompt(
        sector_momentum=[
            {"sector_name": "半导体", "change_pct": 3.21},
            {"sector_name": "银行", "change_pct": -1.05},
            {"sector_name": "创新药", "change_pct": 2.10},
        ],
        hot_plates=[{"name": "CRO/CMO", "change_pct": 5.72}],
    )
    assert "板块与风格" in p
    assert "强势 Top5" in p and "弱势 Top5" in p
    assert "半导体" in p and "+3.21%" in p
    assert "银行" in p and "-1.05%" in p
    assert "热点板块" in p and "CRO/CMO" in p


def test_r01_sector_all_empty_no_fabricated_pct():
    """R01 负向：sector 全空 → 段出现且只给 R80 占位，**不得**出现任何板块涨跌幅。"""
    p = _prompt(sector_momentum=[], hot_plates=[])
    assert "板块与风格" in p
    assert "（板块涨跌数据源暂不可用）" in p
    # 负向：不得凭空虚构板块名/百分比
    assert "强势 Top5" not in p
    assert "热点板块" not in p


def test_r01_sector_rows_without_numeric_pct_are_skipped():
    """R01 负向：涨跌幅字段缺失/非数值的行必须跳过（不得当 0 渲染）。"""
    p = _prompt(
        sector_momentum=[{"sector_name": "半导体"}, {"sector_name": "银行", "change_pct": None}],
        hot_plates=[],
    )
    assert "（板块涨跌数据源暂不可用）" in p
    assert "半导体" not in p and "银行" not in p


def test_r01_router_passes_sector_ctx_into_prompt():
    """R01 接线守卫：llm_report_stream 必须把 ctx 里的 sector_momentum 透传给
    _build_report_prompt（M2 断点的真正修复点在 router 侧）。"""
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "app" / "routers" / "analysis.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    kw_names: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "_build_report_prompt"):
            kw_names |= {k.arg for k in node.keywords if k.arg}
    assert {"sector_momentum", "hot_plates"} <= kw_names, (
        f"router 未把板块三件套透传给 prompt：{sorted(kw_names)}"
    )
