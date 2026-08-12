# -*- coding: utf-8 -*-
"""P0-23 (round16 3.25): 候选池误杀活跃板块 ETF——快照成交额异常实时补查防护。

验收:
① 快照成交额低估（<MIN_AVG_AMOUNT）但实时补查达标 → 保留入候选池（负向：误杀 → FAIL）；
② 实时补查仍低 → 过滤 + WARNING（真实低流动性不误放）；
③ 测试环境 ETF_SKIP_AMOUNT_OVERRIDE=1 时不触发网络（跳过补查直接过滤）。
"""
import os
import pytest
from unittest.mock import patch

from app.fetchers.etf_scanner import filter_etfs, MIN_AVG_AMOUNT


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
