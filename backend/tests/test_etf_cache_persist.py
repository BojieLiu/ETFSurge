"""R6-F7 (round6 §十 R6-08): etf_list_cache.json 文件缓存持久化。

round35 RC-C4 方案A（docs/round35-architecture-review.md §18.4）：落点统一为
DATA_DIR env → settings.data_dir（容器=R93 解析的挂载卷 /app/data），删除
「/app/data exists 探测」与「宿主回落 backend/data」两分支——后者正是
P1-11 少一级 ../ 的历史 bug 落点。宿主用例同步收紧为负向断言（backend/data
前缀必须失败），防弱断言再放行错位路径。
"""
import os
from pathlib import Path

from app.config import settings
from app.fetchers import etf_scanner as es


def test_cache_file_honors_data_dir(monkeypatch):
    """DATA_DIR 环境变量优先（显式配置场景）。"""
    monkeypatch.setenv("DATA_DIR", "C:/custom/data")
    assert es._etf_cache_file() == os.path.join("C:/custom/data", "etf_list_cache.json")


def test_cache_file_container_mount_volume(monkeypatch):
    """容器场景：settings.data_dir 解析为挂载卷 /app/data（R93）→ 写挂载卷，
    容器重建不丢；不再依赖 /app/data 的文件系统探测（冗余防御已删）。"""
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(settings, "data_dir", "/app/data")
    norm = os.path.normpath(es._etf_cache_file()).replace("\\", "/")
    assert norm == "/app/data/etf_list_cache.json"


def test_cache_file_host_never_under_source_tree(monkeypatch):
    """负向（RC-C4 验收口径）：宿主落点必须 == settings.data_dir，
    绝不允许回落源码树 backend/data（P1-11 少一级 ../ 的历史 bug 口径——
    旧断言 `"data" in path` 对 backend/data 与项目根 data 双双放行）。"""
    monkeypatch.delenv("DATA_DIR", raising=False)
    src_backend = str(Path(es.__file__).resolve().parent.parent.parent)  # .../backend
    path = os.path.normpath(es._etf_cache_file())
    assert not path.startswith(os.path.join(src_backend, "data")), f"仍落源码树: {path}"
    assert path == os.path.normpath(os.path.join(str(settings.data_dir), "etf_list_cache.json"))
