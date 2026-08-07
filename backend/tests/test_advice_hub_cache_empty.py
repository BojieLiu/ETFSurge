"""
O3 (docs/archived/round8-rediagnosis.md §7 P2-新): hub 缓存断裂——投顾快照空。

P2 根因: market_service.py 非交易时段 stale 分支把 _global_indices_cache 各 region
重建为空 list 写回；_build_advice_market_snapshot 兜底只读 30s TTL 的
_global_indices_cache（可能被清空），不读 24h 兜底 _global_indices_last_ok（与
/indices/global 同一管道，含磁盘持久化）→ 投顾输出"暂无实时指数/板块"。

修复: 指数兜底改为 last_ok 优先（cache 次之）；get_sector_momentum 空时回退
get_sector_industry；两套缓存路径同步。
"""

import pytest

from app.routers.analysis import _build_advice_market_snapshot


class FakeHub:
    def __init__(self, index=None, sentiment=None, regime=None, sector=None, sector_industry=None, news=None):
        self._index = index
        self._sentiment = sentiment
        self._regime = regime
        self._sector = sector
        self._sector_industry = sector_industry
        self._news = news

    def get_market_regime(self):
        return self._regime

    def get_market_sentiment(self):
        return self._sentiment

    def get_index_realtime(self):
        return self._index

    def get_sector_momentum(self):
        return self._sector

    def get_sector_industry(self, limit=80):
        return self._sector_industry

    def get_news_headlines(self):
        return self._news


def _patch_ms(monkeypatch, cache, last_ok):
    """替换 market_service._global_indices_cache / _global_indices_last_ok。"""
    import app.routers.analysis as ar
    import app.services.market_service as ms
    monkeypatch.setattr(ms, "_global_indices_cache", cache)
    monkeypatch.setattr(ms, "_global_indices_last_ok", last_ok)
    return ar


class TestIndexFallbackToLastOk:
    def test_stale_cache_empty_falls_back_to_last_ok(self, monkeypatch):
        """_global_indices_cache['A股'] 被 stale 分支清空 → 兜底 _global_indices_last_ok。"""
        ar = _patch_ms(monkeypatch,
                       cache={"A股": [], "HK": [], "US": []},
                       last_ok={"A股": [{"name": "上证指数", "price": 3878.43, "change_pct": 1.47}]})
        hub = FakeHub(index=[], regime="range_bound", sentiment={"sentiment_label": "谨慎", "sentiment_index": 34.2})
        text = _build_advice_market_snapshot("当前A股市场怎么配置", hub)
        assert "上证指数" in text
        assert "3878.43" in text
        assert "+1.47%" in text

    def test_both_empty_keeps_graceful(self, monkeypatch):
        """两缓存都空 → 快照不含指数行但不抛异常（市态/情绪仍在）。"""
        ar = _patch_ms(monkeypatch, cache={}, last_ok={})
        hub = FakeHub(index=[], regime="range_bound", sentiment={"sentiment_label": "谨慎", "sentiment_index": 34.2})
        text = _build_advice_market_snapshot("大盘怎么样", hub)
        assert "市场状态: range_bound" in text
        assert "市场情绪" in text


class TestSectorFallback:
    def test_momentum_empty_falls_back_to_industry(self, monkeypatch):
        """get_sector_momentum 空 → 回退 get_sector_industry（板块热力不缺失）。"""
        ar = _patch_ms(monkeypatch, cache={}, last_ok={})
        hub = FakeHub(index=[], sector=[], sector_industry=[
            {"sector_name": "半导体", "change_pct": 5.72},
        ])
        text = _build_advice_market_snapshot("今天哪些板块值得关注", hub)
        assert "半导体" in text

    def test_sector_hit_with_momentum(self, monkeypatch):
        """momentum 有数据时不触发回退（原路径优先）。"""
        ar = _patch_ms(monkeypatch, cache={}, last_ok={})
        hub = FakeHub(index=[], sector=[{"sector_name": "新能源", "change_pct": 2.1}], sector_industry=[])
        text = _build_advice_market_snapshot("板块轮动怎么看", hub)
        assert "新能源" in text
        assert "2.10%" in text
