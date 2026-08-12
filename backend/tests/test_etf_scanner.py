"""
TDD: etf_scanner filter_etfs — column name compatibility.

This test verifies that filter_etfs correctly handles the actual column names
returned by the current akshare fund_etf_spot_em() API.

Current akshare (2026) returns:
  - 成交额 (amount)    at column index 8
  - 换手率 (turnover)  at column index ...
  - 流通市值 (circulating MktCap) at column index 33
  - 总市值             at column index 34

It does NOT return a column named "基金规模".

All data is mocked — no network calls.
"""

import pytest
import pandas as pd

from app.fetchers.etf_scanner import filter_etfs

# P3-6 (round17): 并入 test_p023_amount_override.py（P0-23 快照成交额异常实时补查防护，
# 同一 filter_etfs 函数域）——需要 os + patch
import os
from unittest.mock import patch


def _make_mock_row(**overrides) -> dict:
    """Simulate one row from akshare fund_etf_spot_em() with real column names."""
    row = {
        "代码":      "510300",
        "名称":      "沪深300ETF",
        "最新价":    3.855,
        "涨跌幅":    0.52,
        "成交额":    1_500_000_000.0,
        "成交量":    390_000_000.0,
        "换手率":    5.12,
        "流通市值":  120.0,  # 亿元 — the REAL column name from akshare
        "总市值":    120.0,
    }
    row.update(overrides)
    return row


def _make_mock_raw_list(size: int = 5) -> list[dict]:
    """Return a list of simulated rows with real ETF column names."""
    etfs = [
        {"代码": "510300", "名称": "沪深300ETF",    "成交额": 1.5e9, "流通市值": 120.0},
        {"代码": "512480", "名称": "半导体ETF",     "成交额": 8e8,  "流通市值": 30.0},
        {"代码": "518880", "名称": "黄金ETF",       "成交额": 2e9,  "流通市值": 200.0},
        {"代码": "513100", "名称": "纳指ETF",       "成交额": 5e8,  "流通市值": 45.0},
        {"代码": "560600", "名称": "中证A500ETF",   "成交额": 3e8,  "流通市值": 15.0},
        # 以下应该被过滤掉（成交额 < 1000万）
        {"代码": "999999", "名称": "迷你债ETF",     "成交额": 5e5,  "流通市值": 0.5},
        # 以下应该被过滤掉（纯债关键词）
        {"代码": "511090", "名称": "国债ETF-30年",  "成交额": 1e8,  "流通市值": 80.0},
    ]
    result = []
    for etf in etfs:
        base = _make_mock_row()
        base.update(etf)
        result.append(base)
    return result


class TestFilterEtfs:
    """Tests for filter_etfs: column name compatibility."""

    def test_filter_etfs_with_real_column_names_returns_non_empty(self):
        """P4-a: filter_etfs must work with akshare's current column names.

        With real column names (成交额/流通市值), at least 5 ETFs should pass
        the min-amount and min-scale filters.
        """
        raw = _make_mock_raw_list()
        result = filter_etfs(raw)
        assert len(result) > 0, (
            f"filter_etfs returned 0/{len(raw)} with real column names. "
            "This suggests SCALE_NAMES still uses '基金规模' which doesn't exist "
            "in the current akshare API. Expected at least 5 ETFs to pass."
        )

    def test_filter_etfs_drops_small_etfs(self):
        """ETFs below amount/scale thresholds must be excluded."""
        raw = _make_mock_raw_list()
        # 999999 has 成交额=5e5 < 10M threshold
        result = filter_etfs(raw)
        codes = {r["symbol"] for r in result}
        assert "999999" not in codes, "迷你债ETF (low amount) should be filtered out"

    def test_filter_etfs_drops_pure_bonds(self):
        """Pure bond / money-market ETFs must be excluded (P1-2: 国债ETF kept as defense)."""
        raw = _make_mock_raw_list()
        result = filter_etfs(raw)
        codes = {r["symbol"] for r in result}
        # P1-2: 国债ETF is defense layer asset, NOT filtered out
        assert "511090" in codes, "国债ETF (511090) is a defense layer asset and should NOT be filtered"
        # 国开债/城投债/信用债/可转债 should still be excluded
        raw_bond = raw + [{"代码": "511200", "名称": "国开债ETF", "最新价": 101.0,
                           "涨跌幅": 0.01, "成交额": 5_000_000, "成交量": 50_000,
                           "换手率": 0.1, "流通市值": 5.0, "总市值": 5.0}]
        result2 = filter_etfs(raw_bond)
        codes2 = {r["symbol"] for r in result2}
        assert "511200" not in codes2, "国开债ETF should be filtered out as pure bond"

    def test_filter_etfs_from_dataframe(self):
        """filter_etfs must accept pd.DataFrame input."""
        raw = _make_mock_raw_list()
        df = pd.DataFrame(raw)
        result = filter_etfs(df)
        assert len(result) > 0, "DataFrame input must also work"

    def test_filter_etfs_output_shape(self):
        """Each filtered ETF must have required fields."""
        raw = _make_mock_raw_list()
        result = filter_etfs(raw)
        for r in result:
            assert "symbol" in r
            assert "name" in r
            assert "amount" in r
            assert isinstance(r["amount"], (int, float))
            assert r["amount"] > 0


# ── P0-23 (round16 3.25, 自 test_p023_amount_override.py 并入): 快照成交额异常补查 ──
# 验收: ① 快照成交额低估（<MIN_AVG_AMOUNT）但实时补查达标 → 保留（负向：误杀 → FAIL）；
#       ② 实时补查仍低 → 过滤（真实低流动性不误放）；③ ETF_SKIP_AMOUNT_OVERRIDE=1 不触发网络。


def _row(code, name, amount, scale=50.0):
    return {
        "代码": code, "名称": name, "最新价": 1.0, "涨跌幅": 0.5,
        "成交额": amount, "成交量": 100, "换手率": 1.0,
        "流通市值": scale, "总市值": scale,
    }


class TestP023SnapshotAmountRescue:
    def test_low_snapshot_amount_rescued_by_realtime(self):
        """P0-23①: 快照成交额 48.9 万（<1000万）但实时 9.7 亿 → 保留（防误杀）。

        负向：快照低估被直接过滤 → FAIL。
        """
        os.environ.pop("ETF_SKIP_AMOUNT_OVERRIDE", None)  # 关闭跳过开关（启用补查）
        try:
            raw = [
                _row("159516", "半导体设备ETF", 489_000),   # 快照 48.9 万 < 1000万
                _row("510300", "沪深300ETF", 1.5e9),        # 正常
            ]
            with patch("app.fetchers.etf_scanner._tencent_gtimg_batch",
                       return_value={"159516": {"amount": 9.7e8}}):  # 实时 9.7 亿
                result = filter_etfs(raw)
        finally:
            os.environ["ETF_SKIP_AMOUNT_OVERRIDE"] = "1"
        codes = {r["symbol"] for r in result}
        assert "159516" in codes, "快照低估但实时达标的活跃板块 ETF 不得被过滤"
        kept = next(r for r in result if r["symbol"] == "159516")
        assert kept["amount"] == pytest.approx(9.7e8), "amount 应用实时值覆盖"

    def test_real_low_amount_still_filtered(self):
        """P0-23③: 实时补查仍低 → 过滤（真实低流动性不误放）。"""
        os.environ.pop("ETF_SKIP_AMOUNT_OVERRIDE", None)
        try:
            raw = [_row("999999", "迷你债ETF", 5e5)]
            with patch("app.fetchers.etf_scanner._tencent_gtimg_batch",
                       return_value={"999999": {"amount": 3e5}}):  # 实时仍 <1000万
                result = filter_etfs(raw)
        finally:
            os.environ["ETF_SKIP_AMOUNT_OVERRIDE"] = "1"
        assert result == [], "实时补查仍低时应过滤"

    def test_skip_switch_no_network(self):
        """测试开关 ETF_SKIP_AMOUNT_OVERRIDE=1 → 不触发网络（直接过滤存疑行）。"""
        raw = [_row("999999", "迷你债ETF", 5e5)]
        with patch("app.fetchers.etf_scanner._tencent_gtimg_batch",
                   side_effect=AssertionError("不应触发网络")) as m:
            result = filter_etfs(raw)
        assert result == []
        m.assert_not_called()
