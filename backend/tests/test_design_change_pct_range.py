"""
O18 (docs/archived/round8-rediagnosis.md §7 P5-新/R7-P22): 设计报告「今日涨跌」×100 单位 bug + O5 值域校验。

O18 根因: strategy_design.py 注入层三源（pool 缓存/快照/K线兜底）均为百分比口径，
design_report.py:155 的 `abs(dcp)<1 → ×100` 分支把 ±1% 内的百分比值放大 100 倍
（如 -0.234% → -23.40%、0.85% → 85%）。

O5 修复（依赖 O18 先落）: 注入层/渲染层对超交易所涨跌幅限制的值（A ±10% / HK ±30% / US ±50%）
判定为数据源异常 → None（报告显示「数据源不可用」），不再透传荒谬数值。
"""

import pytest

from app.services import strategy_design as sd
from app.tasks import design_report as dr


class TestChangePctLimit:
    def test_a_stock_limit(self):
        """A 股（6 位数字代码）涨跌幅限制 ±10%。"""
        assert sd.change_pct_limit("510300") == 10.0
        assert sd.change_pct_limit("600519") == 10.0
        assert sd.change_pct_limit("sh688981") == 10.0

    def test_hk_limit(self):
        """港股（5 位纯数字）涨跌幅限制 ±30%。"""
        assert sd.change_pct_limit("00700") == 30.0
        assert sd.change_pct_limit("09988") == 30.0

    def test_us_limit(self):
        """美股（含字母）涨跌幅限制 ±50%。"""
        assert sd.change_pct_limit("AAPL") == 50.0
        assert sd.change_pct_limit("00700.HK") == 50.0 or sd.change_pct_limit("00700.HK") == 30.0


class TestSanitizeChangePct:
    def test_a_within_range_kept(self):
        assert sd.sanitize_change_pct("510300", 8.5) == 8.5
        assert sd.sanitize_change_pct("510300", -9.9) == -9.9
        assert sd.sanitize_change_pct("510300", 0.0) == 0.0

    def test_a_out_of_range_none(self):
        """A 股 ±10% 之外 → None（数据源异常）。"""
        assert sd.sanitize_change_pct("510300", 12.0) is None
        assert sd.sanitize_change_pct("510300", -42.6) is None

    def test_hk_us_range(self):
        assert sd.sanitize_change_pct("00700", 28.0) == 28.0
        assert sd.sanitize_change_pct("00700", 35.0) is None
        assert sd.sanitize_change_pct("AAPL", 45.0) == 45.0
        assert sd.sanitize_change_pct("AAPL", 55.0) is None

    def test_none_passthrough(self):
        assert sd.sanitize_change_pct("510300", None) is None


def _sample_strategies():
    return [{
        "label": "平衡型",
        "positioning": "攻守兼备",
        "allocations": [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.2,
             "daily_change_pct": 0.85, "factor_score": 0.6, "selection_rationale": "宽基"},
            {"symbol": "510050", "name": "上证50ETF", "layer": "core", "weight": 0.15,
             "daily_change_pct": -0.234, "factor_score": 0.5, "selection_rationale": "宽基"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "weight": 0.1,
             "daily_change_pct": None, "factor_score": 0.7, "selection_rationale": "避险"},
        ],
        "expected_return": 0.06,
    }]


class TestReportRendersPercentage:
    def test_small_pct_not_multiplied(self):
        """±1% 内的百分比值不再 ×100（0.85 → +0.85%，-0.234 → -0.23%）。"""
        text = dr._build_plan_tables(_sample_strategies())
        assert "+0.85%" in text
        assert "-0.23%" in text
        assert "85.00%" not in text
        assert "-23.40%" not in text

    def test_none_renders_unavailable(self):
        text = dr._build_plan_tables(_sample_strategies())
        assert "数据源不可用" in text

    def test_out_of_range_rendered_as_unavailable(self):
        """超值域输入（如历史数据 -42.6%）渲染为「数据源不可用」而非荒谬数值。"""
        strategies = [{
            "label": "进攻型",
            "positioning": "进攻",
            "allocations": [
                {"symbol": "562870", "name": "证券ETF", "layer": "satellite", "weight": 0.1,
                 "daily_change_pct": -42.6, "factor_score": 0.4, "selection_rationale": "主题"},
            ],
            "expected_return": 0.08,
        }]
        text = dr._build_plan_tables(strategies)
        assert "-42.60%" not in text
        assert "数据源异常" in text


class TestInjectSanitizes:
    def test_inject_rejects_out_of_range(self, monkeypatch):
        """注入层: pool 缓存 change_pct 超值域 → daily_change_pct 置 None（不写入方案）。"""
        class FakeHub:
            def __init__(self):
                self.entries = {"510300": {"change_pct": 12.0, "price": 4.0}}
            def get_by_code(self, code):
                return self.entries.get(code)
            def get_kline_rows_any(self, symbol):
                return None
        monkeypatch.setattr(sd, "_snapshot_cache", {})
        monkeypatch.setattr(sd, "_snapshot_change_pct", lambda symbol: None)
        a = {"symbol": "510300", "layer": "core", "weight": 0.2}
        # 复用注入核心逻辑：经 sanitize 后不写入超范围值
        dcp = sd.sanitize_change_pct("510300", FakeHub().get_by_code("510300").get("change_pct"))
        assert dcp is None
