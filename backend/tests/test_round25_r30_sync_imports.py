"""round25 R30: scripts 生产同步代码移入 app/fetchers——容器内启动同步不再断裂。

问题（round25 §2 实证）：`backend/.dockerignore` 排除 `scripts/` → 容器内 `/app/scripts/`
不存在 → `app/services/instruments_sync.py:29` `from scripts.sync_instruments import
collect_all` 抛 `No module named 'scripts'` → 启动同步静默失败（恒生港股通系列从未进表）。

修复（round25 R30）：生产同步代码 `sync_instruments.py` / `sync_indices_meta.py` 移入
`app/fetchers/`，services 层改 `from ..fetchers.sync_* import ...`；`scripts/` 保留薄
shim（仅本地手动 CLI）。

验收：
- `import app.fetchers.sync_instruments` / `sync_indices_meta` 成功；
- `app.services.instruments_sync` / `indices_meta_sync` 不再 import `scripts.*`（容器内可跑）；
- `scripts.sync_*` shim 仍可 import（本地 CLI 兼容）。
"""

import inspect


class TestSyncModulesMovedToApp:
    """R30: 生产同步代码在 app 包内可 import。"""

    def test_import_sync_instruments_in_app(self):
        from app.fetchers.sync_instruments import collect_all, _fetch_us_list, _to_pinyin
        assert callable(collect_all)
        assert callable(_fetch_us_list)
        assert callable(_to_pinyin)

    def test_import_sync_indices_meta_in_app(self):
        from app.fetchers.sync_indices_meta import collect_all, _STATIC_EXTRA_INDICES
        assert callable(collect_all)
        assert isinstance(_STATIC_EXTRA_INDICES, list)
        assert len(_STATIC_EXTRA_INDICES) > 0

    def test_services_no_longer_import_scripts(self):
        """services 层源码不再含 `from scripts.` import 语句（容器内可正常 import）。"""
        import app.services.instruments_sync as ins
        import app.services.indices_meta_sync as ims

        src_ins = inspect.getsource(ins)
        src_ims = inspect.getsource(ims)
        # 只匹配 import 语句（注释/文档字符串里的历史说明不计）
        import re
        assert not re.search(r"^\s*from scripts\.", src_ins, re.M), \
            "instruments_sync 不得再 import scripts.*（R30）"
        assert not re.search(r"^\s*from scripts\.", src_ims, re.M), \
            "indices_meta_sync 不得再 import scripts.*（R30）"
        # 确认改指向 app.fetchers
        assert "app.fetchers.sync_instruments" in src_ins or "..fetchers.sync_instruments" in src_ins
        assert "app.fetchers.sync_indices_meta" in src_ims or "..fetchers.sync_indices_meta" in src_ims

    def test_moved_file_is_in_app_package(self):
        """移入的文件物理位于 app/fetchers/（非 scripts/ 遗留）。"""
        import app.fetchers.sync_instruments as si
        import app.fetchers.sync_indices_meta as sim
        path_si = inspect.getfile(si).replace("\\", "/")
        path_sim = inspect.getfile(sim).replace("\\", "/")
        assert "/app/fetchers/sync_instruments.py" in path_si, f"应在 app/fetchers：{path_si}"
        assert "/app/fetchers/sync_indices_meta.py" in path_sim, f"应在 app/fetchers：{path_sim}"
        # 不再有 sys.path 手工 bootstrap（app 包内不需要）
        assert "sys.path.insert" not in inspect.getsource(si)
        assert "sys.path.insert" not in inspect.getsource(sim)


class TestScriptsShimBackCompat:
    """R30: scripts/ 薄 shim 保留本地 CLI 兼容。"""

    def test_scripts_shim_importable(self):
        from scripts.sync_instruments import collect_all as si_collect
        from scripts.sync_indices_meta import collect_all as sim_collect
        assert callable(si_collect)
        assert callable(sim_collect)

    def test_shim_reexports_fetchers(self):
        """shim 与 app.fetchers 同源（同一函数对象，非复制）。"""
        from app.fetchers.sync_instruments import collect_all as app_collect
        from scripts.sync_instruments import collect_all as shim_collect
        assert app_collect is shim_collect, "shim 应 re-export app.fetchers 同一函数"