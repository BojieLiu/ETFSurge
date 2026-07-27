"""
TDD tests for the full-market ETF scanner + classifier.

New modules:
  - etf_scanner.py: fetch_all_etfs_base, filter_etfs, classify_etf, layer_ranking
  - sentiment_fetcher.py: fetch_advance_decline_ratio, fetch_market_sentiment
  - benchmark_stocks.py: fetch_benchmark_stocks

All external calls (akshare) are mocked.
"""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import types


# ─── ETF Scanner ────────────────────────────────────────────────

def _make_spot_row(code, name, scale=5.0, amount=2e8, turnover=3.0, pe=15.0, pb=2.0):
    """Build a DataFrame row shaped like fund_etf_spot_em output."""
    return {
        "代码": code,
        "名称": name,
        "最新价": 1.0,
        "涨跌幅": 0.5,
        "成交额": amount,
        "换手率": turnover,
        "市盈率-动态": pe,
        "市净率": pb,
        "基金规模": scale,
        "跟踪指数": "沪深300指数",
        "跟踪指数代码": "000300",
    }


class TestEtfScanner:
    @patch("akshare.fund_etf_spot_em")
    def test_fetch_all_filters_by_scale_and_amount(self, mock_spot):
        """验证硬性过滤：过滤掉规模<=1亿和成交额<=1000万的ETF"""
        from app.fetchers.etf_scanner import filter_etfs

        df = pd.DataFrame([
            _make_spot_row("510300", "沪深300ETF", scale=50.0, amount=10e8),
            _make_spot_row("518880", "黄金ETF", scale=30.0, amount=5e8),
            _make_spot_row("159999", "迷你ETF", scale=0.5, amount=1e7),   # 规模太小
            _make_spot_row("160000", "僵尸ETF", scale=5.0, amount=5e6),   # 成交额太小
        ])
        result = filter_etfs(df)
        assert len(result) == 2
        codes = {r["symbol"] for r in result}
        assert "510300" in codes
        assert "518880" in codes
        assert "159999" not in codes
        assert "160000" not in codes

    def test_classify_etf_core(self):
        """验证核心层关键词匹配"""
        from app.fetchers.etf_scanner import classify_etf
        assert classify_etf("沪深300ETF", "沪深300指数") == "core"
        assert classify_etf("中证A500ETF", "中证A500指数") == "core"
        assert classify_etf("上证50ETF", "") == "core"
        assert classify_etf("上证180ETF", "") == "core"
        assert classify_etf("中证800ETF", "") == "core"
        # v9.9 fix-plan-pool: 创业板/科创50/中证500 归入核心层
        assert classify_etf("科创50ETF", "") == "core"
        assert classify_etf("创业板ETF", "") == "core"
        assert classify_etf("中证500ETF", "") == "core"
        assert classify_etf("MSCI A50ETF", "") == "core"

    def test_classify_etf_defense(self):
        """验证防御层关键词匹配"""
        from app.fetchers.etf_scanner import classify_etf
        assert classify_etf("黄金ETF", "") == "defense"
        assert classify_etf("30年国债ETF", "") == "defense"
        assert classify_etf("纳指ETF", "") == "defense"
        assert classify_etf("标普500ETF", "") == "defense"
        assert classify_etf("货币ETF", "") == "defense"

    def test_classify_etf_satellite_by_exclusion(self):
        """验证排除法：不在核心/防御关键词中的全部归卫星"""
        from app.fetchers.etf_scanner import classify_etf
        assert classify_etf("半导体ETF", "") == "satellite"
        assert classify_etf("新能源ETF", "") == "satellite"
        assert classify_etf("医药ETF", "") == "satellite"
        assert classify_etf("军工ETF", "") == "satellite"
        assert classify_etf("消费ETF", "") == "satellite"
        assert classify_etf("有色ETF", "") == "satellite"  # 概念板块，非防御

    def test_layer_ranking_selects_top_n(self):
        """验证层内排名取 TOP N"""
        from app.fetchers.etf_scanner import layer_ranking
        items = [
            {"symbol": "A", "name": "ETF_A", "amount": 10e8, "scale": 50.0},
            {"symbol": "B", "name": "ETF_B", "amount": 5e8, "scale": 30.0},
            {"symbol": "C", "name": "ETF_C", "amount": 1e8, "scale": 5.0},
            {"symbol": "D", "name": "ETF_D", "amount": 0.5e8, "scale": 3.0},
        ]
        top2 = layer_ranking(items, top_n=2)
        assert len(top2) == 2
        assert top2[0]["symbol"] == "A"
        assert top2[1]["symbol"] == "B"

    def test_layer_ranking_force_required(self):
        """核心层强制插入510300和560600"""
        from app.fetchers.etf_scanner import layer_ranking
        items = [
            {"symbol": "510500", "name": "中证500ETF", "amount": 10e8, "scale": 50.0},
            {"symbol": "510300", "name": "沪深300ETF", "amount": 8e8, "scale": 100.0},
            {"symbol": "560600", "name": "中证A500ETF", "amount": 5e8, "scale": 60.0},
        ]
        result = layer_ranking(items, top_n=5, required=["510300", "560600"])
        codes = {r["symbol"] for r in result}
        assert "510300" in codes
        assert "560600" in codes

    def test_full_classification_correct_layers(self):
        """验证三层分类覆盖：核心/防御关键词内不遗漏，其余归卫星"""
        from app.fetchers.etf_scanner import classify_etf

        # 全量 ETF 名称测试集
        test_cases = {
            # 核心
            "沪深300ETF": "core", "上证50ETF": "core",
            "深证100ETF": "core",
            # 防御
            "黄金ETF": "defense", "国债ETF": "defense", "纳指ETF": "defense",
            "标普500ETF": "defense", "恒生ETF": "satellite", "货币ETF": "defense",
            "日经ETF": "defense", "短融ETF": "defense",
            # 卫星（排除法）
            "半导体ETF": "satellite", "新能源ETF": "satellite", "医药ETF": "satellite",
            "军工ETF": "satellite", "证券ETF": "satellite", "银行ETF": "satellite",
            "消费ETF": "satellite", "AIETF": "satellite", "有色ETF": "satellite",
            "央企ETF": "satellite", "传媒ETF": "satellite", "游戏ETF": "satellite",
            # v9.9 fix-plan-pool: 中证500/创业板/科创50 归入核心层
            "中证500ETF": "core", "创业板ETF": "core",
            "科创50ETF": "core", "中证1000ETF": "satellite",
            "碳中和ETF": "satellite", "数字经济ETF": "satellite",
        }
        for name, expected in test_cases.items():
            assert classify_etf(name, "") == expected, f"{name} should be {expected}"


# ─── Sentiment Fetcher ──────────────────────────────────────────

class TestSentimentFetcher:
    def test_sentiment_label_boundaries(self):
        """验证情绪指数映射到正确标签"""
        from app.fetchers.sentiment_fetcher import sentiment_label
        assert sentiment_label(85) == "亢奋"
        assert sentiment_label(70) == "乐观"
        assert sentiment_label(55) == "中性偏乐观"
        assert sentiment_label(50) == "中性"
        assert sentiment_label(40) == "中性偏谨慎"
        assert sentiment_label(25) == "谨慎"
        assert sentiment_label(10) == "恐慌"

    def test_sentiment_index_formula(self):
        """验证情绪指数合成公式"""
        from app.fetchers.sentiment_fetcher import calc_sentiment_index
        result = calc_sentiment_index(
            advance_ratio=0.6,      # 60% 个股上涨
            inst_consensus=0.3,     # 机构净买入
            north_flow=0.2,         # 北向净流入(归一化)
            margin_change=0.1,      # 两融增加
        )
        assert 0 <= result <= 100

    def test_sentiment_index_extremes(self):
        """验证极端情绪"""
        from app.fetchers.sentiment_fetcher import calc_sentiment_index
        # 极端乐观
        high = calc_sentiment_index(
            advance_ratio=0.9, inst_consensus=0.8,
            north_flow=0.8, margin_change=0.7,
        )
        assert high > 70

        # 极端悲观
        low = calc_sentiment_index(
            advance_ratio=0.1, inst_consensus=-0.8,
            north_flow=-0.8, margin_change=-0.7,
        )
        assert low < 30


# ─── Benchmark Stocks ──────────────────────────────────────────

class TestBenchmarkStocks:
    def test_core_benchmark_stocks_count(self):
        """验证核心指标股固定为 10 只"""
        from app.fetchers.benchmark_stocks import CORE_BENCHMARK_STOCKS
        assert len(CORE_BENCHMARK_STOCKS) == 10
        # 必须覆盖主要行业
        sectors = {v["sector"] for v in CORE_BENCHMARK_STOCKS.values()}
        assert "消费" in sectors
        assert "金融" in sectors
        assert "新能源" in sectors
        assert "半导体" in sectors
        assert "医药" in sectors

    def test_institutional_consensus_signal(self):
        """验证机构共识信号判断"""
        from app.fetchers.benchmark_stocks import judge_signal
        # 机构买入 > 散户买入 → 机构增配
        assert judge_signal(inst=1.0, retail=0.2, change=0.6) == "机构增配"
        # 机构卖出 > 散户卖出 → 机构出货
        assert judge_signal(inst=-1.0, retail=-0.2, change=-0.6) == "机构出货"
        # 机构买入 + 散户卖出 → 分歧看多
        assert judge_signal(inst=0.5, retail=-0.3, change=1.0) == "分歧看多"
        # 机构卖出 + 散户买入 → 分歧看空
        assert judge_signal(inst=-0.5, retail=0.3, change=-0.6) == "分歧看空"
        # 方向一致 → 温和上涨/温和下跌
        assert judge_signal(inst=0.3, retail=0.2, change=1.0) == "温和上涨"
        assert judge_signal(inst=-0.3, retail=-0.2, change=-1.0) == "温和下跌"
