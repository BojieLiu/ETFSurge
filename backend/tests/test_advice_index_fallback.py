"""R6-F6 (round6 §十 R6-07'): advice 指数注入兜底。

背景：get_index_realtime() 空（东财限流）→ R5-1-3 快照仅市态/情绪 →
AI 投顾输出全"无法确认指数"模板，不可采信。
修复：指数段空时从 get_global_indices() 的 A 股段兜底。
"""
from app.routers.analysis import _build_advice_market_snapshot


def test_advice_snapshot_falls_back_to_global_indices(monkeypatch):
    """get_index_realtime 空时，A 股指数从 market_service 同步缓存兜底注入。"""
    import app.services.market_service as ms

    monkeypatch.setattr(ms, "_global_indices_cache", {
        "A股": [
            {"symbol": "000001", "name": "上证指数", "price": 3809.66, "change_pct": -0.6},
            {"symbol": "399001", "name": "深证成指", "price": 13448.29, "change_pct": -1.0},
            {"symbol": "399006", "name": "创业板指", "price": 3302.55, "change_pct": -1.2},
        ],
        "港股": [{"symbol": "^HSI", "name": "恒生指数", "price": 26009.4, "change_pct": 0.5}],
    })

    class _Hub:
        def get_market_regime(self):
            return "range_bound"

        def get_market_sentiment(self):
            return {"sentiment_label": "中性", "sentiment_index": 49.7}

        def get_index_realtime(self):
            return []  # 东财限流 → 空

        def get_sector_momentum(self):
            return []

        def get_news_headlines(self):
            return []

    snapshot = _build_advice_market_snapshot("当前A股市场怎么配置", _Hub())
    assert "上证指数" in snapshot
    assert "3809.66" in snapshot
    assert "-0.60%" in snapshot
    # 港股不注入（A 股场景兜底只取 A 股段）
    assert "恒生指数" not in snapshot


def test_advice_snapshot_prefers_index_realtime(monkeypatch):
    """get_index_realtime 有数据时优先使用（不触发兜底）。"""
    class _Hub:
        def get_market_regime(self):
            return "range_bound"

        def get_market_sentiment(self):
            return {}

        def get_index_realtime(self):
            return [{"name": "上证指数", "price": 4000.0, "change_pct": 0.5}]

        def get_global_indices(self):
            return {"A股": [{"name": "旧指数", "price": 100.0, "change_pct": 0.0}]}

        def get_sector_momentum(self):
            return []

        def get_news_headlines(self):
            return []

    snapshot = _build_advice_market_snapshot("大盘怎么样", _Hub())
    assert "上证指数: 4000.0" in snapshot
    assert "旧指数" not in snapshot


def test_advice_snapshot_both_empty_no_crash(monkeypatch):
    """两源皆空时优雅降级（不抛异常，快照为空）。"""
    class _Hub:
        def get_market_regime(self):
            return None

        def get_market_sentiment(self):
            return {}

        def get_index_realtime(self):
            return []

        def get_global_indices(self):
            return {}

        def get_sector_momentum(self):
            return []

        def get_news_headlines(self):
            return []

    snapshot = _build_advice_market_snapshot("怎么配置", _Hub())
    assert isinstance(snapshot, str)
