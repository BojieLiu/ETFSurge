"""
O1 (docs/round7-rediagnosis.md §7 P1): etf_list_cache 快照宽容——避免全量 1618 扫描。

P1 根因: 容器重建/挂载卷时间戳使 etf_list_cache.json 快照 ts 跨 4h 阈值
（CACHE_TTL 14400s）→ fetch_all_etfs_base 不命中文件缓存 → 全量 1618 只扫描
（预热 market_cache 64s + etf_cache 64s = 128s）。

修复: 文件快照（len>50）无论新旧先返回（启动快速可用），数据新鲜度由 60s
周期刷新循环保证（内存缓存 TTL 过期后自然重扫）——旧快照不再触发启动冷扫。
"""

import json
import time

from app.fetchers import etf_scanner as es


def _make_cache_file(tmp_path, ts_age_seconds):
    """构造旧快照文件（ts 距今 > 4h）。"""
    cache_file = tmp_path / "etf_list_cache.json"
    cache_file.write_text(json.dumps({
        "ts": time.time() - ts_age_seconds,
        "etfs": [{"symbol": f"{i:06d}", "name": f"ETF{i}"} for i in range(100)],
    }), encoding="utf-8")
    return cache_file


def test_stale_snapshot_used_without_full_scan(tmp_path, monkeypatch):
    """ts 超 4h 的旧快照 → 直接命中（不触发全量扫描）。"""
    cache_file = _make_cache_file(tmp_path, ts_age_seconds=14400 + 3600)
    monkeypatch.setattr(es, "_etf_cache_file", lambda: str(cache_file))
    es.sync_memory_cache._store = {}  # 清内存缓存
    es._last_good_etfs = None

    # 若走到数据源 provider，说明快照未命中（应 FAIL）
    def _boom(*args, **kwargs):
        raise AssertionError("不应触发全量扫描（旧快照应直接命中）")

    monkeypatch.setattr("app.services.source_registry.registry.route", _boom)

    result = es.fetch_all_etfs_base()
    assert len(result) == 100, "旧快照应直接返回 100 只 ETF"
    assert result[0]["symbol"] == "000000"


def test_fresh_snapshot_still_hit(tmp_path, monkeypatch):
    """新鲜快照（<4h）→ 命中（回归）。"""
    cache_file = _make_cache_file(tmp_path, ts_age_seconds=3600)
    monkeypatch.setattr(es, "_etf_cache_file", lambda: str(cache_file))
    es.sync_memory_cache._store = {}
    es._last_good_etfs = None

    def _boom(*args, **kwargs):
        raise AssertionError("新鲜快照不应触发扫描")

    monkeypatch.setattr("app.services.source_registry.registry.route", _boom)
    result = es.fetch_all_etfs_base()
    assert len(result) == 100


def test_empty_snapshot_still_scans(tmp_path, monkeypatch):
    """空/无效快照（len<=50）→ 仍走全量扫描（快照不可用不兜底）。"""
    cache_file = tmp_path / "etf_list_cache.json"
    cache_file.write_text(json.dumps({
        "ts": time.time(),
        "etfs": [{"symbol": "510300", "name": "沪深300ETF"}],  # 仅 1 只
    }), encoding="utf-8")
    monkeypatch.setattr(es, "_etf_cache_file", lambda: str(cache_file))
    es.sync_memory_cache._store = {}
    es._last_good_etfs = None

    scanned = {"called": False}

    def _fake_route(providers, route_name=None, operation=None, target=None):
        scanned["called"] = True
        return None

    monkeypatch.setattr("app.services.source_registry.registry.route", _fake_route)
    result = es.fetch_all_etfs_base()
    assert scanned["called"], "无效快照应触发扫描"
