"""缓存落盘路径/持久化（聚合文件）——P1-4 小测试合并（round53 实施批，docs/redundant-review.md §4.2 T2）。

原文件 docstring 见下方来源注释；用例名/类名全部不变。
"""
from app.config import settings
from app.fetchers import etf_scanner as es
from pathlib import Path
import app.services.hub._kline as _kline_mod
import os


# 来源: tests/test_kline_cache_path.py（R86 (round30)）—— P1-4 小测试合并（用例名不变）
# 根因（§14.4）：`_kline_cache_path()` 用 `getattr(settings, "data_dir", None)` 但
# Settings 无 data_dir 属性 → 落到 fallback `os.path.dirname(__file__)×3 + "data"` =
# /app/app/data（源码目录）→ `docker compose down/up` 即丢。
# 
# 修复：
#   ① config.py 增 data_dir 属性（从 database_url 解析或显式 DATA_DIR env）；
#   ② _kline_cache_path 优先读 settings.data_dir。
# 
# 无网络：纯路径断言。


# 来源: tests/test_etf_cache_persist.py（R6-F7/RC-C4）—— P1-4 小测试合并（用例名不变）
# round35 RC-C4 方案A（docs/round35-architecture-review.md §18.4）：落点统一为
# DATA_DIR env → settings.data_dir（容器=R93 解析的挂载卷 /app/data），删除
# 「/app/data exists 探测」与「宿主回落 backend/data」两分支——后者正是
# P1-11 少一级 ../ 的历史 bug 落点。宿主用例同步收紧为负向断言（backend/data
# 前缀必须失败），防弱断言再放行错位路径。


import os


def test_settings_has_data_dir():
    """R86 ①：Settings 必须暴露 data_dir 属性（可解析出绝对路径）。"""
    from app.config import settings
    d = settings.data_dir
    assert d and os.path.isabs(str(d)), f"data_dir 应为绝对路径: {d}"


def test_kline_cache_path_uses_settings_data_dir(monkeypatch):
    """R86 ②：kline_cache_path 返回 settings.data_dir 下的 kline_cache.json。"""
    import app.services.hub._kline as _kline_mod
    from app.config import settings

    # 重置已缓存的路径（防止测试间污染）
    _kline_mod.KlineMixin._KLINE_CACHE_PERSIST_PATH = None

    # 模拟容器挂载卷 /app/data
    monkeypatch.setattr(settings, "data_dir", "/app/data")
    path = _kline_mod.KlineMixin()._kline_cache_path()
    assert path == os.path.join("/app/data", "kline_cache.json"), f"落盘路径错误: {path}"
    # 负向：不得再落到源码目录 data（dirname×3 的 fallback）
    assert "/app/app/" not in path.replace("\\", "/")


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
