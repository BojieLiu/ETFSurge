"""round25 R36: 降级态（coarse）方案表格不再呈现精确小数——权重/因子分按档位。

问题（round25 §0.3 R36 实证）：`data_precision` 标注 coarse/bucket（R3 已做），但
design_text 表格仍渲染 `-0.99`/`3.07` 精确因子分与 `21.0%` 精确权重——与标注矛盾。

修复（round25 R36）：`_build_plan_tables` 接收 `precision` 参数——mode=coarse 时
因子分列按强弱分档（偏强/中性/偏弱）、权重按 5% 档位（≈20%），与前端 DesignResult
的 bucket 呈现一致。
"""

import pytest

from app.tasks.design_report import _build_plan_tables


def _strategy():
    return [{
        "id": "balanced", "label": "平衡型", "positioning": "攻守平衡",
        "allocations": [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "weight": 0.2067, "factor_score": -0.9855288495104011,
             "daily_change_pct": 1.2, "selection_rationale": "宽基锚"},
            {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
             "weight": 0.1498, "factor_score": 3.0662,
             "daily_change_pct": 0.1, "selection_rationale": "利率对冲"},
            {"symbol": "CASH", "layer": "cash", "weight": 0.10},
        ],
    }]


class TestBuildPlanTablesPrecision:
    """R36: coarse 态表格分档呈现（不出现精确小数）。"""

    def test_coarse_buckets_factor_score(self):
        """mode=coarse → 因子分列显示「偏弱/偏强/中性」，不含 -0.99/3.07 精确值。"""
        table = _build_plan_tables(_strategy(), precision={"mode": "coarse", "weight_step_pct": 5.0})
        assert "偏弱" in table, "coarse 态 -0.99 应显示「偏弱」"
        assert "偏强" in table, "coarse 态 3.07 应显示「偏强」"
        assert "-0.99" not in table, "coarse 态不得出现精确因子分（R36）"
        assert "3.07" not in table

    def test_coarse_buckets_weight(self):
        """mode=coarse → 权重按 5% 档位（≈20%/≈15%），不含 20.67% 精确值。"""
        table = _build_plan_tables(_strategy(), precision={"mode": "coarse", "weight_step_pct": 5.0})
        assert "≈20%" in table, "20.67% → ≈20%（5% 档）"
        assert "≈15%" in table, "14.98% → ≈15%（5% 档）"
        assert "20.67" not in table and "14.98" not in table, "coarse 态不得出现精确权重"

    def test_exact_keeps_precision(self):
        """mode=exact（或未传）→ 原精确值不变（不误降级）。"""
        table = _build_plan_tables(_strategy())
        assert "-0.99" in table or "-0.985528" in table, "exact 态保留精确因子分"
        assert "21%" in table, "exact 态权重按原值 20.67→21%"
        assert "≈" not in table, "exact 态不得出现档位近似值"

    def test_precision_none_no_regression(self):
        """precision=None → 与旧行为一致（无 ≈/偏强 等降级呈现）。"""
        table = _build_plan_tables(_strategy(), precision=None)
        assert "偏弱" not in table and "≈" not in table