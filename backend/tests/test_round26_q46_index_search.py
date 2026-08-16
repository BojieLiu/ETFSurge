"""round26 Q4/Q6: 指数搜索索引补全 + akshare 运行时兜底。

问题（round26 §1 Q4/Q6 实证）：`indices_meta` 表极不全（US=7/HK=63）——「费城」「SO」
（美股 tab）与「恒生港股通高股息低波动指数」（港股 tab）搜不到；`_search_indices` 只查
此表、无运行时兜底（与 symbol 模式 search_etf 的兜底不同）。

修复（round26 Q4/Q6）：
- `_search_indices`：本地表 0 命中时触发 akshare 运行时兜底
  `_search_indices_akshare_fallback`（A/HK/US 三段，含静态扩展段）；
- `sync_indices_meta._STATIC_EXTRA_INDICES`：补 SOX/费城半导体、恒生港股通低波动变体。
"""

import pytest


class TestSearchIndicesRuntimeFallback:
    """Q4/Q6: 本地表空 → akshare 兜底命中。"""

    @pytest.mark.asyncio
    async def test_us_fallback_detects_sox(self, monkeypatch):
        """US tab 搜「费城」：本地表空 → akshare US 段兜底命中 SOX。"""
        from app.routers import market as mkt

        # 本地表空（session 返回 0 行）
        class _Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def execute(self, stmt): return _Result([])
        class _Result:
            def __init__(self, rows): self._rows = rows
            def scalars(self): return self
            def all(self): return self._rows

        monkeypatch.setattr(mkt, "async_session", lambda: _Session())

        # akshare US 列表返回含 SOX
        import pandas as pd
        df = pd.DataFrame([{"symbol": "SOX", "name": "费城半导体指数"}])
        calls = {"n": 0}
        async def _fake_to_thread(fn, *args):
            calls["n"] += 1
            return df() if calls["n"] > 1 else df

        import asyncio
        async def _fake_to_thread2(fn, *args):
            return df

        monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread2)

        out = await mkt._search_indices_akshare_fallback("费城", "US")
        assert any("SOX" in (r.get("symbol") or "") for r in out), (
            "US 指数兜底必须命中 SOX（Q6）"
        )

    @pytest.mark.asyncio
    async def test_hk_fallback_includes_static_low_vol(self, monkeypatch):
        """HK tab 搜「低波动」：静态扩展段（恒生港股通低波动变体）命中。"""
        from app.routers import market as mkt

        out = await mkt._search_indices_akshare_fallback("低波动", "HK")
        # 静态扩展段不依赖网络——必须命中
        assert any("低波动" in (r.get("name") or "") for r in out), (
            "港股低波动变体必须可由静态扩展段命中（Q4）"
        )

    @pytest.mark.asyncio
    async def test_akshare_failure_returns_empty(self, monkeypatch):
        """akshare 全失败 → []（诚实降级，不编造）。"""
        from app.routers import market as mkt

        import asyncio
        def _boom(fn, *args):
            raise RuntimeError("akshare down")
        monkeypatch.setattr(asyncio, "to_thread", _boom)

        out = await mkt._search_indices_akshare_fallback("费城", "US")
        assert out == []

    @pytest.mark.asyncio
    async def test_search_indices_local_hit_no_fallback(self, monkeypatch):
        """本地表命中 → 不触发 akshare 兜底（避免每搜触网）。"""
        from app.routers import market as mkt

        class _Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def execute(self, stmt):
                class _Row:
                    symbol = "000300"
                    name = "沪深300"
                    market = "A"
                return _Result([_Row()])
        class _Result:
            def __init__(self, rows): self._rows = rows
            def scalars(self): return self
            def all(self): return self._rows

        monkeypatch.setattr(mkt, "async_session", lambda: _Session())
        monkeypatch.setattr(mkt, "_search_indices_akshare_fallback",
                            lambda kw, m: (_ for _ in ()).throw(AssertionError("本地命中不应触网")))

        out = await mkt._search_indices("沪深", "A")
        assert out and out[0]["symbol"] == "000300"


class TestStaticIndicesExtended:
    """Q4/Q6: _STATIC_EXTRA_INDICES 补全覆盖（US/HK 索引缺失项）。"""

    def test_us_sox_present(self):
        from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES
        us_syms = {s["symbol"] for s in _STATIC_EXTRA_INDICES if s.get("market") == "US"}
        assert "SOX" in us_syms, "费城半导体指数必须入静态索引（Q6）"
        assert "IXIC" in us_syms
        assert "DJI" in us_syms

    def test_hk_low_vol_variant_present(self):
        from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES
        hk_names = [s["name"] for s in _STATIC_EXTRA_INDICES if s.get("market") == "HK"]
        assert any("低波动" in n for n in hk_names), "恒生港股通低波动变体必须入静态索引（Q4）"