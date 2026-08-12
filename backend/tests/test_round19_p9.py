"""
round19 P9（问题 9：美股自选技术分析显示数据不足）测试（2026-08-12 实施）：
- _tickflow_kline 扩 US/HK 分支（旧硬编码 SH/SZ 仅 A 股；负向：SPY → [] → FAIL）
- _fetch_sina_us_daily 新浪全量兜底（列名映射）
- _fetch_akshare_history US 降级链重排：akshare(3s 快速失败) → TickFlow → alphavantage
  → 新浪 → finnhub(3s)；key 缺失/异常 → [] 不抛错
"""

import pytest
import pandas as pd
from unittest.mock import MagicMock


def _us_df(n=500):
    import datetime as dt
    rows = []
    base = dt.date(2024, 1, 1)
    for i in range(n):
        d = base + dt.timedelta(days=i)
        rows.append({"trade_date": d.strftime("%Y-%m-%d"), "open": 100 + i * 0.01,
                     "high": 101 + i * 0.01, "low": 99 + i * 0.01,
                     "close": 100.5 + i * 0.01, "volume": 1e6, "amount": 1e8})
    return pd.DataFrame(rows)


class TestTickflowKlineUsHk:
    """round19 P9-②: _tickflow_kline 支持 US/HK 分支（复用 _tickflow_symbol）。"""

    def _patch_key(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.tickflow_api_key", "tk_test")

    def test_tickflow_kline_us_returns_rows(self, monkeypatch):
        """_tickflow_kline('SPY','US') → 500 行（负向：US 分支不支持 → [] → FAIL）。"""
        from app.fetchers import china_market as cm
        self._patch_key(monkeypatch)
        df = _us_df(500)
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: df)
        rows = cm._tickflow_kline("SPY", "daily")
        assert len(rows) >= 30, f"US 应返回 ≥30 行，实得 {len(rows)}"
        assert rows[0]["收盘"] == pytest.approx(100.5, rel=1e-6)
        assert rows[-1]["日期"]  # 日期非空

    def test_tickflow_kline_hk_symbol_mapped(self, monkeypatch):
        """港股显式后缀 00700.HK → tf_sym=00700.HK（不误映射 SZ）。"""
        from app.fetchers import china_market as cm
        self._patch_key(monkeypatch)
        captured = {}

        class _FakeKlines:
            def get(self, sym, period="1d", count=500, as_dataframe=True):
                captured["sym"] = sym
                return _us_df(30)

        class _FakeTickFlow:
            class TickFlow:
                def __init__(self, api_key):
                    self.klines = _FakeKlines()

        import sys
        monkeypatch.setitem(sys.modules, "tickflow", _FakeTickFlow)
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: fn())
        rows = cm._tickflow_kline("00700.HK", "daily")
        assert captured.get("sym") == "00700.HK", f"HK 应映射为 00700.HK，实得 {captured}"
        assert len(rows) >= 30

    def test_tickflow_kline_exception_returns_empty(self, monkeypatch):
        """TickFlow 抛异常 → []（降级链继续，负向：抛异常中断 → FAIL）。"""
        from app.fetchers import china_market as cm
        self._patch_key(monkeypatch)

        def boom(fn, **k):
            raise RuntimeError("tickflow down")

        monkeypatch.setattr(cm, "run_in_thread", boom)
        assert cm._tickflow_kline("SPY", "daily") == []


class TestFetchSinaUsDaily:
    """round19 P9-②: 新浪 stock_us_daily 全量兜底（英文列名 → 系统格式）。"""

    def test_column_mapping(self, monkeypatch):
        from app.fetchers import china_market as cm
        df = pd.DataFrame([
            {"date": "2026-08-11", "open": 770.0, "high": 775.0, "low": 768.0,
             "close": 770.56, "volume": 1.2e7},
            {"date": "2026-08-12", "open": 771.0, "high": 772.0, "low": 769.0,
             "close": 771.905, "volume": 1.1e7},
        ])
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: df)
        rows = cm._fetch_sina_us_daily("SPY")
        assert len(rows) == 2
        assert rows[-1]["日期"] == "2026-08-12"
        assert rows[-1]["收盘"] == pytest.approx(771.905)
        assert rows[-1]["开盘"] == pytest.approx(771.0)

    def test_failure_returns_empty(self, monkeypatch):
        from app.fetchers import china_market as cm

        def boom(fn, **k):
            raise RuntimeError("sina down")

        monkeypatch.setattr(cm, "run_in_thread", boom)
        assert cm._fetch_sina_us_daily("SPY") == []


class TestAkshareHistoryUsChain:
    """round19 P9-③: US 降级链重排——akshare(3s) → TickFlow → alphavantage → sina → finnhub(3s)。"""

    def _setup(self, monkeypatch, *, akshare_df=None, tickflow=None, av=None, sina=None, fh=None):
        from app.fetchers import china_market as cm
        import app.fetchers.global_markets_fetcher as gmf
        calls = []

        def _run_in_thread(fn, timeout=8, executor="long"):
            calls.append(("thread", timeout))
            return fn()

        monkeypatch.setattr(cm, "run_in_thread", _run_in_thread)
        monkeypatch.setattr(cm, "_tickflow_kline", lambda s, p: (calls.append(("tickflow", s)) or tickflow or []))
        monkeypatch.setattr(cm, "_fetch_sina_us_daily", lambda s: (calls.append(("sina", s)) or sina or []))
        monkeypatch.setattr(gmf, "fetch_daily_alphavantage",
                            lambda s: (calls.append(("av", s)) or av or []))
        monkeypatch.setattr(gmf, "fetch_candles",
                            lambda s, p: (calls.append(("finnhub", s)) or fh or []))
        # akshare 主源：run_in_thread 里 _p() 调 ak.stock_us_hist —— mock 返回空 df
        import pandas as pd
        monkeypatch.setattr("builtins.__import__", self._fake_ak_import(akshare_df))
        return cm, calls

    @staticmethod
    def _fake_ak_import(akshare_df):
        orig_import = __import__  # patch 前的原始 __import__（避免递归）

        def fake_import(name, *args, **kwargs):
            if name == "akshare":
                class _Ak:
                    @staticmethod
                    def stock_zh_a_hist(symbol=None, period=None, adjust=None):
                        return pd.DataFrame()

                    @staticmethod
                    def stock_hk_hist(symbol=None, period=None):
                        return pd.DataFrame()

                    @staticmethod
                    def stock_us_hist(symbol=None, period=None, adjust=None):
                        return akshare_df if akshare_df is not None else pd.DataFrame()
                return _Ak()
            return orig_import(name, *args, **kwargs)
        return fake_import

    def test_us_chain_order_akshare_3s_then_fallback(self, monkeypatch):
        """akshare 空 → TickFlow 命中（不继续往下）；akshare 超时 3s。"""
        from app.fetchers import china_market as cm
        tf_rows = [{"日期": "2026-08-12", "收盘": 771.9}]
        cm, calls = self._setup(monkeypatch, akshare_df=pd.DataFrame(), tickflow=tf_rows)
        out = cm._fetch_akshare_history("SPY", "US", "daily")
        assert out == tf_rows
        thread_timeouts = [c[1] for c in calls if c[0] == "thread"]
        assert 3 in thread_timeouts, f"US akshare 应 3s 快速失败，实得 {thread_timeouts}"
        assert ("tickflow", "SPY") in calls

    def test_us_chain_full_fallback_order(self, monkeypatch):
        """akshare → TickFlow → av → sina 全空时走 finnhub；顺序验证。"""
        from app.fetchers import china_market as cm
        fh_rows = [{"date": "2026-08-12", "close": 771.9}]
        cm, calls = self._setup(monkeypatch, akshare_df=pd.DataFrame(),
                                tickflow=[], av=[], sina=[], fh=fh_rows)
        out = cm._fetch_akshare_history("SPY", "US", "daily")
        assert out == fh_rows
        seq = [c[0] for c in calls]
        # 顺序: akshare 主源(thread) → tickflow → alphavantage(thread) → sina → finnhub(thread)
        assert seq.index("tickflow") < seq.index("av") < seq.index("sina") < seq.index("finnhub"), \
            f"US 降级链顺序应为 tickflow→av→sina→finnhub，实得 {seq}"

    def test_us_all_fail_returns_empty_no_throw(self, monkeypatch):
        from app.fetchers import china_market as cm
        cm, calls = self._setup(monkeypatch, akshare_df=pd.DataFrame(),
                                tickflow=[], av=[], sina=[], fh=[])
        out = cm._fetch_akshare_history("SPY", "US", "daily")
        assert out == []

    def test_hk_chain_tencent_preserved(self, monkeypatch):
        """HK 链保持 finnhub → av → 腾讯独立兜底（不引入新浪/变更语义）。"""
        from app.fetchers import china_market as cm
        tx_rows = [{"日期": "2026-08-12", "收盘": 461.6}]
        calls = []

        def _run_in_thread(fn, timeout=8, executor="long"):
            calls.append(("thread", timeout))
            return fn()

        import app.fetchers.global_markets_fetcher as gmf
        monkeypatch.setattr(cm, "run_in_thread", _run_in_thread)
        monkeypatch.setattr(gmf, "fetch_daily_alphavantage", lambda s: [])
        monkeypatch.setattr(gmf, "fetch_candles", lambda s, p: [])
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda s: tx_rows)
        # akshare 主源 mock（返回空 df，避免真实网络）
        monkeypatch.setattr("builtins.__import__", TestAkshareHistoryUsChain._fake_ak_import(pd.DataFrame()))
        out = cm._fetch_akshare_history("00700", "HK", "daily")
        assert out == tx_rows, "HK 全链失败后应走腾讯独立兜底"
