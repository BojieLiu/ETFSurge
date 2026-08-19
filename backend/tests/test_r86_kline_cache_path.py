# -*- coding: utf-8 -*-
"""round30 R86: kline_cache.json 落盘路径修正（写到挂载卷 data_dir，非源码目录）。

根因（§14.4）：`_kline_cache_path()` 用 `getattr(settings, "data_dir", None)` 但
Settings 无 data_dir 属性 → 落到 fallback `os.path.dirname(__file__)×3 + "data"` =
/app/app/data（源码目录）→ `docker compose down/up` 即丢。

修复：
  ① config.py 增 data_dir 属性（从 database_url 解析或显式 DATA_DIR env）；
  ② _kline_cache_path 优先读 settings.data_dir。

无网络：纯路径断言。
"""
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
