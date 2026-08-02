# -*- coding: utf-8 -*-
"""F20-S2 管道级测试：mock 数据源层 → 断言 fetch_market_sentiment 注入段产出字段。

F19 根因 1：test_sentiment_factors 直接传 sentiment_history 给因子函数，从不验证
fetch_market_sentiment 是否产出该字段（结构性 bug 被完美绕过）。本测试 mock akshare
数据源函数，走 fetch_market_sentiment 真实路径，断言返回结构含 sentiment_history /
sentiment_index / advance_ratio。
"""
import pytest

from app.fetchers import fundamentals_fetcher as ff


@pytest.fixture
def clean_rolling(monkeypatch):
    """冷启动：滚动数组置空 + 文件读写 no-op（不污染真实数据文件）。"""
    monkeypatch.setattr(ff, "_sentiment_rolling", [])
    monkeypatch.setattr(ff, "_load_sentiment_history", lambda *a, **k: [])
    monkeypatch.setattr(ff, "_persist_sentiment_history", lambda *a, **k: None)
    yield


@pytest.fixture
def mock_sources(monkeypatch):
    """mock 数据源层：三个底层指标函数返回固定值。"""
    monkeypatch.setattr(ff, "fetch_advance_decline_ratio", lambda *a, **k: 0.6)
    monkeypatch.setattr(ff, "_fetch_volume_ratio", lambda *a, **k: 1.2)
    monkeypatch.setattr(ff, "fetch_margin_change", lambda *a, **k: 0.05)


async def test_pipeline_injects_sentiment_history(mock_sources, clean_rolling):
    """全链路：数据源 → fetch_market_sentiment 返回结构含 sentiment_history（F19 根因 1 拦截）。"""
    result = await ff.fetch_market_sentiment()
    assert "sentiment_history" in result, "注入段必须产出 sentiment_history"
    assert len(result["sentiment_history"]) >= 1
    assert isinstance(result["sentiment_index"], (int, float))
    # advance_ratio 来自数据源层（0.6），四舍五入保留 4 位
    assert result["advance_ratio"] == 0.6


async def test_pipeline_rolling_accumulates_across_calls(mock_sources, clean_rolling):
    """连续调用 3 次 → 滚动数组累积 3 个样本（冷启动逐步累积）。"""
    await ff.fetch_market_sentiment()
    await ff.fetch_market_sentiment()
    result = await ff.fetch_market_sentiment()
    assert len(result["sentiment_history"]) == 3
    # 三个样本相同（数据源固定）但索引来自真实计算
    assert all(isinstance(x, float) for x in result["sentiment_history"])


async def test_pipeline_rolling_capped_at_20(mock_sources, clean_rolling):
    """滚动数组上限 20：连调 25 次仍只保留最近 20 个。"""
    for _ in range(25):
        await ff.fetch_market_sentiment()
    result = await ff.fetch_market_sentiment()
    assert len(result["sentiment_history"]) == 20


async def test_pipeline_source_failure_degrades(mock_sources, clean_rolling, monkeypatch):
    """数据源失败 → 降级默认值（advance→0.5），不崩溃且仍产出 sentiment_history。"""
    def _boom(*a, **k):
        raise RuntimeError("akshare 超时")

    monkeypatch.setattr(ff, "fetch_advance_decline_ratio", _boom)
    result = await ff.fetch_market_sentiment()
    assert result["advance_ratio"] == 0.5  # 降级默认
    assert "sentiment_history" in result  # 降级也不丢注入字段
