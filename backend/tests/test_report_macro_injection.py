# -*- coding: utf-8 -*-
"""round29 R79 / R80: 国内宏观注入 prompt + 数据时效与不可用标注。

R79: domestic_macro 采集了却从未注入 prompt → LLM 写「未提供国内利率信号」。
R80: 报告里的行情值不可用时静默显示旧值/None，且无「数据截至」时效标注。

无网络：纯 prompt 文本断言 + monkeypatch 宏观源。
"""
import asyncio
import time

import pytest

from app.analysis import llm
from app.analysis.llm.reports import _format_domestic_macro

_REAL_MACRO = {
    "unavailable": False,
    "lpr": {"lpr_1y": 3.0, "lpr_5y": 3.5, "date": "2026-08-20"},
    "bond_yields": {"cn_10y": 1.85, "us_10y": 4.25, "spread_bp": -240.0, "date": "2026-08-18"},
    "money_supply": {"m0_yoy": 11.3, "m1_yoy": 4.6, "m2_yoy": 8.8, "date": "2026-07-31"},
    "cpi_ppi": {"cpi_yoy": 0.4, "ppi_yoy": -2.9},
    "pmi_gdp": {"pmi": {"value": 49.7, "date": "2026-07-31"}, "gdp": {"value": 5.2, "date": "2026-06-30"}},
}


def _prompt(**kw):
    base = dict(
        indices=[{"symbol": "000300", "name": "沪深300", "price": 3800.0, "change_pct": 0.5}],
        commodities=[],
        market_data=[],
        indicators={},
        news=[],
        macro_news=[],
        market="A",
    )
    base.update(kw)
    return llm._build_report_prompt(**base)


# ---------------- R79: 国内宏观注入 ----------------

def test_r79_domestic_macro_injected_with_real_values():
    """真实宏观数据必须出现在 prompt（含 LPR / 国债 / 利差 / M2 / CPI / PMI 真实数字）。"""
    p = _prompt(domestic_macro=_REAL_MACRO)
    assert "### 国内流动性" in p
    assert "3.0" in p and "LPR 1年期" in p
    assert "1.85" in p and "中国10年期国债收益率" in p
    assert "-240.0" in p and "中美10Y利差" in p
    assert "8.8" in p  # M2 同比
    assert "0.4" in p  # CPI 同比
    assert "49.7" in p  # PMI


def test_r79_unavailable_macro_states_source_unavailable():
    """数据源不可用 → 明示「暂不可用」，不得编造数字。"""
    p = _prompt(domestic_macro={"unavailable": True})
    assert "### 国内流动性" in p
    assert "暂不可用" in p
    for fake in ("3.0%", "1.85", "-240.0"):
        assert fake not in p.split("### 国内流动性", 1)[1].split("\n\n")[0]


def test_r79_no_param_keeps_section_absent():
    """未传 domestic_macro（HK/US 报告）→ 不出现该段，向后兼容。"""
    p = _prompt()
    assert "### 国内流动性" not in p


def test_r79_prompt_never_claims_missing_domestic_signal():
    """负向断言：注入真实数据后，prompt 不应再出现「未提供国内利率」类措辞。"""
    p = _prompt(domestic_macro=_REAL_MACRO)
    assert "未提供国内利率" not in p
    assert "未提供国内宏观" not in p


def test_r79_format_partial_macro_only_renders_present_fields():
    """部分源失败（None）→ 只渲染可用项，不输出 None 字面量。"""
    out = _format_domestic_macro({
        "unavailable": False,
        "lpr": {"lpr_1y": 3.0, "lpr_5y": None},
        "bond_yields": None,
        "money_supply": None,
        "cpi_ppi": None,
        "pmi_gdp": None,
    })
    assert out is not None
    assert "LPR 1年期" in out
    assert "LPR 5年期" not in out
    assert "None" not in out


def test_r79_format_all_none_marks_unavailable():
    """所有源 None → 占位「暂不可用」，不返回空串（否则 LLM 无从判断）。"""
    out = _format_domestic_macro({"unavailable": False, "lpr": None, "bond_yields": None,
                                  "money_supply": None, "cpi_ppi": None, "pmi_gdp": None})
    assert out and "暂不可用" in out


# ---------------- R79 step3: 单源超时不拖死整包 ----------------

@pytest.mark.asyncio
async def test_r79_slow_source_does_not_sink_all(monkeypatch):
    """一个慢源超时 → 该源 None，其余源正常返回（旧实现整包 unavailable）。"""
    from app.fetchers import macro_fetcher as mf

    monkeypatch.setattr(mf, "_MACRO_SOURCE_TIMEOUT", 0.3, raising=False)

    def _slow():
        time.sleep(3)
        return {"cn_10y": 1.85}

    monkeypatch.setattr(mf, "fetch_bond_yields", _slow)
    monkeypatch.setattr(mf, "fetch_lpr", lambda: {"lpr_1y": 3.0, "lpr_5y": 3.5})
    monkeypatch.setattr(mf, "fetch_money_supply", lambda: {"m2_yoy": 8.8})
    monkeypatch.setattr(mf, "fetch_cpi_ppi", lambda: {"cpi_yoy": 0.4})
    monkeypatch.setattr(mf, "fetch_pmi_gdp", lambda: {"pmi": {"value": 49.7}})
    monkeypatch.setattr(mf, "fetch_macro_snapshot", lambda: {"macro_direction": "宽松"})

    t0 = time.monotonic()
    out = await asyncio.wait_for(mf.fetch_all_domestic_macro(), timeout=2.5)
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, f"单源超时应立即返回，实测 {elapsed:.2f}s"
    assert out.get("unavailable") is False
    assert out.get("bond_yields") is None  # 慢源被超时丢弃
    assert (out.get("lpr") or {}).get("lpr_1y") == 3.0  # 快源仍在


@pytest.mark.asyncio
async def test_r79_all_sources_fail_returns_unavailable(monkeypatch):
    """全源失败 → unavailable=True（诚实降级，不编造）。"""
    from app.fetchers import macro_fetcher as mf

    def _boom():
        raise RuntimeError("source down")

    for name in ("fetch_lpr", "fetch_bond_yields", "fetch_money_supply",
                 "fetch_cpi_ppi", "fetch_pmi_gdp", "fetch_macro_snapshot"):
        monkeypatch.setattr(mf, name, _boom)

    out = await mf.fetch_all_domestic_macro()
    assert out == {"unavailable": True}


# ---------------- R80: 不可用标注 + 数据时效 ----------------

def test_r80_unavailable_index_not_rendered_as_stale_value():
    """available=False 的指数 → 标「数据源暂不可用」，不得静默展示旧价。"""
    p = _prompt(indices=[{"symbol": "000300", "name": "沪深300", "price": 3800.0,
                          "change_pct": 0.5, "available": False}])
    assert "数据源暂不可用" in p
    assert "3800" not in p


def test_r80_available_index_still_renders_value():
    """available 缺省/True → 正常渲染真实值（不误伤正常路径）。"""
    p = _prompt(indices=[{"symbol": "000300", "name": "沪深300", "price": 3800.0,
                          "change_pct": 0.5, "available": True}])
    assert "3800" in p
    assert "数据源暂不可用" not in p


def test_r80_unavailable_major_stock_marked():
    """主要标的 available=False → 同样标注不可用。"""
    p = _prompt(market_data=[{"symbol": "510300", "name": "沪深300ETF", "price": 3.85,
                              "change_pct": 0.3, "available": False}])
    assert "数据源暂不可用" in p
    assert "3.85" not in p


def test_r80_as_of_annotation_present():
    """as_of 传入 → prompt 含数据截至时效标注。"""
    p = _prompt(as_of="2026-08-19 15:00")
    assert "数据截至 2026-08-19 15:00" in p


def test_r80_as_of_absent_no_annotation():
    p = _prompt()
    assert "数据截至" not in p


def test_r80_hub_exposes_index_snapshot_as_of():
    """hub 必须暴露真实的指数快照时间（否则 as_of 恒 None = 假实现）。"""
    from app.services.market_data_hub import MarketDataHub

    hub = MarketDataHub()
    assert hub.get_index_realtime_as_of() is None  # 未刷新 → 诚实返回 None

    hub._index_realtime_cache = [{"symbol": "000300", "price": 3800.0}]
    hub._index_realtime_cache_ts = time.time()
    as_of = hub.get_index_realtime_as_of()
    assert as_of and len(as_of) >= 16  # "YYYY-MM-DD HH:MM"
    assert as_of[:2] == "20"
