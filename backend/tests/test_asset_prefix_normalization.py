"""
O22 (docs/archived/round8-rediagnosis.md §7 §5.1G): 自选 A 股股票实时为空——sh/sz 前缀匹配失败。

根因（2026-08-07 容器实测）: fetch_a_stock_realtime('sh688981') → 空——带 sh/sz
前缀在底层源（tencent/sina/mootdx）取数阶段就失败（_exchange 把 sh688981 判成 sz →
拼出 szsh688981 → 恒空）；比对层 item["symbol"]==symbol 精确匹配也不命中。

修复（已拍板 4 项）: ① fetch_a_stock_realtime/fetch_a_stock_batch 入口剥 sh/sz/bj
前缀（底层源拿到纯数字）；② _exchange 剥前缀（双保险）；③ get_asset_realtime
比对层归一化（双保险）；④ search/入库规约纯数字 symbol。
"""

import pytest
from unittest.mock import patch

from app.fetchers import china_market as cm
from app.services import market_service as ms


class TestExchangeStripsPrefix:
    def test_exchange_with_prefix(self):
        """_exchange 对带前缀输入正确判定交易所（sh688981→sh / sz000001→sz）。"""
        assert cm._exchange("sh688981") == "sh"
        assert cm._exchange("sz000001") == "sz"
        assert cm._exchange("600519") == "sh"
        assert cm._exchange("000001") == "sz"

    def test_strip_a_prefix(self):
        assert cm._strip_a_prefix("sh688981") == "688981"
        assert cm._strip_a_prefix("SZ000001") == "000001"
        assert cm._strip_a_prefix("bj430047") == "430047"
        assert cm._strip_a_prefix("600519") == "600519"


class TestFetchStripsPrefix:
    def test_fetch_a_stock_realtime_receives_pure_digit(self, monkeypatch):
        """fetch_a_stock_realtime('sh688981') → 底层源收到纯数字 '688981'（验收⑤）。"""
        with patch.object(cm, "_mootdx_realtime", return_value=[]) as m_mootdx, \
             patch.object(cm, "_tencent_realtime", return_value=[]) as m_tencent, \
             patch.object(cm, "_sina_realtime", return_value=[]) as m_sina:
            cm.fetch_a_stock_realtime("sh688981")
            assert m_mootdx.call_args[0][0] == ["688981"]
            assert m_tencent.call_args[0][0] == ["688981"]
            assert m_sina.call_args[0][0] == ["688981"]

    def test_fetch_a_stock_batch_strips_prefix(self, monkeypatch):
        with patch.object(cm, "_mootdx_realtime", return_value=[]) as m_mootdx:
            cm.fetch_a_stock_batch(["sh688981", "sz000001"])
            assert m_mootdx.call_args[0][0] == ["688981", "000001"]

    def test_tencent_sina_sym_key_stripped(self):
        """_tencent/_sina 的 A 股前缀拼接使用纯数字（不产生 szsh688981）。"""
        with patch.object(cm, "_session") as m_session:
            resp = m_session.return_value.get.return_value
            resp.text = ""
            cm._tencent_realtime(["sh688981"], "A")
            url = m_session.return_value.get.call_args[0][0]
            assert "szsh688981" not in url
            assert "q=sh688981" in url


class TestGetAssetRealtimeMatch:
    @pytest.mark.asyncio
    async def test_prefixed_symbol_matches_pure_digit_result(self, monkeypatch):
        """get_asset_realtime('sh688981') 与 fetch 返回 '688981' 行能匹配（验收④）。"""
        import app.services.market_service as ms_mod
        fake_rows = [{"symbol": "688981", "name": "中芯国际", "price": 126.01, "change_pct": 1.5}]

        async def fake_call(fn, *args, **kwargs):
            return fake_rows

        monkeypatch.setattr(ms_mod, "_call", fake_call)
        ms_mod._asset_realtime_cache.clear()
        result = await ms.get_asset_realtime("sh688981", "A")
        assert result is not None
        assert result["name"] == "中芯国际"

    @pytest.mark.asyncio
    async def test_hk_suffix_normalized(self, monkeypatch):
        """HK 分支：'00700.HK' 与 '00700' 归一化后匹配。"""
        import app.services.market_service as ms_mod
        fake_rows = [{"symbol": "00700", "name": "腾讯控股", "price": 492.2, "change_pct": 0.5}]

        async def fake_call(fn, *args, **kwargs):
            return fake_rows

        monkeypatch.setattr(ms_mod, "_call", fake_call)
        ms_mod._asset_realtime_cache.clear()
        result = await ms.get_asset_realtime("00700.HK", "HK")
        assert result is not None
        assert result["name"] == "腾讯控股"
