"""验证 SourceMonitor 新增的 2 个 admin 端点真实可用 (反假完成)."""
import asyncio
from app.routers.admin import list_llm_excluded, get_lifespan_warmup
from fastapi import Request


class FakeApp:
    class State:
        def __init__(self):
            self.nav_warmup = {
                "enabled": True,
                "started_at": 0.0,
                "warmup_period_s": 3600,
                "first_run_delay_s": 60,
                "last_cycle": None,
                "last_cycle_start_ts": None,
                "next_run_eta_s": None,
                "redis_available": False,
            }
    state = State()


async def main():
    req = Request(scope={"type": "http", "app": FakeApp()})

    # 1. list_llm_excluded (R46)
    r1 = await list_llm_excluded()
    print("[R46] list_llm_excluded 返回:", r1)

    # 2. get_lifespan_warmup (R49 B3)
    r2 = await get_lifespan_warmup(req)
    print("[R49] get_lifespan_warmup 返回 keys:", list(r2.keys()))

    # 3. add/remove 全闭环 (R46)
    from app.analysis.llm.model_catalog import model_catalog
    from app.core.config_manager import config_manager
    from app.routers.admin import add_llm_excluded, remove_llm_excluded
    from app.routers.admin import LLMExcludedCreate

    class FakeCM:
        async def set_kv(self, *a, **kw): return True
        async def delete_kv(self, *a, **kw): return True

    config_manager.set_kv = FakeCM().set_kv
    config_manager.delete_kv = FakeCM().delete_kv
    _saved_excl = model_catalog._exclusions.copy()
    try:
        model_catalog._exclusions.clear()
        body = LLMExcludedCreate(provider="opencode_zen", model="test-r50", reason="verify")
        r3 = await add_llm_excluded(body)
        print("[R46] add_llm_excluded:", r3["status"])
        assert r3["status"] == "added"
        r4 = await remove_llm_excluded("opencode_zen", "test-r50")
        print("[R46] remove_llm_excluded:", r4["status"])
        assert r4["status"] == "removed"
    finally:
        model_catalog._exclusions.clear()
        model_catalog._exclusions.update(_saved_excl)
    print("\n[R50 C3 验证] 3 端点 + 闭环全 PASS")


asyncio.run(main())
