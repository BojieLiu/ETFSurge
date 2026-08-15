"""round24 R3: 降级态「精确数字」治理——data_precision 精度标识。

问题（round24 §2.1 实证）：design 570 `factor_data_quality.valid_rate=0.0%` +
「方案仅供参考」横幅，但 UI 仍呈现 5%/15%/21% 精确权重与 -0.99/-0.96 精确因子分
→ 降级诚实了、数字没诚实，专业投资者无法分辨可信边界。

契约：`api-contracts/portfolio/design-precision.md`。
本测试锁定 `_data_precision_report` 纯函数：降级→coarse（权重 5% 档位 + 因子分分档
+ 缺失百分比），正常→exact，输入缺失→exact（不误报降级）。
"""

from app.services.strategy_design import _data_precision_report


def test_degraded_gives_coarse_mode():
    """valid_rate=0 + degraded=True → coarse：权重档位 5%、因子分分档、缺失 100%。"""
    p = _data_precision_report({"valid_rate": 0.0, "degraded": True})
    assert p["mode"] == "coarse"
    assert p["weight_display"] == "coarse"
    assert p["weight_step_pct"] == 5.0
    assert p["factor_score_display"] == "bucket"
    assert p["factor_missing_pct"] == 100.0
    assert "100%" in p["note"]


def test_healthy_gives_exact_mode():
    """valid 率 82% 且未降级 → exact：呈现精确权重/因子分（现状不变）。"""
    p = _data_precision_report({"valid_rate": 0.82, "degraded": False})
    assert p["mode"] == "exact"
    assert p["weight_display"] == "exact"
    assert p["weight_step_pct"] is None
    assert p["factor_score_display"] == "exact"
    assert p["factor_missing_pct"] == 18.0


def test_missing_input_defaults_to_exact():
    """统计不可用（空 dict / None）→ exact，不得误报降级（负向断言）。"""
    for bad in (None, {}, {"note": "因子数据质量统计不可用"}):
        p = _data_precision_report(bad)
        assert p["mode"] == "exact", f"输入 {bad!r} 误报降级"


def test_partial_valid_rate_below_threshold_is_coarse():
    """valid 率 40% < 60% 阈值 → coarse（即使调用方未显式传 degraded）。"""
    p = _data_precision_report({"valid_rate": 0.40})
    assert p["mode"] == "coarse"
    assert p["factor_missing_pct"] == 60.0


def test_precision_never_mutates_weights():
    """data_precision 只影响呈现——函数为纯计算，不含任何 allocations 字段。"""
    p = _data_precision_report({"valid_rate": 0.0, "degraded": True})
    assert "allocations" not in p and "target_weight" not in p
    assert set(p) == {
        "mode", "factor_valid_rate", "factor_missing_pct",
        "weight_display", "weight_step_pct", "factor_score_display", "note",
    }
