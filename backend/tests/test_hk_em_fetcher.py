from __future__ import annotations
"""TDD tests for P1: HK East Money data source.

All akshare calls are mocked; no network needed.
"""
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from app.fetchers.china_market import _em_hk_realtime
from app.services.cache_service import sync_memory_cache


def _make_fake_hk_spot_df():
    """Simulate akshare stock_hk_spot_em() DataFrame with garbled (latin1) columns."""
    data = {
        "代码": ["00700", "00005", "09988"],
        "名称": ["腾讯控股", "汇丰控股", "阿里巴巴"],
        "最新价": [380.0, 68.5, 120.0],
        "涨跌幅": [2.5, -0.3, 1.8],
        "成交量": [25000000, 5000000, 18000000],
        "成交额": [9500000000, 342500000, 2160000000],
    }
    return pd.DataFrame(data)


def test_em_hk_returns_filtered_symbols():
    """_em_hk_realtime returns only requested symbols from EM HK spot data."""
    fake_df = _make_fake_hk_spot_df()

    with patch("akshare.stock_hk_spot_em", return_value=fake_df):
        results = _em_hk_realtime(["00700", "09988"])

    assert len(results) == 2
    symbols = {r["symbol"] for r in results}
    assert symbols == {"00700", "09988"}
    assert results[0]["price"] == 380.0
    assert results[0]["asset_type"] == "HK"


def test_em_hk_returns_none_on_empty():
    """_em_hk_realtime returns empty list when akshare fails."""
    sync_memory_cache.clear()
    with patch("akshare.stock_hk_spot_em", side_effect=Exception("API error")):
        results = _em_hk_realtime(["00700"])
    assert results == []


def test_em_hk_returns_empty_for_no_match():
    """_em_hk_realtime returns empty list when no symbols match."""
    fake_df = _make_fake_hk_spot_df()

    with patch("akshare.stock_hk_spot_em", return_value=fake_df):
        results = _em_hk_realtime(["99999"])
    assert results == []


# ===== folded from test_round19_p8.py =====
class TestFetchIndexHistoryHkBranch:
    """round19 P8-③: fetch_index_history 字母代码（HK 指数）走腾讯。"""

    def test_hk_alpha_code_uses_tencent(self, monkeypatch):
        """fetch_index_history('HSCI') → 腾讯 hk{code}（负向：走 A 股 akshare 链
        失败返回空 → FAIL）。"""
        from app.fetchers import china_market as cm

        tx_rows = [{"date": f"2026-08-{i:02d}", "open": 20000 + i, "high": 20100 + i,
                    "low": 19900 + i, "close": 20050 + i, "volume": 1e8} for i in range(1, 8)]
        calls = []
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history",
                            lambda s: (calls.append(s) or tx_rows))
        rows = cm.fetch_index_history("HSCI", "daily")
        assert rows == tx_rows
        assert calls == ["HSCI"], f"应传 'HSCI'（内部拼 hkHSCI），实得 {calls}"

    def test_hk_uncovered_returns_empty(self, monkeypatch):
        """腾讯不覆盖（HSAHC）→ 返回 []（前端标注「暂无行情」，负向：走 A 股链报错 → FAIL）。"""
        from app.fetchers import china_market as cm
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda s: [])
        assert cm.fetch_index_history("HSAHC", "daily") == []

    def test_a_index_keeps_akshare_chain(self, monkeypatch):
        """数字代码（A 股指数）保持原 akshare 链（不误入 HK 分支）。"""
        from app.fetchers import china_market as cm
        import pandas as pd

        a_rows = [{"date": "2026-08-11", "open": 3900.0, "high": 3910.0, "low": 3890.0,
                   "close": 3905.0, "volume": 1e9}]
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history",
                            lambda s: pytest.fail("A 股指数不应走腾讯 HK 分支"))

        df = pd.DataFrame([{"date": "2026-08-11", "open": 3900.0, "high": 3910.0,
                            "low": 3890.0, "close": 3905.0, "volume": 1e9}])
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: df)
        rows = cm.fetch_index_history("000001", "daily")
        assert rows and rows[0]["收盘"] == pytest.approx(3905.0)
