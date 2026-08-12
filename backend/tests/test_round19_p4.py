"""
round19 P4（问题 4：A股板块热度大量涨跌幅为 0）测试（2026-08-12 实施）：
- fetch_em_industry_sectors: push2delay 直连分页（pn 递增到 <100 为止、字段与
  _ak_industry_sectors 兼容、失败打 ERROR 日志不静默吞异常）
- fetch_sector_heat_em: push2delay 优先 → akshare 兜底 → 均空回退 + ERROR 日志
- 前端 SectorHeatMap: change_pct=null 显示「—」（负向：null 显示 0% → FAIL）
"""

import json
import logging

import pytest


class _FakeUrl:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()

    def decode(self):
        return self._text


class TestFetchEmIndustrySectors:
    """round19 P4-①: push2delay 直连行业板块分页拉全。"""

    def _diff(self, start, n):
        return [
            {"f12": f"BK{1000 + i}", "f14": f"行业板块{i}", "f3": 1.23,
             "f6": 1e8 + i, "f62": 1e6 + i, "f20": 1e10 + i}
            for i in range(start, start + n)
        ]

    def test_pagination_loops_until_under_100(self, monkeypatch):
        """pn 递增循环，服务端实回 100/页 → 拉 3 页 300 条；字段与 akshare 兼容。"""
        import app.fetchers.sector_fetcher as sf

        calls = []

        def fake_urlopen(req, timeout=8):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(req.full_url).query)
            pn = int(qs["pn"][0])
            calls.append(pn)
            n = 100 if pn < 3 else 50  # 第 3 页不足 100 → 停止
            payload = {"data": {"diff": self._diff((pn - 1) * 100, n)}}
            return _FakeUrl(json.dumps(payload))

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        rows = sf.fetch_em_industry_sectors()
        assert calls == [1, 2, 3], f"pn 应递增到 <100 为止，实得 {calls}"
        assert len(rows) >= 250, f"应拉全 300（3 页），实得 {len(rows)}"
        first = rows[0]
        # 与 _ak_industry_sectors 兼容的键
        for key in ("sector_code", "sector_name", "change_pct", "amount",
                    "main_inflow", "total_market", "lead_stock_name", "lead_stock_code"):
            assert key in first, f"缺兼容键 {key}: {first}"
        assert first["sector_name"] == "行业板块0"
        assert first["change_pct"] == 1.23

    def test_failure_logs_error_not_silent(self, monkeypatch, caplog):
        """网络失败打 ERROR 日志（负向：静默吞异常 → FAIL）。"""
        import app.fetchers.sector_fetcher as sf

        def fake_urlopen(req, timeout=8):
            raise ConnectionError("RemoteDisconnected")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with caplog.at_level(logging.ERROR, logger="app.fetchers.sector_fetcher"):
            rows = sf.fetch_em_industry_sectors()
        assert rows == [], "全失败返回空列表（调用方走 akshare 兜底）"
        assert any("fetch_em_industry_sectors" in r.message for r in caplog.records), \
            "网络失败应打 ERROR 日志而非静默"


class TestFetchSectorHeatEmPriority:
    """round19 P4-①: fetch_sector_heat_em push2delay 优先 → akshare 兜底。"""

    def test_push2delay_first_akshare_fallback(self, monkeypatch):
        import app.fetchers.sector_fetcher as sf

        em_rows = [
            {"sector_code": "BK1", "sector_name": "半导体", "change_pct": 2.3,
             "amount": 1e9, "lead_stock_code": "", "lead_stock_name": "",
             "lead_stock_chg": None},
        ]
        ak_rows = [{"sector_code": "BK2", "sector_name": "白酒", "change_pct": -1.2,
                    "amount": 5e8, "lead_stock_code": "600519",
                    "lead_stock_name": "茅台", "lead_stock_chg": 1.0}]
        calls = []

        def fake_em(limit=None):
            calls.append("em")
            return em_rows

        def fake_ak():
            calls.append("ak")
            return ak_rows

        monkeypatch.setattr(sf, "fetch_em_industry_sectors", fake_em)
        monkeypatch.setattr(sf, "_ak_industry_sectors", fake_ak)
        # 绕过 cached() 60s TTL（测试内连续两次调用独立场景）
        monkeypatch.setattr(sf, "cached", lambda key, fn, ttl_key: fn())
        out = sf.fetch_sector_heat_em(limit=5)
        assert calls == ["em"], "push2delay 有数据时不应调 akshare"
        assert out and out[0]["name"] == "半导体" and out[0]["change_pct"] == 2.3

        # push2delay 空 → akshare 兜底
        calls.clear()

        def fake_em_empty(limit=None):
            calls.append("em")
            return []

        monkeypatch.setattr(sf, "fetch_em_industry_sectors", fake_em_empty)
        out2 = sf.fetch_sector_heat_em(limit=5)
        assert calls == ["em", "ak"], "push2delay 空时应走 akshare 兜底"
        assert out2[0]["name"] == "白酒"
        assert out2[0]["lead_stocks"][0]["symbol"] == "600519", "akshare 路径保留领涨股"

    def test_both_empty_logs_error(self, monkeypatch, caplog):
        """push2delay + akshare 均空 → ERROR 日志（负向：静默 → FAIL）。"""
        import app.fetchers.sector_fetcher as sf

        monkeypatch.setattr(sf, "fetch_em_industry_sectors", lambda limit=None: [])
        monkeypatch.setattr(sf, "_ak_industry_sectors", lambda: None)
        with caplog.at_level(logging.ERROR, logger="app.fetchers.sector_fetcher"):
            out = sf.fetch_sector_heat_em(limit=5)
        assert out == []
        assert any("均无数据" in r.message for r in caplog.records), "双源均空应打 ERROR 日志"


class TestSectorHeatMapNullChangePct:
    """round19 P4-③: 前端 SectorHeatMap change_pct=null 显示「—」不冒充 0%。"""

    def _src(self):
        import os
        p = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                         "components", "market", "SectorHeatMap.vue")
        if not os.path.exists(p):
            p = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src",
                             "components", "market", "SectorHeatMap.vue")
        return open(p, encoding="utf-8").read()

    def test_null_change_pct_shows_dash(self):
        src = self._src()
        assert "row-change--na" in src, "null 涨跌幅应有「—」占位样式"
        assert "涨跌幅数据源异常" in src, "「—」应有 tooltip 说明"

    def test_degraded_banner_consumed(self):
        src = self._src()
        assert 'v-if="degraded && activeTab === \'heat\'"' in src, "degraded=true 应有提示条"
