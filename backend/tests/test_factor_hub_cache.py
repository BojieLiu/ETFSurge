# -*- coding: utf-8 -*-
"""round30 R85: 因子路径接 Hub 缓存（两缓存域断裂修复）+ 缺数据填 None。

根因（§14.4）：design-data warmup 只填充 hub._kline_cache_rows，而
factor_registry._fetch_market_data 的数据获取顺序是 ①模块级 _kline_cache（冷）→
②SourceRegistry 电路 → ③live fetch（盘后空）→ 因子全空 → 占位 RSI 50.0/动量 +0.300
全标的同值冒充真实评分。

修复：
  ① _fetch_market_data 在 live fetch 前先读 hub.get_kline_rows_any（已热身缓存）；
  ② _compute_rsi_14/_compute_kdj_* 等缺数据改填 None（下游区分「真实 0」与「无数据」）；
  ③ compute() 遇 None 不产出占位（z-score 跳过 None）。

无网络：全部 monkeypatch。
"""
import pytest


def _rows(seed=1.0, n=40):
    """构造 hub 缓存样式的行式 K 线数据。"""
    out = []
    px = 100.0
    for i in range(n):
        px += (i % 5) * 0.1
        out.append({
            "date": f"2026-07-{i % 28 + 1:02d}",
            "open": px, "high": px + 0.2, "low": px - 0.1,
            "close": px, "volume": int(1e6 + i * 1000),
        })
    return out


@pytest.fixture
def patch_hub_cache(monkeypatch):
    """hub._kline_cache_rows 已热身（模拟 design-data warmup 后），模块缓存冷。"""
    from app.factors import factor_registry
    from app.services.market_data_hub import market_data_hub

    factor_registry._kline_cache.clear()
    factor_registry._kline_cache_ts = 0.0
    rows = {f"{c}": _rows(i) for i, c in enumerate(["510300", "518880", "512880"])}
    monkeypatch.setattr(market_data_hub, "get_kline_rows_any",
                        lambda sym: rows.get(sym))
    monkeypatch.setattr(market_data_hub, "get_kline_rows",
                        lambda sym, max_age=300: rows.get(sym))
    # 防止 live fetch 被调用（R85 应命中 hub 缓存）
    monkeypatch.setattr(market_data_hub, "get_history",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("R85: live fetch should not be called")))
    return rows


class TestHubCacheReadR85:
    @pytest.mark.asyncio
    async def test_fetch_market_data_reads_hub_cache(self, patch_hub_cache):
        """模块缓存冷 + hub 缓存热 → _fetch_market_data 必须读到 hub 缓存数据。"""
        from app.factors.factor_registry import registry

        data = await registry._fetch_market_data(["510300", "518880", "512880"])
        assert data, "factor data should not be empty"
        for sym in ("510300", "518880", "512880"):
            row = data.get(sym) or {}
            closes = row.get("close") or []
            assert len(closes) >= 5, f"{sym} close 数组为空（未读 hub 缓存）"
            assert row.get("_fetch_error") is None

    @pytest.mark.asyncio
    async def test_no_live_fetch_when_hub_warm(self, patch_hub_cache):
        """hub 缓存命中时不得触发 live fetch（get_history 被 patch 为抛错）。"""
        from app.factors.factor_registry import registry

        # patch_hub_cache 中 get_history 抛 AssertionError → 若被调用测试即失败
        data = await registry._fetch_market_data(["510300"])
        assert (data.get("510300") or {}).get("close")


class TestMissingDataReturnsNoneR85:
    def test_rsi_short_data_returns_none(self):
        """R85 ②：缺数据 RSI 返回 None（不得再返回 50.0 占位冒充中性）。"""
        from app.factors.factor_registry import _compute_rsi_14
        assert _compute_rsi_14({"close": []}) is None
        assert _compute_rsi_14({"close": [100.0] * 5}) is None

    def test_kdj_short_data_returns_none(self):
        """缺数据 KDJ 返回 None（不得再返回 50.0 占位）。"""
        from app.factors.factor_registry import _compute_kdj_k, _compute_kdj_d, _compute_kdj_j
        data = {"high": [], "low": [], "close": []}
        assert _compute_kdj_k(data) is None
        assert _compute_kdj_d(data) is None
        assert _compute_kdj_j(data) is None

    def test_macd_short_data_returns_none(self):
        """缺数据 MACD 返回 None（不得再返回 0.0 占位）。"""
        from app.factors.factor_registry import _compute_macd
        assert _compute_macd({"close": [100.0] * 5}) is None

    def test_sma_short_data_returns_none(self):
        """缺数据 SMA 返回 None。"""
        from app.factors.factor_registry import _compute_sma_5
        assert _compute_sma_5({"close": [100.0] * 3}) is None

    def test_ln_mcap_zero_returns_none(self):
        """total_mv 缺失 → ln_mcap 返回 None（真实 0 与无数据区分）。"""
        from app.factors.factor_registry import _compute_ln_mcap
        assert _compute_ln_mcap({"total_mv": 0}) is None


class TestComputeNoPlaceholderR85:
    @pytest.mark.asyncio
    async def test_compute_missing_data_not_all_50(self, monkeypatch):
        """负向：全缺数据时 compute 不得产出「RSI 50.0 全同值」冒充。"""
        from app.factors import factor_registry
        from app.factors.factor_registry import registry

        # 模块缓存空 + hub 缓存空 + live fetch 空（盘后模拟）
        factor_registry._kline_cache.clear()
        factor_registry._kline_cache_ts = 0.0
        from app.services.market_data_hub import market_data_hub
        monkeypatch.setattr(market_data_hub, "get_kline_rows_any", lambda s: None)
        monkeypatch.setattr(market_data_hub, "get_history", lambda *a, **k: [])
        monkeypatch.setattr(registry, "_inject_macro_data", lambda *a, **k: None)

        result = await registry.compute(
            ["510300", "518880"],
            codes=["technical.rsi.rsi_14", "technical.macd.macd", "technical.signal.overall"],
        )
        for sym in ("510300", "518880"):
            row = result.get(sym) or {}
            # RSI 必须不是 50.0 占位（None → 0.0 由下游兜底，但绝不能是「50.0 中性」）
            assert row.get("technical.rsi.rsi_14") != 50.0, f"{sym} RSI 仍是占位 50.0"
