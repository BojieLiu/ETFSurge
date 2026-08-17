"""round27 R44 (P1) F1/F2: 预热回归修复——fund NAV 后台友好 + requests.Session 复用。

问题（round27 §1 / §15.1 R44）：预热 34.5s 回归，其中 `fetch_fund_nav` 13 次累计 16.7s
（akshare 全量历史拉取），SSL 握手 149 次累计 15-16s（无 Session 复用）。

修复（本轮）：
- F1: `fetch_fund_nav` 增 `limit` 参数（background/cheap 模式）——传入时直接走轻量
  近期净值源（天天基金 f10/lsjz），跳过 akshare `fund_open_fund_info_em` 全量历史拉取，
  使该函数在后台任务中安全调用、不拖长 startup；
- F2: `_fetch_ttj_lsjz`（fund NAV 的近期净值源）改用模块级共享 `requests.Session`
  （`_session()`，HTTP keep-alive + 连接池），复用连接、避免每次 urllib 重复 TLS 握手。

反假完成：负向断言——`fetch_fund_nav(..., limit=5)` 旧签名不接受 limit（TypeError → FAIL）；
cheap 模式必须跳过重型 akshare 调用；`_fetch_ttj_lsjz` 必须走 `_session()`（旧 urllib 不调用）。
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock

from app.fetchers import china_market as cm


@pytest.fixture(autouse=True)
def _clear_nav_cache():
    """隔离：清空 fund NAV 内存缓存，确保 cheap 模式走真实冷路径。"""
    cm._FUND_NAV_CACHE.clear()
    yield



class TestFundNavCheapMode:
    """R44 F1: limit/cheap 模式跳过重型 akshare 全量历史拉取。"""

    def test_fetch_fund_nav_limit_uses_cheap_source(self, monkeypatch):
        """传入 limit → 走轻量 ttj 源、跳过 akshare fund_open_fund_info_em（调用计数 0）。"""
        import akshare

        calls = {"akshare": 0}

        def _fake_ak(symbol, indicator):
            calls["akshare"] += 1
            return pd.DataFrame()

        monkeypatch.setattr(akshare, "fund_open_fund_info_em", _fake_ak)
        monkeypatch.setattr(
            cm, "_fetch_ttj_lsjz",
            lambda s: [{"DWJZ": "3.07", "JZZZL": "0.5", "FSRQ": "2026-08-14"}],
        )
        cm._FUND_NAV_CACHE.pop("510050", None)

        res = cm.fetch_fund_nav("510050", limit=5)
        assert res is not None, "limit/cheap 模式必须返回净值（R44 F1）"
        assert res["nav"] == 3.07
        assert calls["akshare"] == 0, "limit 模式必须跳过重型 akshare 全量拉取（R44 F1）"

    def test_fetch_fund_nav_limit_signature_accepted(self, monkeypatch):
        """旧签名不接受 limit → TypeError（确保 cheap 模式契约已落地）。"""
        import akshare

        monkeypatch.setattr(akshare, "fund_open_fund_info_em", lambda symbol, indicator: pd.DataFrame())
        monkeypatch.setattr(
            cm, "_fetch_ttj_lsjz",
            lambda s: [{"DWJZ": "1.0", "JZZZL": "0.0", "FSRQ": "2026-08-14"}],
        )
        cm._FUND_NAV_CACHE.pop("159915", None)
        # 不抛 TypeError 即通过（旧实现无 limit 形参会抛）
        res = cm.fetch_fund_nav("159915", limit=10)
        assert res is not None


class TestTtjSessionReuse:
    """R44 F2: _fetch_ttj_lsjz 复用模块级 requests.Session（避免重复 TLS 握手）。"""

    def test_ttj_lsjz_reuses_shared_session(self, monkeypatch):
        """_fetch_ttj_lsjz 必须调用 _session().get（旧 urllib.urlopen 不调用 _session）。"""
        fake_session = MagicMock()

        class _FakeResp:
            text = '{"Data":{"LSJZList":[{"FSRQ":"2026-08-14","DWJZ":"3.0687","JZZZL":"1.37"}]}}'

        fake_session.get.return_value = _FakeResp()
        monkeypatch.setattr(cm, "_session", lambda: fake_session)

        rows = cm._fetch_ttj_lsjz("510050")
        assert fake_session.get.called, "_fetch_ttj_lsjz 必须复用 _session()（R44 F2）"
        assert rows and rows[0].get("DWJZ") == "3.0687"
