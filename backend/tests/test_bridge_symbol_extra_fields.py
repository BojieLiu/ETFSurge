# -*- coding: utf-8 -*-
"""P1-2 (docs/redundant-review.md §2.1 R2): _bridge_symbol_extra_fields 桥接单测。

冗余评审 R2 判定: _fetch_market_data DEPRECATED 大函数体仍驻留生产桥接逻辑
（R146 nav / R150 total_mv·float_mv / R148 industry），「名义 deprecated、实际
关键路径」。本批把 R150/R148 桥接抽为公共函数 _bridge_symbol_extra_fields，
_fetch_market_data 与 compute() market_data 分支两处复用（R146 nav 既有
_inject_nav 已是公共方法，不重复抽）。

守卫负向断言: 已有真实值不得被估算值覆盖。
"""
from __future__ import annotations

from app.factors.factor_registry import _bridge_symbol_extra_fields


def _apply(extra, base=None):
    data = {"510300": dict(base or {})}
    _bridge_symbol_extra_fields(data, ["510300"], {"510300": extra})
    return data["510300"]


class TestBridgeSymbolExtraFields:
    def test_z04_base_fields_injected(self):
        out = _apply({
            "industry": "半导体", "concepts": ["芯片"],
            "benchmark_close": [3.9, 3.95], "shares_change_20d": -1.2,
            "fund_scale": 100.0,
        })
        assert out["industry"] == "半导体"
        assert out["concepts"] == ["芯片"]
        assert out["shares_change_20d"] == -1.2

    def test_r150_total_mv_bridge(self):
        """fund_scale=100 → total_mv=100（R150 别名桥接）。"""
        out = _apply({"fund_scale": 100.0})
        assert out["total_mv"] == 100.0

    def test_r150_total_mv_no_overwrite_existing(self):
        """负向守卫: 已有真实 total_mv 不得被 fund_scale 覆盖。"""
        out = _apply({"fund_scale": 100.0}, base={"total_mv": 250.0})
        assert out["total_mv"] == 250.0

    def test_r150_float_mv_estimate(self):
        """fund_scale=100 → float_mv=85.0（0.85 估算）。"""
        out = _apply({"fund_scale": 100.0})
        assert out["float_mv"] == 85.0

    def test_r150_float_mv_zero_fund_scale_skipped(self):
        """fund_scale=0 → float_mv 不写入（不造 0 值假数据）。"""
        out = _apply({"fund_scale": 0})
        assert "float_mv" not in out

    def test_r148_industry_holdings_bridge(self):
        out = _apply({"industry": "半导体"})
        assert out["industry_holdings"] == {"半导体": 1.0}

    def test_r148_unknown_industry_skipped(self):
        """负向: industry='unknown' 不桥接（无意义单行业）。"""
        out = _apply({"industry": "unknown"})
        assert "industry_holdings" not in out

    def test_r148_no_overwrite_real_holdings(self):
        """负向: 已有真实 industry_holdings 不得被单值桥接覆盖。"""
        out = _apply({"industry": "半导体"}, base={"industry_holdings": {"半导体": 0.6, "电子": 0.4}})
        assert out["industry_holdings"] == {"半导体": 0.6, "电子": 0.4}
