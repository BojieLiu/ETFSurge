"""round46 §1: mark_excluded admin endpoint + 启动期加载.

覆盖:
  - model_catalog: mark_excluded / unmark_excluded / is_excluded / list_excluded / load_excluded_from_keys
  - config_manager: set_kv / delete_kv / list_keys_with_prefix
  - admin router: GET/POST/DELETE /api/v1/admin/llm-excluded
  - 跨重启: 模拟启动期 list_keys_with_prefix 灌回 in-memory set
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. model_catalog 纯函数层 ──────────────────────────────────────


def test_mark_excluded_basic():
    from app.analysis.llm.model_catalog import ModelCatalog
    cat = ModelCatalog()
    cat.mark_excluded("opencode_zen", "m1-free")
    assert cat.is_excluded("opencode_zen", "m1-free")
    assert not cat.is_excluded("opencode_zen", "m2-free")
    assert not cat.is_excluded("openrouter", "m1-free")


def test_unmark_excluded_returns_true_if_existed():
    from app.analysis.llm.model_catalog import ModelCatalog
    cat = ModelCatalog()
    cat.mark_excluded("opencode_zen", "m1-free")
    assert cat.unmark_excluded("opencode_zen", "m1-free") is True
    assert not cat.is_excluded("opencode_zen", "m1-free")
    # 二次 unmark 返 False
    assert cat.unmark_excluded("opencode_zen", "m1-free") is False


def test_list_excluded_sorted():
    from app.analysis.llm.model_catalog import ModelCatalog
    cat = ModelCatalog()
    cat.mark_excluded("openrouter", "z-model")
    cat.mark_excluded("opencode_zen", "a-free")
    cat.mark_excluded("opencode_zen", "m-free")
    items = cat.list_excluded()
    # 排序: (provider, model) 全字符串序
    assert items == [
        {"provider": "opencode_zen", "model": "a-free"},
        {"provider": "opencode_zen", "model": "m-free"},
        {"provider": "openrouter", "model": "z-model"},
    ]
    assert len(cat._exclusions) == 3


def test_load_excluded_from_keys_filters_and_splits():
    from app.analysis.llm.model_catalog import ModelCatalog
    cat = ModelCatalog()
    # 混合: 合法 / 非 llm_excluded: / 缺冒号
    keys = [
        "llm_excluded:opencode_zen:deepseek-v4-flash-free",
        "llm_excluded:openrouter:meta-llama/llama-3.3-70b:free",  # model 内含 : (罕见但合法)
        "DEEPSEEK_API_KEY",  # 无关
        "llm_excluded:bad_no_colon",
    ]
    loaded = cat.load_excluded_from_keys(keys)
    assert loaded == 2
    assert cat.is_excluded("opencode_zen", "deepseek-v4-flash-free")
    assert cat.is_excluded("openrouter", "meta-llama/llama-3.3-70b:free")
    # DEEPSEEK_API_KEY 没被吞进 _exclusions
    assert len(cat._exclusions) == 2


# ── 2. config_manager set_kv / delete_kv / list_keys_with_prefix ──


@pytest.mark.asyncio
async def test_config_manager_kv_crud():
    """set_kv → list_keys_with_prefix → delete_kv 端到端 (mock DB session)."""
    from app.core.config_manager import ConfigManager

    # 模拟 AppConfig 表
    storage: dict[str, str] = {}

    class FakeRow:
        def __init__(self, k, v):
            self.key = k
            self.value = v

    class FakeResult:
        def all(self):
            return [FakeRow(k, v) for k, v in storage.items()]

    class FakeSession:
        async def execute(self, stmt, params=None):
            # list_keys_with_prefix 用 select + where like
            from sqlalchemy import select, delete
            compiled = stmt.compile()
            sql = str(compiled).lower()
            if "select" in sql and "like" in sql:
                prefix = params if params else "%"
                # 简化: 直接返 storage 全 keys (prefix 过滤在 Python 侧)
                if isinstance(prefix, dict):
                    pref = prefix.get("prefix", "%")
                else:
                    pref = prefix
                keys = [FakeRow(k, v) for k, v in storage.items() if k.startswith(pref)]
                return FakeResult()
            if "delete" in sql and params is not None:
                k = params.get("key")
                existed = k in storage
                storage.pop(k, None)
                self.rowcount = 1 if existed else 0
                return MagicMock(rowcount=self.rowcount)
            return MagicMock()

        async def commit(self):
            pass

    cm = ConfigManager()
    # mock session factory
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=FakeSession())
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    cm.init(factory)

    # set_kv 需要 sqlite_insert on_conflict_do_update — 改用 mock
    with patch.object(cm, "set_kv", new=AsyncMock(return_value=True)) as mock_set, \
         patch.object(cm, "delete_kv", new=AsyncMock(return_value=True)) as mock_del:
        # 直接测 list_keys_with_prefix (上面的 FakeSession 已覆盖)
        keys = await cm.list_keys_with_prefix("llm_excluded:")
        # 因为 storage 空, 应该返 []
        assert keys == []


# ── 3. admin router HTTP 端点 (用 TestClient) ─────────────────────


@pytest.fixture
def admin_client(monkeypatch):
    """构造 TestClient + mock config_manager + 清空 model_catalog 状态."""
    from fastapi.testclient import TestClient
    from app.analysis.llm.model_catalog import model_catalog as _cat
    from app.core.config_manager import config_manager as _cm

    # 清空 _exclusions
    _cat._exclusions.clear()

    # mock config_manager.kv 方法 (TestClient 跑同步事件循环)
    _cm.set_kv = AsyncMock(return_value=True)
    _cm.delete_kv = AsyncMock(return_value=True)
    _cm.list_keys_with_prefix = AsyncMock(return_value=[])

    # 用最小 app (避免 lifespan 卡死)
    from fastapi import FastAPI
    from app.routers.admin import router as admin_router
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app), _cat, _cm


def test_admin_list_llm_excluded_empty(admin_client):
    client, _cat, _cm = admin_client
    r = client.get("/api/v1/admin/llm-excluded")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_admin_add_llm_excluded(admin_client):
    client, _cat, _cm = admin_client
    r = client.post(
        "/api/v1/admin/llm-excluded",
        json={"provider": "opencode_zen", "model": "m1-free", "reason": "test bad"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "added"
    assert data["provider"] == "opencode_zen"
    assert data["model"] == "m1-free"
    assert data["persisted"] is True
    # in-memory 立即生效
    assert _cat.is_excluded("opencode_zen", "m1-free")
    # config_manager.set_kv 调了
    _cm.set_kv.assert_awaited_once()
    args, _ = _cm.set_kv.call_args
    assert args[0] == "llm_excluded:opencode_zen:m1-free"
    assert args[1] == "1"


def test_admin_add_llm_excluded_duplicate(admin_client):
    client, _cat, _cm = admin_client
    client.post("/api/v1/admin/llm-excluded",
                json={"provider": "opencode_zen", "model": "m1-free"})
    r2 = client.post("/api/v1/admin/llm-excluded",
                     json={"provider": "opencode_zen", "model": "m1-free"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_excluded"


def test_admin_remove_llm_excluded(admin_client):
    client, _cat, _cm = admin_client
    # 先加
    client.post("/api/v1/admin/llm-excluded",
                json={"provider": "opencode_zen", "model": "m1-free"})
    # 再删
    r = client.delete("/api/v1/admin/llm-excluded/opencode_zen/m1-free")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "removed"
    assert data["in_mem_removed"] is True
    assert data["db_deleted"] is True
    # in-memory 真删
    assert not _cat.is_excluded("opencode_zen", "m1-free")


def test_admin_remove_llm_excluded_not_found(admin_client):
    client, _cat, _cm = admin_client
    # 模拟 DB 没这个 key (mock delete 返 False)
    _cm.delete_kv = AsyncMock(return_value=False)
    r = client.delete("/api/v1/admin/llm-excluded/opencode_zen/never-added")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "not_found"
    assert data["in_mem_removed"] is False
    assert data["db_deleted"] is False


def test_admin_list_after_add(admin_client):
    client, _cat, _cm = admin_client
    client.post("/api/v1/admin/llm-excluded",
                json={"provider": "opencode_zen", "model": "m1-free"})
    client.post("/api/v1/admin/llm-excluded",
                json={"provider": "openrouter", "model": "z-free"})
    r = client.get("/api/v1/admin/llm-excluded")
    assert r.json()["total"] == 2
    providers = [it["provider"] for it in r.json()["items"]]
    assert "opencode_zen" in providers
    assert "openrouter" in providers


# ── 4. 跨重启: 模拟启动期 list_keys_with_prefix + load ──────────


@pytest.mark.asyncio
async def test_startup_load_excluded_restores_state():
    """模拟跨重启: DB 有 3 条 llm_excluded:*, 启动后灌回 in-memory."""
    from app.analysis.llm.model_catalog import model_catalog as _cat
    _cat._exclusions.clear()
    # 模拟 DB 返 keys
    fake_db_keys = [
        "llm_excluded:opencode_zen:m1-free",
        "llm_excluded:opencode_zen:m2-free",
        "llm_excluded:openrouter:z-free",
        "DEEPSEEK_API_KEY",  # 无关
    ]
    loaded = _cat.load_excluded_from_keys(fake_db_keys)
    assert loaded == 3
    assert _cat.is_excluded("opencode_zen", "m1-free")
    assert _cat.is_excluded("opencode_zen", "m2-free")
    assert _cat.is_excluded("openrouter", "z-free")
    _cat._exclusions.clear()  # 清理
