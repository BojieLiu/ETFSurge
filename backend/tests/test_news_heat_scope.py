"""F12 (round6 §15.4): sentiment news_heat 按标的新闻/市态级降级。

背景：factor_registry 把 get_news_headlines()（全市场新闻）写入每个标的的
news_items → _compute_news_heat 对所有标的值相同（全 100 顶格），无区分度
+ 误导。修复：优先标的相关新闻（get_news_stock）；不可用 → 市态级降级并
标注 news_scope（全市场热度，非个股值）。
"""
import pytest

from app.factors import factor_registry as fr


def _news_items():
    return [{"title": f"n{i}", "stars": i % 5 + 1, "level": "利好"} for i in range(10)]


def _patch_kline(monkeypatch):
    """K 线路径全 mock：run_sync 直连 + 无缓存 + 无网络。"""
    from app.core import async_utils

    def _fake_history(symbol, market="A", period="daily", timeout=20):
        return [{"close": 4.0 + i * 0.01, "high": 4.1, "low": 3.9, "volume": 1e7,
                 "total_mv": 5e9, "float_mv": 3e9} for i in range(30)]

    async def _direct(call, *args, timeout=None, **kwargs):
        # fetch_one 的 call 是 hub.get_history——直接返回 fake K 线（不触网）
        return _fake_history(*args, **kwargs)

    monkeypatch.setattr(async_utils, "run_sync", _direct)
    monkeypatch.setattr(fr, "_get_cached_kline", lambda symbols: None)
    return _fake_history


async def _fetch_with_news(monkeypatch, stock_news):
    """构造经真实 _fetch_market_data（K 线 mock、新闻 mock）后的单标的 data。"""
    from app.services.market_data_hub import market_data_hub as hub_inst

    monkeypatch.setattr(hub_inst, "get_news_stock", lambda sym: stock_news)
    monkeypatch.setattr(hub_inst, "get_news_headlines", lambda: _news_items())
    monkeypatch.setattr(hub_inst, "get_market_sentiment", lambda: {"sentiment_index": 50.0})
    monkeypatch.setattr(hub_inst, "get_fund_nav", lambda sym, **kw: {})
    _patch_kline(monkeypatch)
    reg = fr.FactorRegistry()
    data = await reg._fetch_market_data(["510300"])
    return data.get("510300", {})


async def test_stock_news_used_when_available(monkeypatch):
    """标的新闻可用 → news_items 用标的新闻且 news_scope=stock。"""
    stock_news = [{"title": "个股专属新闻", "stars": 5, "level": "利好"}] * 5
    d = await _fetch_with_news(monkeypatch, stock_news)
    assert d.get("news_scope") == "stock"
    assert d.get("news_items") == stock_news[-30:]
    # 标的新闻的 news_heat 有区分度来源
    assert fr._compute_news_heat(d) > 0


async def test_market_fallback_marks_scope(monkeypatch):
    """标的新闻不可用 → 市态级降级 + news_scope=market 标注。"""
    d = await _fetch_with_news(monkeypatch, [])
    assert d.get("news_scope") == "market"
    assert d.get("news_items"), "市态级降级仍应注入全市场新闻（供 regime 输入）"
    # 全市场新闻注入时标注"非个股值"——前端/明细据此避免误导
    assert d.get("news_items") == _news_items()[-30:]
