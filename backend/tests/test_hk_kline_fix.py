"""
O2 (docs/archived/round8-rediagnosis.md §7 P1-新): 港股 K 线全链路修复。

现象: /market/history/00700?asset_type=HK 返回 0 根——finnhub 403 → alphavantage
传 "00700"（需 "0700.HK"）恒空 → akshare get_k_data 是 A 股接口。且 symbol-analysis
的 K 线（9.49-17.6）与实时价（492.2）脱钩数十倍（LLM 主动声明数据矛盾）。

修复: ① alphavantage 调用前做 HK 符号格式转换（00700 → 0700.HK）；② get_history
HK 分支 K 线与实时价一致性校验——最高/最新价与实时价差异 >50% 视为数据源错误，
丢弃返回空（不再喂 LLM 失真 K 线）。
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.fetchers import china_market as cm
from app.services import market_service as ms


class TestAvSymbolConversion:
    def test_hk_symbol_padded_for_alphavantage(self):
        """00700 → 0700.HK（Alpha Vantage 港股符号格式）。"""
        assert cm._alphavantage_symbol("00700", "HK") == "0700.HK"
        assert cm._alphavantage_symbol("09988", "HK") == "9988.HK"
        assert cm._alphavantage_symbol("AAPL", "US") == "AAPL"
        assert cm._alphavantage_symbol("510300", "A") == "510300"

    def test_fetch_akshare_history_uses_converted_symbol(self, monkeypatch):
        """alphavantage 兜底收到转换后的符号（0700.HK）而非裸 00700。"""
        captured = {}

        def fake_av(symbol, outputsize="compact"):
            captured["symbol"] = symbol
            return None

        def fake_fh(symbol, resolution="D"):
            return None

        monkeypatch.setattr(cm, "global_markets_fetcher", type("F", (), {
            "fetch_candles": staticmethod(fake_fh),
            "fetch_daily_alphavantage": staticmethod(fake_av),
        }))
        calls = []
        # 第 1 次（akshare _p）→ None；后续（fh/av）→ 执行 fn
        monkeypatch.setattr(cm, "run_in_thread",
                            lambda fn, timeout=8, executor="long": (
                                calls.append(1) or (None if len(calls) == 1 else fn())
                            ))
        # round9 P1-1: 腾讯港股日 K 兜底在测试之后加入——测试环境网络可达时返回真实
        # 数据，破坏「链断裂 → 空」断言；补 mock 保持测试意图（只验符号转换）。
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda symbol: None)
        # round20 P0-4: HK 分支 akshare 空后先走 TickFlow（真实网络）——补 mock 返回
        # 空，避免网络可达时提前返回真实数据（pre-existing flaky：全量 -n4 过、单独跑挂）。
        monkeypatch.setattr(cm, "_tickflow_kline", lambda symbol, period, asset_type: None)

        rows = cm._fetch_akshare_history("00700", "HK", "daily")
        assert captured.get("symbol") == "0700.HK", \
            f"alphavantage 应收到 0700.HK，实得 {captured.get('symbol')}"
        assert rows == []  # fh/av 都空 → 空（链断裂但符号已正确）


class TestHkKlineRealtimeConsistency:
    @pytest.mark.asyncio
    async def test_inconsistent_hk_kline_discarded(self, monkeypatch):
        """K 线最高价与实时价差异 >50% → 丢弃（不再喂 LLM 失真数据）。"""
        import app.services.market_service as ms_mod

        async def fake_history(symbol, asset_type, period):
            # 脱钩 K 线：close 9.49（旧 bug 数据）
            return [
                {"date": "2026-08-01", "open": 9.4, "high": 9.6, "low": 9.2, "close": 9.49, "volume": 100},
                {"date": "2026-08-04", "open": 9.5, "high": 9.7, "low": 9.3, "close": 9.55, "volume": 120},
            ]

        async def fake_rt(symbol, timeout=8):
            return [{"symbol": "00700", "name": "腾讯控股", "price": 492.2}]

        monkeypatch.setattr(ms_mod, "_call", AsyncMock(side_effect=[
            [  # fetch_history 返回脱钩 K 线
                {"date": "2026-08-01", "open": 9.4, "high": 9.6, "low": 9.2, "close": 9.49, "volume": 100},
                {"date": "2026-08-04", "open": 9.5, "high": 9.7, "low": 9.3, "close": 9.55, "volume": 120},
            ],
            [{"symbol": "00700", "name": "腾讯控股", "price": 492.2}],  # fetch_hk_stock_realtime
        ]))
        from app.services.market_data_hub import market_data_hub as _hub
        monkeypatch.setattr(_hub, "get_kline_rows", lambda *a, **k: [])
        monkeypatch.setattr(_hub, "get_kline_rows_any", lambda *a, **k: [])

        result = await ms.get_history("00700", "HK", "daily")
        assert result == [], "脱钩 K 线应被一致性校验丢弃（返回空降级）"

    @pytest.mark.asyncio
    async def test_consistent_hk_kline_kept(self, monkeypatch):
        """K 线与实时价一致（差异 <50%）→ 保留。"""
        import app.services.market_service as ms_mod

        async def fake_history(symbol, asset_type, period):
            return [
                {"date": "2026-08-01", "open": 490, "high": 495, "low": 485, "close": 492.2, "volume": 100},
                {"date": "2026-08-04", "open": 492, "high": 498, "low": 490, "close": 496.0, "volume": 120},
            ]

        async def fake_rt(symbol, timeout=8):
            return [{"symbol": "00700", "name": "腾讯控股", "price": 492.2}]

        monkeypatch.setattr(ms_mod, "_call", AsyncMock(side_effect=[
            [  # fetch_history 返回一致 K 线
                {"date": "2026-08-01", "open": 490, "high": 495, "low": 485, "close": 492.2, "volume": 100},
                {"date": "2026-08-04", "open": 492, "high": 498, "low": 490, "close": 496.0, "volume": 120},
            ],
            [{"symbol": "00700", "name": "腾讯控股", "price": 492.2}],
        ]))
        from app.services.market_data_hub import market_data_hub as _hub
        monkeypatch.setattr(_hub, "get_kline_rows", lambda *a, **k: [])
        monkeypatch.setattr(_hub, "get_kline_rows_any", lambda *a, **k: [])

        result = await ms.get_history("00700", "HK", "daily")
        assert len(result) == 2, "一致 K 线应保留"


class TestP019HkKlineTencentFirst:
    """P0-19 (round16 3.20): HK K 线降级链 8s 截断——腾讯前置 + 超时放宽。"""

    def test_fetch_history_hk_tries_tencent_first(self, monkeypatch):
        """fetch_history HK 分支先试腾讯——腾讯命中即返回，不走 akshare 长链
        （负向：腾讯可命中却被 akshare 8s 超时截断 → FAIL）。"""
        tx_rows = [{"date": "2026-08-01", "open": 490, "close": 492.2, "high": 495, "low": 485, "volume": 100}]
        called = {"akshare": False}

        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda symbol: tx_rows)

        def fake_akshare_history(*a, **k):
            called["akshare"] = True
            return []

        monkeypatch.setattr(cm, "_fetch_akshare_history", fake_akshare_history)

        rows = cm.fetch_history("00700", "HK", "daily")
        assert rows == tx_rows, "腾讯前置命中应直接返回"
        assert called["akshare"] is False, "腾讯命中后不得再走 akshare 长链"

    @pytest.mark.asyncio
    async def test_get_history_hk_timeout_broadened(self, monkeypatch):
        """get_history HK/US 调用 fetch_history 超时放宽到 20s（旧 8s 截断腾讯前）。"""
        import app.services.market_service as ms_mod
        captured = {"timeouts": [], "args": []}

        async def fake_call(fn, *args, timeout=8):
            captured["timeouts"].append(timeout)
            captured["args"].append(args)
            return [{"date": "2026-08-01", "open": 1, "close": 1, "high": 1, "low": 1, "volume": 1}]

        monkeypatch.setattr(ms_mod, "_call", fake_call)
        from app.services.market_data_hub import market_data_hub as _hub
        monkeypatch.setattr(_hub, "get_kline_rows", lambda *a, **k: [])
        monkeypatch.setattr(_hub, "get_kline_rows_any", lambda *a, **k: [])

        result = await ms.get_history("00700", "HK", "daily")
        # 第一次调用是 fetch_history（HK 链应放宽到 20s）；后续为一致性校验（8s）
        assert captured["timeouts"][0] == 20, \
            f"HK fetch_history 超时应放宽到 20s，首次调用实得 {captured['timeouts'][0]}"
        assert result

    @pytest.mark.asyncio
    async def test_get_history_hk_tencent_independent_fallback(self, monkeypatch):
        """get_k_data 空后 HK 补腾讯独立兜底（不依赖 akshare 链）。"""
        import app.services.market_service as ms_mod
        tx_rows = [{"date": "2026-08-01", "open": 1, "close": 1, "high": 1, "low": 1, "volume": 1}]
        calls = {"n": 0}

        async def fake_call(fn, *args, timeout=8):
            calls["n"] += 1
            if calls["n"] == 1:
                return []  # fetch_history 空
            return []  # get_k_data 空

        monkeypatch.setattr(ms_mod, "_call", fake_call)
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda symbol: tx_rows)
        from app.services.market_data_hub import market_data_hub as _hub
        monkeypatch.setattr(_hub, "get_kline_rows", lambda *a, **k: [])
        monkeypatch.setattr(_hub, "get_kline_rows_any", lambda *a, **k: [])

        result = await ms.get_history("09988", "HK", "daily")
        assert result == tx_rows, "get_k_data 空后应走腾讯独立兜底"
