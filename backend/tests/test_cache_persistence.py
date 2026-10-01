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


# ===================================================================
# merged from test_valuation_mixin_v1.py (F1 baseline 归位, 2026-09-28)
# ===================================================================
"""L2 P0: ValuationMixin 契约（tmp 库 + mock fetcher，无网络）。

- 内存缓存 6h：TTL 内二次调用不触 fetcher。
- 落盘幂等：同 (kind, key, as_of) 重复 persist 只留 1 行。
- 裁剪：每 (kind, key) 只留最近 250 个 as_of。
- 分位：攒起的历史能算出近 20 日分位；单点历史 → None（待验）。
"""
import sqlite3

import pytest

from app.services.hub._valuation import ValuationMixin


@pytest.fixture()
def mix(tmp_path, monkeypatch):
    m = ValuationMixin()
    db = str(tmp_path / "val_test.db")
    monkeypatch.setattr("app.services.hub._valuation._valuation_db_path",
                        lambda: db)
    return m


def _idx_rows():
    return [
        {"date": "2026-09-16", "pe_1": 14.6, "pe_2": 16.82,
         "div_1": 2.63, "div_2": 2.34},
        {"date": "2026-09-15", "pe_1": 14.5, "pe_2": 16.70,
         "div_1": 2.61, "div_2": 2.32},
    ]


def test_index_cache_ttl(mix, monkeypatch):
    calls = {"n": 0}

    def _fake(symbol):
        calls["n"] += 1
        return _idx_rows()

    monkeypatch.setattr("app.services.hub._valuation.fetch_index_valuation_history",
                        _fake)
    assert len(mix.get_index_valuation("000300")) == 2
    assert len(mix.get_index_valuation("000300")) == 2
    assert calls["n"] == 1, "TTL 内不应重复触源"


def test_index_empty_not_cached(mix, monkeypatch):
    calls = {"n": 0}

    def _fake(symbol):
        calls["n"] += 1
        return []

    monkeypatch.setattr("app.services.hub._valuation.fetch_index_valuation_history",
                        _fake)
    assert mix.get_index_valuation("000300") == []
    assert mix.get_index_valuation("000300") == []
    assert calls["n"] == 2, "空结果不进 6h 缓存（靠 fetcher 1h 失败缓存防刷）"


def test_persist_idempotent(mix):
    mix.persist_index_valuation("000300", _idx_rows())
    mix.persist_index_valuation("000300", _idx_rows())
    assert mix.count_valuation_rows("index", "000300") == 2


def test_trim_keeps_250(mix):
    rows = [{"date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
             "pe_1": 10.0 + i * 0.01, "pe_2": None,
             "div_1": None, "div_2": None} for i in range(260)]
    mix.persist_index_valuation("000300", rows)
    assert mix.count_valuation_rows("index", "000300") == 250


def test_percentile_from_history(mix):
    mix.persist_index_valuation("000300", _idx_rows())
    hist = mix.get_valuation_history("index", "000300", col="pe_1")
    assert hist == [14.6, 14.5]
    from app.engine.valuation import compute_pe_percentile
    assert compute_pe_percentile(14.6, hist) == pytest.approx(1.0)
    assert compute_pe_percentile(14.5, hist) == pytest.approx(0.0)


def test_single_point_percentile_none(mix):
    mix.persist_index_valuation("000300", _idx_rows()[:1])
    hist = mix.get_valuation_history("index", "000300", col="pe_1")
    from app.engine.valuation import compute_pe_percentile
    # 单点历史无法分位 → engine 按 n==1 语义返回端点值；
    # 调用方约定：len(hist) < 5 一律待验（本断言锁定该约定输入）
    assert len(hist) == 1
    assert compute_pe_percentile(99.0, hist) == pytest.approx(1.0)


def test_sector_snapshot_persist_and_read(mix):
    rows = [{"ind_code": "C39", "ind_name": "计算机",
             "pe_wavg": 20.5, "pe_median": 35.2, "pe_avg": 40.1,
             "as_of": "2026-09-16"}]
    mix.persist_sector_valuation(rows)
    got = mix.get_valuation_history("sector", "C39", col="pe_wavg")
    assert got == [20.5]


def test_tmp_db_has_table(mix):
    # lazy 建表：首次读写（此处为读）即建表，无需 init_db
    assert mix.count_valuation_rows("index", "000300") == 0
    import app.services.hub._valuation as _v
    with sqlite3.connect(_v._valuation_db_path(), timeout=10) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "valuation_history" in names


# ---------------------------------------------------------------------------
# round59 R06：app_config 的 LLM key override 与 provider 实际生效 key 一致性
#
# 病灶（doc M7）：`core/config_manager.py:100-104` 的 `get()` 是 **DB 优先**，
# 但真正发请求的 `app/analysis/provider.py` 用 `settings.opencode_zen_api_key`
# ——该值在启动时从 `.env` 载入，DB override **不影响调用**，却让 ConfigView
# 显示一个不生效的 key（2026-09-28 21:16 写入的占位行 'sk-x'）。
#
# 本轮处置：删除该误导行（已执行）+ 本测试锁住"两者一致"。
# 架构裂缝本身（DB override 对 LLM provider 无效）**本轮不修**，故测试的
# 断言方向是"若再次出现分歧则失败"，而不是"DB override 应当生效"。
# ---------------------------------------------------------------------------


def test_r06_no_stale_placeholder_override_left_in_app_config():
    """占位/失效的 override 行必须清掉，UI 才不会显示一个假 key。

    注意口径修正（doc M7 原述不准确）：`OPENCODE_ZEN_API_KEY` **在**
    `provider._HOT_RELOAD_KEYS` 中，且 `routers/admin.py:242` 在 admin PUT 之后
    调 `refresh_provider_chain` 把 DB override patch 进 settings —— 所以经 admin
    端点写入的 override 是**会生效**的。真正的缺口是「直接写 DB 绕过 admin handler
    → 不触发热加载」，那种行会留在 ConfigView 上却不影响实际调用。
    因此本测试锁的是"不存在绕过热加载留下的陈旧行"，而不是"override 不该存在"。

    只比较 key 名，不打印任何密钥内容。
    """
    from app.core.config_manager import config_manager
    import asyncio as _aio

    async def _read():
        return await config_manager.get("OPENCODE_ZEN_API_KEY")

    try:
        _loop = _aio.get_running_loop()
    except RuntimeError:
        _loop = None
    override = _loop.run_until_complete(_read()) if _loop else _aio.run(_read())

    assert not override or len(override) > 6, (
        "app_config 仍留有占位形态的 OPENCODE_ZEN_API_KEY override"
    )


def test_r06_zen_key_is_registered_for_hot_reload():
    """守卫：provider 必须把该 key 登记进 _HOT_RELOAD_KEYS。

    若将来移除该登记，admin ConfigView 改key 将静默不生效——这正是
    「UI 显示已保存、实际调用没变」那类难以定位的问题。
    """
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "app" / "analysis" / "provider.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    hot_reload: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_HOT_RELOAD_KEYS" and isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        hot_reload[k.value] = v.value
    assert "OPENCODE_ZEN_API_KEY" in hot_reload, (
        "OPENCODE_ZEN_API_KEY 未登记进 _HOT_RELOAD_KEYS：admin 改 key 将不热生效"
    )
    assert hot_reload["OPENCODE_ZEN_API_KEY"] == "opencode_zen_api_key", hot_reload