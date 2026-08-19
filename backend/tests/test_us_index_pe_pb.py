"""
round30: 美股指数 PE/PB 估值（SPX multpl 主源 + Yahoo ETF 代理兜底）。

覆盖 fundamentals_fetcher.fetch_current_pe_pb 的 US 指数分支：
- SPX/^GSPC → multpl（真实指数口径）优先，失败回落 Yahoo SPY 代理
- IXIC/NDX/DJI → Yahoo QQQ/DIA ETF 代理（直连 quoteSummary，绕开 yfinance 库会话限流）
- 成功缓存 6h / 失败缓存 1h（R4-26 模式）
- 全部源失败 → None（报告诚实标注「数据源不可用」，不伪造值）

所有外部网络均 mock，无网络依赖。
"""
from unittest.mock import patch

from app.fetchers import fundamentals_fetcher as ff


def _clear_cache():
    ff.sync_memory_cache.clear()


def test_us_index_spx_pe_pb_from_multpl():
    """SPX 指数估值优先走 multpl（真实指数口径），不触 Yahoo 代理。"""
    _clear_cache()
    try:
        with patch.object(ff, "_fetch_spx_pe_pb_multpl", return_value={
                "pe_ttm": 29.65, "pb": 6.11, "source": "标普500估值(multpl)"}), \
             patch.object(ff, "_fetch_yahoo_quote_summary",
                          side_effect=AssertionError("multpl 主源不应触 Yahoo")):
            result = ff.fetch_current_pe_pb("SPX", "index")
        assert result is not None
        assert result["pe_ttm"] == 29.65
        assert result["pb"] == 6.11
        assert "multpl" in result.get("source", "")
    finally:
        _clear_cache()


def test_us_index_spx_falls_back_to_yahoo_proxy():
    """multpl 失败 → 回落直连 Yahoo SPY 代理（mock 无网络）。"""
    _clear_cache()
    try:
        with patch.object(ff, "_fetch_spx_pe_pb_multpl", return_value=None), \
             patch.object(ff, "_fetch_yahoo_quote_summary",
                          return_value={"pe": 25.85, "pb": 1.79}):
            result = ff.fetch_current_pe_pb("SPX", "index")
        assert result is not None, "SPX 指数应回落 SPY 代理估值"
        assert result["pe_ttm"] == 25.85
        assert result["pb"] == 1.79
        assert "SPY" in result.get("source", ""), f"应标注代理来源: {result}"
        # 二次调用命中成功缓存（6h），不再触源
        with patch.object(ff, "_fetch_spx_pe_pb_multpl", side_effect=AssertionError("缓存命中不应重拉")):
            cached = ff.fetch_current_pe_pb("SPX", "index")
        assert cached == result
    finally:
        _clear_cache()


def test_us_index_ixic_dji_ndx_via_yahoo_proxy():
    """IXIC/DJI/NDX 走 Yahoo ETF 代理（QQQ/DIA），PB 因 ETF 无 book 值为 None。"""
    _clear_cache()
    try:
        cases = {
            "IXIC": (30.68, "QQQ"),
            "NDX": (30.68, "QQQ"),
            "DJI": (22.13, "DIA"),
        }
        for sym, (pe, etf) in cases.items():
            with patch.object(ff, "_fetch_yahoo_quote_summary",
                              return_value={"pe": pe, "pb": None}):
                result = ff.fetch_current_pe_pb(sym, "index")
            assert result is not None, f"{sym} 应返回 {etf} 代理估值"
            assert result["pe_ttm"] == pe
            assert result.get("pb") is None, "ETF priceToBook 为空 → pb=None（诚实标注）"
            assert etf in result.get("source", ""), f"应标注 {etf} 代理来源: {result}"
    finally:
        _clear_cache()


def test_us_index_pe_missing_returns_none():
    """负向: 指数代理无 PE/PB → None（报告诚实标注不可用），失败缓存 1h。"""
    _clear_cache()
    try:
        with patch.object(ff, "_fetch_spx_pe_pb_multpl", return_value=None), \
             patch.object(ff, "_fetch_yahoo_quote_summary",
                          return_value={"pe": None, "pb": None}):
            assert ff.fetch_current_pe_pb("SPX", "index") is None
        # 失败缓存：二次调用不再触源
        with patch.object(ff, "_fetch_spx_pe_pb_multpl", side_effect=AssertionError("失败缓存不应重拉")):
            assert ff.fetch_current_pe_pb("SPX", "index") is None
    finally:
        _clear_cache()


def test_us_index_dispatch_not_hijack_us_stock():
    """非指数符号（QQQ）不被代理分支拦截，仍走美股 spot 分支。"""
    from app.fetchers import sector_fetcher as sf

    with patch.object(sf, "_fetch_us_spot_rich", return_value=[
            {"symbol": "QQQ", "name": "纳指100ETF", "industry": "-", "pe": None}]):
        assert ff.fetch_current_pe_pb("QQQ", "US") is None


def test_spx_multpl_parse_tolerates_amp_entity():
    """multpl 页面解析容忍 &amp; 实体 + meta/display 双格式（mock HTTP 无网络）。"""

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return (
                b'<html><head><meta name="description" content="S&amp;P 500 PE Ratio chart, '
                b'historic, and current data. Current S&amp;P 500 PE Ratio is 29.65, a change '
                b'of -0.21 from previous market close." /></head><body>'
                b'<div>Current S&amp;P 500 Price to Book Value : 6.11 -0.02 (-0.33%)</div>'
                b'</body></html>'
            )

    with patch("urllib.request.urlopen", return_value=_FakeResp()):
        result = ff._fetch_spx_pe_pb_multpl()
    assert result is not None
    assert result["pe_ttm"] == 29.65
    assert result["pb"] == 6.11
    assert "multpl" in result.get("source", "")


def test_yahoo_quote_summary_parses_pe_pb():
    """Yahoo quoteSummary JSON 解析——trailingPE 提取，ETF 空 priceToBook→pb=None。"""
    body = ('{"quoteSummary":{"result":[{"summaryDetail":{"trailingPE":{"raw":30.680885}},'
            '"defaultKeyStatistics":{"priceToBook":{}}}]}}')
    parsed = ff._parse_yahoo_quote_summary(body)
    assert parsed == {"pe": 30.680885, "pb": None}


def test_yahoo_quote_summary_bad_body_returns_none():
    """quoteSummary 非 JSON/缺字段 → None（诚实降级）。"""
    assert ff._parse_yahoo_quote_summary("not-json") is None
    assert ff._parse_yahoo_quote_summary('{"quoteSummary":{"result":[]}}') == {"pe": None, "pb": None}
