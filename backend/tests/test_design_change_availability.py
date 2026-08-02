"""
P1-4 (R4-02): 今日涨跌列数据源降级显性化。

- _build_plan_tables 涨跌数据缺失时输出「数据源不可用」而非空 "—"，
  避免「数据源降级导致的数据缺失」被误读为「0% 涨跌」或静默缺失。
- 有真实涨跌（含 0.0 真实值）时正常输出百分比。

mock 引擎 strategies，无网络。
"""

from app.tasks.design_report import _build_plan_tables


def _strategy(daily_change_pct=None):
    return {
        "label": "防御型",
        "positioning": "稳健防守",
        "expected_return": 0.08,
        "expected_return_current": 0.08,
        "allocations": [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "weight": 0.2, "factor_score": 0.6,
             "selection_rationale": "核心宽基，大盘价值代表",
             "daily_change_pct": daily_change_pct},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "weight": 0.1, "factor_score": 0.4,
             "selection_rationale": "避险资产配置",
             "daily_change_pct": daily_change_pct},
        ],
    }


def test_missing_change_marked_data_unavailable():
    """P1-4: 涨跌缺失 → 「数据源不可用」而非 "—"。"""
    tables = _build_plan_tables([_strategy(daily_change_pct=None)])
    assert "| 数据源不可用 |" in tables, "缺失涨跌应显式标注「数据源不可用」"
    assert "| — |" not in tables, "不应再输出裸 em-dash 涨跌单元格"


def test_real_change_percent_rendered():
    """P1-4: 真实涨跌（含 0.0）正常渲染百分比。"""
    tables = _build_plan_tables([_strategy(daily_change_pct=0.0)])
    assert "| +0.00% |" in tables, "真实 0% 应渲染 +0.00% 而非降级标注"
    assert "数据源不可用" not in tables

    tables2 = _build_plan_tables([_strategy(daily_change_pct=0.015)])
    assert "| +1.50% |" in tables2


def test_mixed_missing_and_real():
    """P1-4: 部分缺失——缺失标的标注，有数据标的正常。"""
    s = _strategy(daily_change_pct=None)
    s["allocations"][1]["daily_change_pct"] = -0.008  # -0.80%
    tables = _build_plan_tables([s])
    assert "| 数据源不可用 |" in tables
    assert "| -0.80% |" in tables


def test_expected_return_equal_explicit_note():
    """P2-6 (R4-03): 当前预期年化 == 预期年化 → 显式说明（非默认同值误导）。"""
    s = _strategy(daily_change_pct=0.5)
    s["expected_return"] = 0.08
    s["expected_return_current"] = 0.08  # range_bound 不调整 → 相等
    tables = _build_plan_tables([s])
    assert "当前预期年化" in tables
    assert "当前预期年化与预期年化一致" in tables, "相等时应给出显式说明"
    assert "未触发预期收益调整" in tables


def test_expected_return_adjusted_no_note():
    """P2-6: 已随市态调整（不同值）时不输出「一致」说明。"""
    s = _strategy(daily_change_pct=0.5)
    s["expected_return"] = 0.08
    s["expected_return_current"] = 0.11  # 已调整（如偏多市态）
    tables = _build_plan_tables([s])
    assert "| 8% |" in tables and "| 11% |" in tables
    assert "当前预期年化与预期年化一致" not in tables
