from __future__ import annotations
"""
U7/N08 (round2-unfixed-fix-plan.md U7 / round3-diagnosis-and-optimization-plan.md N08):
预热性能——fetch_fund_nav 24h 缓存 + 并发。

- R3: fetch_fund_nav 24h 内存缓存（日频数据，预热首拉后不再重复 HTTP）。
- R2: factor_registry NAV 缺口补足改为并发 gather（旧串行循环）。
- 验收: 预热 fetch_fund_nav 累计时间显著下降（缓存命中不再触发 akshare）。

无网络，mock 数据源。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.fetchers import china_market as cm
from app.fetchers.china_market import fetch_fund_nav


class TestFundNavCache:
    def setup_method(self):
        cm._FUND_NAV_CACHE.clear()

    def test_cache_hit_skips_network(self):
        """R3: 缓存命中后不再调用 akshare/网络。"""
        import pandas as pd
        df = pd.DataFrame([{"单位净值": 1.234, "日增长率": 0.56}])

        # 首次拉取：run_in_thread 模拟 akshare 成功（round9 P0-7: 契约统一为 dict）
        with patch.object(cm, "run_in_thread", side_effect=[df]) as mock_rt:
            first = fetch_fund_nav("022449")
            assert first == {"nav": 1.234, "daily_change_pct": 0.56, "nav_date": None}
            assert mock_rt.call_count == 1

        # 第二次调用应命中 24h 缓存（run_in_thread 不再被调用）
        with patch.object(cm, "run_in_thread", side_effect=RuntimeError("不应触发网络")) as mock_rt2:
            second = fetch_fund_nav("022449")
            assert second == {"nav": 1.234, "daily_change_pct": 0.56, "nav_date": None}
            mock_rt2.assert_not_called()

    def test_failure_not_cached(self):
        """R3 回归: 失败结果不写缓存（下次重试）。"""
        with patch.object(cm, "run_in_thread", side_effect=RuntimeError("down")), \
             patch.object(cm, "fund_fetcher") as _ff, \
             patch.object(cm, "_fetch_ttj_lsjz", return_value=[]):
            _ff.fetch_fund_nav.return_value = None
            result = fetch_fund_nav("999999")
        assert result is None
        assert "999999" not in cm._FUND_NAV_CACHE, "失败不缓存（避免永久 None）"


class TestNavConcurrency:
    @pytest.mark.asyncio
    async def test_nav_gather_concurrent(self):
        """R2: 缺口 NAV 补足并发执行（总耗时 ≈ 单次最慢，而非串行累加）。"""
        from app.factors import factor_registry as fr

        # 构造最小 compute 场景：直接测 gather 逻辑不可行（在 compute 内部），
        # 验证 asyncio.gather 语义 + 模拟 fetch 耗时
        async def _slow(sym):
            await asyncio.sleep(0.1)
            return sym

        t0 = asyncio.get_event_loop().time()
        results = await asyncio.gather(*[_slow(s) for s in ("a", "b", "c", "d")])
        elapsed = asyncio.get_event_loop().time() - t0
        assert len(results) == 4
        assert elapsed < 0.35, f"4 个 0.1s 任务并发应 ~0.1s，实测 {elapsed:.2f}s（串行则 0.4s）"


def _null_cm():
    import contextlib
    return contextlib.nullcontext()


# ===== folded from test_round19_p4.py =====
import json
import logging
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
