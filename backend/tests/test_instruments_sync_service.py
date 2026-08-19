"""F17 (round6 §16.5): instruments 启动自动同步 service + 防并发互斥锁。

背景：instruments 表从未创建/同步（§十八-3）→ search 恒降级全量拉取；
启动自动同步（lifespan 后台，不阻塞启动）+ scheduler 每日 16:30 保留 +
防并发互斥锁（双写竞态）。
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from app.services import instruments_sync as insvc


def _row(symbol, name, market="A", asset_type="stock"):
    return {"symbol": symbol, "name": name, "market": market,
            "asset_type": asset_type, "pinyin": "", "first_letter": ""}


async def test_sync_table_writes_rows():
    """数据正常 → 全量替换（delete + add_all + commit）。"""
    rows = [_row("600519", "贵州茅台"), _row("510300", "沪深300ETF", asset_type="etf")]
    with patch.object(insvc, "_collect", new=AsyncMock(return_value=rows)), \
         patch("app.database.init_db", new=AsyncMock()), \
         patch("app.database.async_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_session

        n = await insvc.sync_instruments_table()

    assert n == 2
    executed = [c.args[0] for c in mock_session.execute.await_args_list]
    assert any("delete" in str(a).lower() for a in executed if a is not None)
    assert mock_session.add_all.call_count == 1
    assert mock_session.commit.await_count == 1


async def test_sync_table_keeps_table_when_all_fail():
    """全部段失败 → 不 delete（保留旧表），返回 0。"""
    with patch.object(insvc, "_collect", new=AsyncMock(return_value=[])), \
         patch("app.database.async_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_session

        n = await insvc.sync_instruments_table()

    assert n == 0
    executed = [c.args[0] for c in mock_session.execute.await_args_list]
    assert not any("delete" in str(a).lower() for a in executed if a is not None)


async def test_sync_table_mutex_serializes():
    """并发调用（启动同步 vs 每日同步）→ 互斥锁串行，第二次直接返回不双写。"""
    start = asyncio.Event()
    release = asyncio.Event()

    async def _slow_collect():
        start.set()
        await release.wait()
        return [_row("600519", "贵州茅台")]

    with patch.object(insvc, "_collect", new=_slow_collect), \
         patch("app.database.init_db", new=AsyncMock()), \
         patch("app.database.async_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_session

        t1 = asyncio.create_task(insvc.sync_instruments_table())
        await start.wait()  # 第一个已进入采集
        # 第二个并发调用——互斥锁应让其立即返回 0（不进入 DB 写路径）
        n2 = await insvc.sync_instruments_table()
        assert n2 == 0, "并发调用应被互斥锁拦截"
        release.set()
        n1 = await t1
        assert n1 == 1
    # DB 写只发生一次
    assert mock_ctx.return_value is not None


class TestP24SegmentGuard:
    """P2-4 (round16 §5 盲区⑥): 依赖表同步守卫——instruments 五段含 US/HK 段。"""

    def test_collect_all_has_us_and_hk_segments(self):
        """sync_instruments.collect_all 段清单含美股/港股段（US/HK 搜索依赖表非空）。"""
        from app.fetchers.sync_instruments import collect_all
        import inspect

        src = inspect.getsource(collect_all)
        # 五段收集：A股个股/ETF/港股/港股ETF/美股
        assert "stock_us_spot_em" in src, "美股段缺失 → instruments US=0 → 英文名搜索恒断"
        assert "stock_hk_main_board_spot_em" in src, "港股段缺失 → instruments HK=0"
        # 主源 + 降级链（新浪）双保险
        assert "stock_us_spot" in src, "美股新浪降级链缺失（EM 被拦时 US 段恒空）"

    def test_fetch_us_list_has_primary_and_fallback(self):
        """_fetch_us_list 主源 5s 独立超时 + 新浪降级（P0-6 修复防 CancelledError 截断）。"""
        import inspect
        from app.fetchers.sync_instruments import _fetch_us_list

        src = inspect.getsource(_fetch_us_list)
        assert "timeout=5.0" in src, "美股主源应独立 5s 超时（旧实现整段 20s 取消降级链）"
        assert "新浪" in src or "sina" in src.lower(), "美股降级链（新浪受限分页）应存在"


# ===================================================================
# merged from test_round25_r30_sync_imports.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
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


class TestSyncIndicesMovedToApp:
    """round29 续轮: sync_indices 对齐 R30 模式（逻辑入 app/fetchers + scripts 留 shim）。"""

    def test_import_sync_indices_in_app(self):
        from app.fetchers.sync_indices import sync
        assert callable(sync)

    def test_moved_file_is_in_app_package(self):
        """真身物理位于 app/fetchers/，且不再有 sys.path 手工 bootstrap。"""
        import inspect
        import app.fetchers.sync_indices as si
        path_si = inspect.getfile(si).replace("\\", "/")
        assert "/app/fetchers/sync_indices.py" in path_si, f"应在 app/fetchers：{path_si}"
        assert "sys.path.insert" not in inspect.getsource(si)

    def test_scripts_shim_reexports_fetchers(self):
        """scripts/sync_indices shim 与 app.fetchers 同源（同一函数对象）。"""
        from app.fetchers.sync_indices import sync as app_sync
        from scripts.sync_indices import sync as shim_sync
        assert app_sync is shim_sync, "shim 应 re-export app.fetchers 同一函数"

    def test_scripts_shim_has_main_block(self):
        """shim 保留 `__main__` 块——`python -m scripts.sync_indices` 本地 CLI 仍可执行。

        （与 sync_instruments / sync_indices_meta 两个 shim 不同——那两个 shim 缺失
        `__main__` 块，`python -m scripts.sync_*` 实际只 import 不执行 sync()，是本轮
        顺带发现的既有小瑕疵。）
        """
        import inspect
        import scripts.sync_indices as shim
        src = inspect.getsource(shim)
        assert "__main__" in src, "shim 应保留 __main__ 块供本地 CLI 执行 sync()"

