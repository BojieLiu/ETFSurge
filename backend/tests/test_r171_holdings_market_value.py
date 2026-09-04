# -*- coding: utf-8 -*-
"""R171 (round52 §4.3 方案B): 策略检查 holdings_analysis 缺市值字段。

round52 §4.1: check 67 的 holdings_json 15 只均无 `market_value`/`shares_held` 键
（市值总和 = 0）——round51 遗留④「R141 持仓市值列复测」的验证路径在 check 输出
schema 中**不存在**。契约 api-contracts/portfolio/strategy-check-v2.md 已补字段。

负向断言（能失败的）：
- 有份额 + 有现价 → market_value 必须非空且 = 份额×现价（不得为 0/None）；
- 份额缺失或现价为 0 → market_value 必须为 None（诚实），**不得**填 0 冒充；
- 两条路径（LLM 后处理骨架 / 规则兜底骨架）都必须带这两个键。

无网络：纯函数断言（_holding_market_value / _build_rule_fallback_holdings_analysis）。
"""
from __future__ import annotations

import pytest

from app.services.portfolio.strategy_check import (
    _build_rule_fallback_holdings_analysis,
    _holding_market_value,
)


class TestHoldingMarketValuePure:
    def test_shares_times_price(self):
        assert _holding_market_value(1000, 3.85) == 3850.0

    def test_rounds_to_cents(self):
        assert _holding_market_value(333, 1.005) == pytest.approx(334.67, abs=0.01)

    def test_missing_shares_is_none(self):
        """负向：无份额 → None（不填 0 冒充市值）。"""
        assert _holding_market_value(None, 3.85) is None
        assert _holding_market_value(0, 3.85) is None

    def test_missing_price_is_none(self):
        """负向：现价缺失/为 0（数据源未返回）→ None，不得输出 0 市值。"""
        assert _holding_market_value(1000, 0) is None
        assert _holding_market_value(1000, None) is None

    def test_garbage_input_is_none(self):
        assert _holding_market_value("abc", "1.2") is None


def _etf(symbol, shares):
    return {"symbol": symbol, "name": f"{symbol}ETF", "shares_held": shares}


class TestRuleFallbackHoldingsCarryMarketValue:
    def _build(self, etfs, market_data):
        return _build_rule_fallback_holdings_analysis(
            etfs=etfs,
            market_data=market_data,
            factor_breakdowns={},
            weight_map={},
            regime="range_bound",
        )

    def test_holding_with_shares_and_price_has_market_value(self):
        """核心正向：份额>0 + 现价>0 → market_value 非空且 = 份额×现价。"""
        rows = self._build(
            [_etf("159338", 12000)],
            [{"symbol": "159338", "price": 1.1751, "change_pct": 0.5}],
        )
        assert len(rows) == 1
        assert rows[0]["shares_held"] == 12000
        assert rows[0]["market_value"] == pytest.approx(14101.2), (
            f"市值应为 12000×1.1751，实际 {rows[0]['market_value']}"
        )

    def test_price_zero_market_value_is_honest_none(self):
        """负向：现价 0（行情断链）→ market_value=None，不得是 0（0 会被当真实市值）。"""
        rows = self._build(
            [_etf("022449", 8500)],
            [{"symbol": "022449", "price": 0, "change_pct": 0}],
        )
        assert rows[0]["shares_held"] == 8500
        assert rows[0]["market_value"] is None, "现价缺失时市值必须诚实 None（不得 0）"

    def test_missing_shares_key_is_none(self):
        """负向：未灌录份额 → shares_held=None + market_value=None（键仍在）。"""
        rows = self._build(
            [{"symbol": "510300", "name": "沪深300ETF"}],
            [{"symbol": "510300", "price": 4.02, "change_pct": 0.1}],
        )
        assert "shares_held" in rows[0], "字段缺失会让验证路径不存在（R171 根因）"
        assert rows[0]["shares_held"] is None
        assert rows[0]["market_value"] is None

    def test_all_holdings_carry_both_keys(self):
        """骨架路径：每条持仓都带两个键（无一只缺失）。"""
        etfs = [_etf("159338", 12000), {"symbol": "510300", "name": "300ETF"}]
        md = [
            {"symbol": "159338", "price": 1.1751, "change_pct": 0.5},
            {"symbol": "510300", "price": 4.02, "change_pct": 0.1},
        ]
        rows = self._build(etfs, md)
        assert len(rows) == 2
        for r in rows:
            assert "shares_held" in r and "market_value" in r, f"{r['symbol']} 缺市值字段"
        total = sum(r["market_value"] for r in rows if r["market_value"])
        assert total > 0, "有份额+现价的持仓市值总和必须 >0（不得恒 0）"
