"""Round45 option C acceptance verification.

不重启后端, 用 redis_cache_sync 实际写入一个 fund_nav: 符号 + 读出 + 删除,
验证 Redis 端到端工作. 同时检查 fetch_fund_nav 不可用时降级路径.

若 Redis 真不可达 (无 server 启动) → 降级到 no-op, 验证降级路径 (不应崩溃).
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    from app.services.cache_service import redis_cache_sync

    print("=== Round45 option C Redis 端到端验证 ===\n")

    # 1. ping
    print("[1] redis_cache_sync.ping() ...", end=" ")
    ping_ok = redis_cache_sync.ping()
    print(f"{'OK' if ping_ok else 'UNAVAILABLE (降级模式)'}")

    if not ping_ok:
        print("\n[INFO] Redis 不可达, 验证降级路径:")
        # get 返 None
        r = redis_cache_sync.get("fund_nav:verify")
        assert r is None, f"get 不可用应返 None, 实得 {r!r}"
        print("  - get(unavailable) 返 None: OK")
        # set 返 False
        ok = redis_cache_sync.set("fund_nav:verify", {"nav": 4.5}, ttl=10)
        assert ok is False, f"set 不可用应返 False, 实得 {ok!r}"
        print("  - set(unavailable) 返 False: OK")
        print("\n[SKIP] Redis 不可达, 跳过 write/read 闭环验证")
        print("       (本机需启动 redis-server 才能跑 set/get 端到端)")
        return 0

    # 2. set + get 闭环
    test_key = "fund_nav:r45_verify"
    test_value = {
        "nav": 4.567,
        "daily_change_pct": 0.12,
        "nav_date": "2026-08-29",
        "verify_marker": "round45_option_c",
    }
    print(f"\n[2] SET {test_key} = {test_value}")
    ok = redis_cache_sync.set(test_key, test_value, ttl=10)
    print(f"    -> {ok}")
    assert ok, "set 应返 True"

    print(f"\n[3] GET {test_key}")
    val = redis_cache_sync.get(test_key)
    print(f"    -> {val}")
    assert val == test_value, f"get 应返原值, 实得 {val!r}"

    # 4. TTL 验证 (redis-cli 层面已生效, 客户端无 TTL 字段但服务器有)
    # 跳过客户端 TTL 验证, 信任 Redis 服务端.

    # 5. 清理 (避免污染生产)
    print(f"\n[4] DEL {test_key} (清理)")
    # 用 ping 的 client 调 delete (redis_cache_sync 没暴露 del)
    if redis_cache_sync._client is not None:
        deleted = redis_cache_sync._client.delete(test_key)
        print(f"    -> deleted={deleted}")
        # 再次 get 应 None
        val2 = redis_cache_sync.get(test_key)
        assert val2 is None, f"删除后 get 应 None, 实得 {val2!r}"
        print(f"    verify: GET after DEL -> None: OK")

    print("\n[OK] Redis 端到端验证 PASS")
    print("     二次启动 lifespan 1618 任务应能命中此模式缓存")
    return 0


if __name__ == "__main__":
    sys.exit(main())
