"""
TDD: signal.py enhanced with TD Sequential (九转) computation.
"""
import pytest
import pandas as pd
import numpy as np

from app.analysis.signal import (
    generate_signal,
    compute_td_sequential,
)


class TestTdSequential:
    """九转序列信号测试"""

    def test_td_buy_setup_triggered(self):
        """连续4天 close[i] < close[i-4] 应触发买入计数"""
        close = pd.Series([10.0, 10.5, 10.3, 10.8,  # 기준
                           9.8, 9.9, 9.7, 10.0,     # 第1-4天
                           8.5, 9.0, 8.8, 9.2])     # 第5-8天
        result = compute_td_sequential(close)
        # 第 4-8 天中至少有一天有买入计数
        assert any(c > 0 for c in result["buy_sequence"])

    def test_td_sell_setup_triggered(self):
        """连续4天 close[i] > close[i-4] 应触发卖出计数"""
        close = pd.Series([10.0, 9.5, 9.8, 9.6,
                           10.5, 10.8, 10.3, 10.9,
                           11.5, 11.2, 11.8, 11.6])
        result = compute_td_sequential(close)
        assert any(c > 0 for c in result["sell_sequence"])

    def test_td_buy_sequence_counts_correctly(self):
        """买入计数应递增"""
        # 构造持续下降序列
        close = pd.Series([100, 101, 102, 103,    # reference
                           99, 100, 98, 99,        # days 1-4 (all < i-4)
                           98, 97, 96, 95])        # days 5-8
        result = compute_td_sequential(close)
        buy = [c for c in result["buy_sequence"] if c > 0]
        # 应该连续递增: 1, 2, 3, 4, 5...
        assert len(buy) >= 4
        assert buy[0] == 1
        assert buy[1] >= buy[0]

    def test_td_no_setup_no_count(self):
        """震荡行情不应触发九转"""
        np.random.seed(42)
        close = pd.Series(100 + np.random.randn(20) * 2)
        result = compute_td_sequential(close)
        # 可能触发也可能不触发，但不能出现 > 9
        assert max(result["buy_sequence"]) <= 9
        assert max(result["sell_sequence"]) <= 9

    def test_td_short_series_returns_default(self):
        """数据不足时应返回全零"""
        close = pd.Series([10.0, 10.5, 10.3])
        result = compute_td_sequential(close)
        assert result["buy_setup_9"] is False
        assert result["sell_setup_9"] is False
        assert result["current_buy"] == 0
        assert result["current_sell"] == 0

    def test_td_buy_setup_9_detected(self):
        """买入序列到达 9 时 buy_setup_9 应为 True"""
        close = pd.Series([
            100, 101, 102, 103,  # reference
            99, 100, 98, 99,     # 1-4
            98, 97, 96, 95,      # 5-8
            94, 93, 92, 91,      # 9-12 (should hit 9 here)
        ])
        result = compute_td_sequential(close)
        assert result["buy_setup_9"] is True

    def test_td_returns_dict_keys(self):
        """返回字典应包含所有预期字段"""
        close = pd.Series([10.0] * 20)
        result = compute_td_sequential(close)
        expected_keys = {"buy_sequence", "sell_sequence",
                         "buy_setup_9", "sell_setup_9",
                         "current_buy", "current_sell"}
        assert set(result.keys()) == expected_keys


class TestGenerateSignalWithTD:
    """集成了九转后的信号生成测试"""

    def test_signal_structure_with_td(self):
        """集成了九转的 generate_signal 仍应返回标准结构"""
        indicators = {
            "rsi": 45,
            "macd": {"dif": 0.1, "dea": 0.05, "histogram": 0.05},
            "kdj": {"k": 40, "d": 35, "j": 50},
            "bollinger": {"bandwidth": 8},
            "ma5": 100.0,
            "ma20": 99.0,
            "td_sequential": {
                "buy_setup_9": False,
                "sell_setup_9": False,
                "current_buy": 0,
                "current_sell": 0,
            },
        }
        result = generate_signal(indicators)
        assert "signal" in result
        assert "score" in result
        assert "reasons" in result
