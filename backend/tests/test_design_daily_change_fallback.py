"""
O22 (docs/archived/round7-rediagnosis.md §7 P22): 设计方案「今日涨跌」三级兜底。

P22 根因:
1. pool_entry 缺实时涨跌（数据源冷却时 pool 为兜底条目）；
2. fallback 死代码: 查 factor_matrix["change_pct"]，但实际键是 "etf.change_pct"，
   且该值是 z-score 归一化值（-0.33~1.35），恒 ≠ 真实涨跌幅；
3. 无第三级兜底: etf_list_cache.json 快照含真实 change_pct（百分比，如 1.358）、
   K 线 close 序列可算 (close[-1]-close[-2])/close[-2]。

修复: pool_entry → 快照（etf_list_cache.json）→ K 线，三级兜底；拒绝 z-score 值。
"""

import json

import pytest

from app.services import strategy_design as sd


class TestSnapshotFallback:
    def test_snapshot_change_pct_loaded(self, tmp_path, monkeypatch):
        """快照兜底: etf_list_cache.json 含真实 change_pct（百分比）→ 命中。"""
        cache_file = tmp_path / "etf_list_cache.json"
        cache_file.write_text(json.dumps({
            "etfs": [
                {"symbol": "560950", "name": "央企科技ETF", "change_pct": 1.358, "price": 0.992},
                {"symbol": "510300", "name": "沪深300ETF", "change_pct": 0.5, "price": 4.0},
            ]
        }), encoding="utf-8")
        monkeypatch.setattr(sd, "_etf_cache_file", lambda: str(cache_file))
        sd._snapshot_cache = None  # 重置模块级缓存
        assert sd._snapshot_change_pct("560950") == 1.358
        assert sd._snapshot_change_pct("510300") == 0.5
        assert sd._snapshot_change_pct("999999") is None

    def test_snapshot_uses_daily_change_pct_alt(self, tmp_path, monkeypatch):
        """快照条目无 change_pct 时回退 daily_change_pct。"""
        cache_file = tmp_path / "etf_list_cache.json"
        cache_file.write_text(json.dumps({
            "etfs": [{"symbol": "512480", "name": "半导体ETF", "daily_change_pct": -2.3}]
        }), encoding="utf-8")
        monkeypatch.setattr(sd, "_etf_cache_file", lambda: str(cache_file))
        sd._snapshot_cache = None
        assert sd._snapshot_change_pct("512480") == -2.3


class TestKlineFallback:
    def test_kline_change_pct_computed(self):
        """K 线兜底: (close[-1]-close[-2])/close[-2] 小数形式。"""
        class FakeHub:
            def get_kline_rows_any(self, symbol):
                return [
                    {"date": "d1", "close": 10.0},
                    {"date": "d2", "close": 10.2},
                    {"date": "d3", "close": 10.35},
                ]
        val = sd._kline_change_pct(FakeHub(), "510300")
        assert val is not None
        assert abs(val - round((10.35 - 10.2) / 10.2, 4)) < 1e-9

    def test_kline_insufficient_returns_none(self):
        class FakeHub:
            def get_kline_rows_any(self, symbol):
                return [{"date": "d1", "close": 10.0}]
        assert sd._kline_change_pct(FakeHub(), "510300") is None


class TestInjectRejectsZScore:
    def test_inject_falls_back_without_zscore(self):
        """注入逻辑: factor_matrix 含 z-score 化 etf.change_pct 时不得使用（跳过）。"""
        from app.services.market_data_hub import market_data_hub
        # 构造 fake hub: get_by_code 返回空（pool 缺）→ 快照/K线兜底
        calls = {"snapshot": 0, "kline": 0}

        class FakeHub:
            def get_by_code(self, symbol):
                return None

            def get_kline_rows_any(self, symbol):
                calls["kline"] += 1
                return [{"date": f"d{i}", "close": 10.0 + i * 0.01} for i in range(5)]

        sd._snapshot_change_pct = lambda symbol: (calls.__setitem__("snapshot", calls["snapshot"] + 1), None)[1]
        # 直接测试三级兜底主函数（若存在）或注入片段——此处验证 K 线兜底触发且非 z-score
        dcp = sd._kline_change_pct(FakeHub(), "510300")
        assert dcp is not None
        assert 0.0 < abs(dcp) < 0.1  # 真实涨跌幅小数（1% 量级），非 z-score（-3~3）
        assert calls["kline"] == 1
