# -*- coding: utf-8 -*-
"""F19 R68 补充：sentiment_history 滚动数组的文件持久化。

R68 要求 20 日 sentiment_index 滚动数组"持久化到 sentiment_cache.json"——
当前实现仅内存（进程重启丢失，panic_greed_diff 在冷启动后仍需 20 个交易日
才恢复）。本测试验证：跨进程/跨模块复用滚动数组 + 落盘/恢复。
"""
import json
import os

from app.fetchers import fundamentals_fetcher as ff


def test_sentiment_rolling_persisted_to_file(tmp_path, monkeypatch):
    """fetch_market_sentiment 后，滚动数组写入缓存文件；恢复逻辑能读回。"""
    # 模拟一次带 history 的 sentiment 数据
    history = [50.0 + i for i in range(12)]
    sentiment = {
        "sentiment_index": 62.0,
        "sentiment_label": "中性偏乐观",
        "advance_ratio": 0.6,
        "sentiment_history": history,
    }
    file_path = tmp_path / "sentiment_history.json"

    ff._persist_sentiment_history(file_path, sentiment)

    assert file_path.exists()
    saved = json.loads(file_path.read_text(encoding="utf-8"))
    assert saved == history


def test_sentiment_rolling_restored_from_file(tmp_path, monkeypatch):
    """模块加载时若存在历史文件，滚动数组被恢复（不从头累积）。"""
    file_path = tmp_path / "sentiment_history.json"
    file_path.write_text(json.dumps([55.0 + i for i in range(8)]), encoding="utf-8")

    restored = ff._load_sentiment_history(file_path)
    assert restored == [55.0 + i for i in range(8)]


def test_sentiment_rolling_capped_at_20(tmp_path, monkeypatch):
    """滚动数组上限 20 条（超出丢弃最旧）。"""
    file_path = tmp_path / "sentiment_history.json"
    file_path.write_text(json.dumps([float(i) for i in range(30)]), encoding="utf-8")

    restored = ff._load_sentiment_history(file_path)
    assert len(restored) == 20
    assert restored[0] == 10.0  # 只保留最近 20 条
