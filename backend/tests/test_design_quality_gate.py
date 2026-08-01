# -*- coding: utf-8 -*-
"""T14: 方案质量门禁（§8.5.3 清单自动化）——validate_design_quality 纯函数 + 单测。"""
from collections import Counter

import pytest

from app.engine.design_quality import validate_design_quality, check_strategies_differ


def _mk_strategy(sid, core, sats, rsi_vals=None, signals=None):
    etfs = []
    for sym, name, layer, *rest in [c + (None,) for c in core] + [s + (None,) for s in sats]:
        tidx = rest[0]
        a = {"symbol": sym, "name": name, "layer": layer,
             "weight": 0.1, "factor_scores": {"technical": 0.3, "valuation": 0.2}}
        if tidx:
            a["tracked_index"] = tidx
        if rsi_vals:
            a["factor_scores"]["technical.rsi.rsi_14"] = rsi_vals.pop(0)
        if signals:
            a["signal"] = signals.pop(0)
        etfs.append(a)
    return {"id": sid, "etfs": etfs}


# ── ① 核心层宽基 ──────────────────────────────────────────────

def test_core_requires_wide_basis():
    s = _mk_strategy("balanced", [("562330", "中证500价值ETF", "core")], [])
    issues = validate_design_quality([s])
    assert any("核心层" in i and "宽基" in i for i in issues), issues


def test_core_with_wide_basis_ok():
    s = _mk_strategy("balanced", [("510300", "沪深300ETF", "core")], [])
    issues = validate_design_quality([s])
    assert not any("核心层" in i for i in issues)


# ── ② 卫星层同板块 ≤2 ─────────────────────────────────────────

def test_satellite_same_sector_max_two():
    """tracked_index 归一化后同板块 3 只 → 报问题（≤2 只）。"""
    sats = [
        ("159516", "半导体ETF", "satellite", "半导体"),
        ("512480", "半导体50ETF", "satellite", "半导体"),
        ("588200", "科创芯片ETF", "satellite", "半导体"),
    ]
    s = _mk_strategy("balanced", [("510300", "沪深300ETF", "core")], sats)
    issues = validate_design_quality([s])
    assert any("卫星层" in i and "板块" in i for i in issues), issues


# ── ③ RSI 值域 ────────────────────────────────────────────────

def test_rsi_all_below_3_flag():
    s = _mk_strategy("balanced", [("510300", "沪深300ETF", "core")],
                     [("159516", "半导体ETF", "satellite")],
                     rsi_vals=[1.5, 2.0])
    issues = validate_design_quality([s])
    assert any("RSI" in i for i in issues), issues


def test_rsi_normal_range_ok():
    s = _mk_strategy("balanced", [("510300", "沪深300ETF", "core")],
                     [("159516", "半导体ETF", "satellite")],
                     rsi_vals=[43.4, 55.1])
    issues = validate_design_quality([s])
    assert not any("RSI" in i for i in issues)


# ── ④ 信号方向自洽 ────────────────────────────────────────────

def test_signal_consistency_dual_weak():
    """技术<0 且 估值<0 但信号 buy → 不自洽（文案含「双弱」）。"""
    s = _mk_strategy("balanced", [("510300", "沪深300ETF", "core")],
                     [], signals=["buy"])
    for a in s["etfs"]:
        a["factor_scores"]["technical"] = -0.5
        a["factor_scores"]["valuation"] = -0.4
    issues = validate_design_quality([s])
    assert any("双弱" in i for i in issues), issues


# ── ⑤ 三方案差异非机械缩放 ────────────────────────────────────

def test_strategies_differ_not_mechanical():
    """三档预算层权重结构不同（F3-3 差异化预算）。"""
    from app.engine.budgets import dynamic_layer_budget
    budgets = [dynamic_layer_budget(p, "range_bound") for p in ("defensive", "balanced", "aggressive")]
    sig = [tuple(round(b[k], 3) for k in ("core", "satellite", "defense")) for b in budgets]
    assert len(set(sig)) >= 2, f"三档预算结构趋同: {sig}"


def test_check_strategies_differ():
    """check_strategies_differ 检测「仅权重机械缩放」的方案（层结构相同 → False）。"""
    same = [
        {"id": "a", "etfs": [
            {"symbol": "510300", "layer": "core", "weight": 0.45},
            {"symbol": "159516", "layer": "satellite", "weight": 0.30},
            {"symbol": "518880", "layer": "defense", "weight": 0.10},
        ]},
        {"id": "b", "etfs": [
            {"symbol": "510300", "layer": "core", "weight": 0.40},
            {"symbol": "159516", "layer": "satellite", "weight": 0.35},
            {"symbol": "518880", "layer": "defense", "weight": 0.10},
        ]},
    ]
    # 层结构相同（0.45/0.30/0.10 vs 0.40/0.35/0.10 → 不同！）
    assert check_strategies_differ(same) is True
    # 完全复制 → False
    dup = [dict(same[0]), dict(same[0])]
    assert check_strategies_differ(dup) is False
