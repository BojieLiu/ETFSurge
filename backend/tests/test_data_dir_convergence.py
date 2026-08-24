# -*- coding: utf-8 -*-
"""round35 §18.4 RC-C 数据落点收敛（C1/C4/C5/C6）—— 落点必须 == settings.data_dir。

背景：四处活代码手拼相对路径 data（dirname×2/×3），同一项目三份数据目录并存：
- 项目根 data/（正牌：config._DATA_DIR、docker 挂载卷 ./data）
- backend/app/data/（C1 sentiment_history、C6 indices_cache 写入包内，
  容器内落在镜像层重建必丢）
- backend/data/（C4 etf_list_cache + etf_index_mapping、C5 sentiment_cache 写入，
  容器内碰巧正确、宿主机错位）

本测试钉死「monkeypatch settings.data_dir 后各落点精确跟随」，对旧实现必红。
验收总闸（§18.7）：任何落点不得解析到 backend/data 或 backend/app/data。
"""
import os
from pathlib import Path

import pytest

from app.config import settings


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return tmp_path


# ── C1: fundamentals_fetcher sentiment_history ──────────────────────────


def test_c1_sentiment_history_follows_data_dir(data_dir):
    from app.fetchers import fundamentals_fetcher as ff

    assert ff._sentiment_history_path() == os.path.join(str(data_dir), "sentiment_history.json")


def test_c1_not_inside_package_tree():
    """负向：落点不得位于源码包内（旧实现 dirname×2 → backend/app/data）。"""
    from app.fetchers import fundamentals_fetcher as ff

    pkg_app_root = str(Path(ff.__file__).resolve().parent.parent)  # .../backend/app
    assert not ff._sentiment_history_path().startswith(pkg_app_root)


# ── C5: hub/_regime_sentiment sentiment_cache（写/读双拷贝共用单点）──────


def test_c5_sentiment_cache_follows_data_dir(data_dir):
    from app.services.hub import _regime_sentiment as rs

    assert rs._sentiment_cache_file() == os.path.join(str(data_dir), "sentiment_cache.json")


# ── C4: etf_scanner etf_list_cache + tracked_index_mapping ──────────────


def test_c4_etf_list_cache_follows_data_dir(data_dir, monkeypatch):
    from app.fetchers import etf_scanner as es

    monkeypatch.delenv("DATA_DIR", raising=False)
    assert es._etf_cache_file() == os.path.join(str(data_dir), "etf_list_cache.json")


def test_c4_tracked_index_mapping_follows_data_dir(data_dir):
    from app.fetchers import etf_scanner as es

    assert es._tracked_index_cache_path() == os.path.join(str(data_dir), "etf_index_mapping.json")


# ── C6: market_service indices_cache ────────────────────────────────────


def test_c6_indices_cache_follows_data_dir(data_dir, monkeypatch):
    from app.services import market_service as ms

    monkeypatch.setattr(ms, "_CACHE_DB_PATH", None)  # 重置导入期缓存的全局单例
    assert ms._get_cache_db_path() == os.path.join(str(data_dir), "indices_cache.json")


# ── 总闸负向：历史漂移目录一律禁止 ───────────────────────────────────────


def test_no_location_resolves_into_legacy_drift_dirs(data_dir, monkeypatch):
    """RC-R3 双模式总闸的测试化：四个落点均不得落在 backend/{data,app/data}。"""
    from app.fetchers import etf_scanner as es
    from app.services.hub import _regime_sentiment as rs

    monkeypatch.delenv("DATA_DIR", raising=False)
    backend_root = str(Path(es.__file__).resolve().parent.parent.parent)  # .../backend
    forbidden = {
        os.path.normpath(os.path.join(backend_root, "data")),
        os.path.normpath(os.path.join(backend_root, "app", "data")),
    }
    locations = (
        es._etf_cache_file(),
        es._tracked_index_cache_path(),
        rs._sentiment_cache_file(),
    )
    for p in locations:
        norm = os.path.normpath(p)
        for bad in forbidden:
            assert not norm.startswith(bad), f"{norm} 仍落在历史漂移目录 {bad}"
