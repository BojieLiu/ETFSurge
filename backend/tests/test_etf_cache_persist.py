"""R6-F7 (round6 §十 R6-08): etf_list_cache.json 文件缓存持久化。

背景：缓存写在镜像层 `app/app/data`（容器重建必丢）→ 预热全量扫描 1617 只
（~6.4s）。修复：容器内写到挂载卷 /app/data（与 portfolio.db 同卷），
宿主机回落 backend/data。
"""
import os

from app.fetchers import etf_scanner as es


def test_cache_file_honors_data_dir(monkeypatch):
    """DATA_DIR 环境变量优先（显式配置场景）。"""
    monkeypatch.setenv("DATA_DIR", "C:/custom/data")
    assert es._etf_cache_file() == os.path.join("C:/custom/data", "etf_list_cache.json")


def test_cache_file_container_path_when_app_data_exists(monkeypatch):
    """容器内 /app/data 挂载卷存在 → 写到 /app/data（容器重建不丢）。"""
    monkeypatch.delenv("DATA_DIR", raising=False)
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/app/data" or real_exists(p))
    path = es._etf_cache_file()
    # Windows 下 join 产生反斜杠——规范化比较
    norm = os.path.normpath(path).replace("\\", "/")
    assert norm == "/app/data/etf_list_cache.json"


def test_cache_file_host_fallback(monkeypatch):
    """宿主机（无 /app/data）→ 回落 backend/data（现状路径）。"""
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    path = es._etf_cache_file()
    assert "etf_list_cache.json" in path
    assert "data" in path
    assert not path.startswith("/app")
