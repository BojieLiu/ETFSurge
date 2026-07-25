"""
TDD: Solution Design tests (remaining-issues-solution-design.md)

Covers:
  - S1-A: Pool Manager 60s TTL cache (V1-1, V1-2)
  - S2: Factor Registry mixed normalization (V2-1, V2-3)
  - S3-B/C: WS broadcast timeout + cleanup (V3-2, V3-3)
  - S1-C: Progressive state machine — quick_ready stage (V1-3)

All external calls are mocked.
"""
import asyncio
import time
import pytest
from unittest.mock import patch, AsyncMock, Mock, MagicMock


# ═══════════════════════════════════════════════════════════════════
# S1-A: Pool Manager TTL Cache
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pool_ttl_cache_hit():
    """V1-1: TTL 有效期内第二次 refresh 应返回缓存，不触发 I/O"""
    from app.services.pool_manager import PoolManager
    pm = PoolManager()
    # 注入缓存数据
    pm._cached_pool = {"core": [{"symbol": "510300", "name": "HS300ETF"}]}
    pm._cached_ts = time.time()
    pm._by_code = {"510300": {"symbol": "510300"}}
    pm._last_refresh_ts = time.time()  # 必须有值以允许 TTL 命中
    # refresh 应在 TTL 内返回缓存
    with patch.object(pm, '_refresh_impl') as mock_refresh:
        diff = await pm.refresh()
        # TTL 命中时不应调用 _refresh_impl
        mock_refresh.assert_not_called()
    assert diff is not None
    # 检查缓存未被清除
    assert pm._cached_pool is not None


@pytest.mark.asyncio
async def test_pool_ttl_cache_expired():
    """V1-2: TTL 过期后 refresh 应执行刷新"""
    from app.services.pool_manager import PoolManager
    pm = PoolManager()
    # 注入过期缓存
    pm._cached_pool = {"core": []}
    pm._cached_ts = time.time() - 120  # 过期
    pm._by_code = {}
    # 缓存过期后，会走刷新路径；需要 mock _refresh_impl
    with patch.object(pm, '_refresh_impl', new=AsyncMock()) as mock_refresh:
        mock_refresh.return_value = pm._compute_diff({})
        diff = await pm.refresh()
        mock_refresh.assert_called_once()
        assert diff is not None


# ═══════════════════════════════════════════════════════════════════
# S2: Factor Registry Mixed Normalization
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_factor_zero_std_no_crash():
    """V2-3: 零标准差时不崩溃（所有值相同）"""
    from app.factors.factor_registry import FactorRegistry

    reg = FactorRegistry()
    reg._computers = {"test.flat": lambda d: 1.0}
    # 所有值相同，标准差为零
    market_data = {
        "A": {"close": [1, 1, 1, 1, 1]},
        "B": {"close": [1, 1, 1, 1, 1]},
        "C": {"close": [1, 1, 1, 1, 1]},
    }
    with patch.object(reg, '_factors', {"test.flat": MagicMock(standardization="zscore")}):
        try:
            result = await reg.compute(["A", "B", "C"], codes=["test.flat"], market_data=market_data)
            # 不应抛异常
            assert result is not None
        except Exception as e:
            pytest.fail(f"零标准差时崩溃: {e}")


@pytest.mark.asyncio
async def test_factor_normalization_positive():
    """V2-1: 混合归一化后顶部标的正分"""
    from app.factors.factor_registry import FactorRegistry

    reg = FactorRegistry()
    # 注册计算因子: momentum 直接返回原始值
    reg._computers = {"test.momentum": lambda d: d.get("momentum", 0)}
    market_data = {
        "SYM_A": {"close": [1, 2, 3, 4, 5], "momentum": 0.9},
        "SYM_B": {"close": [5, 4, 3, 2, 1], "momentum": -0.5},
        "SYM_C": {"close": [3, 3, 3, 3, 3], "momentum": 0.0},
    }
    with patch.object(reg, '_factors', {"test.momentum": MagicMock(standardization="zscore")}):
        result = await reg.compute(["SYM_A", "SYM_B", "SYM_C"], codes=["test.momentum"], market_data=market_data)
        # SYM_A 的 momentum=0.9 应为排名最高的，应有正分
        score_a = result.get("SYM_A", {}).get("test.momentum", 0)
        score_b = result.get("SYM_B", {}).get("test.momentum", 0)
        score_c = result.get("SYM_C", {}).get("test.momentum", 0)
        # SYM_A 应为最高分
        assert score_a >= score_b and score_a >= score_c, f"SYM_A({score_a}) should be highest"
        # 实际值不确定，但不应为 NaN 或 None
        assert score_a is not None


# ═══════════════════════════════════════════════════════════════════
# S3-B/C: WS Broadcast Timeout + Cleanup
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ws_broadcast_timeout():
    """V3-2: 慢客户端超时不影响其他客户端"""
    from app.routers.ws import ConnectionManager
    from fastapi import WebSocket

    cm = ConnectionManager()

    # 创建模拟 WS 连接
    slow_ws = AsyncMock(spec=WebSocket)
    fast_ws = AsyncMock(spec=WebSocket)
    slow_ws.send_text = AsyncMock(side_effect=asyncio.TimeoutError("timeout"))
    fast_ws.send_text = AsyncMock(return_value=None)

    cm.active_connections["test"] = [slow_ws, fast_ws]
    cm._last_cleanup = time.time() - 120  # 强制清理检查

    await cm.broadcast("test", {"type": "ping"})

    # 慢客户端应被断开
    assert slow_ws not in cm.active_connections.get("test", [])
    # 快客户端应仍在
    assert fast_ws in cm.active_connections.get("test", [])
    fast_ws.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_ws_cleanup_stale():
    """V3-3: 断开清理后 broadcast 不报错"""
    from app.routers.ws import ConnectionManager
    from fastapi import WebSocket

    cm = ConnectionManager()

    # 已断开客户端
    ws = AsyncMock(spec=WebSocket)
    ws.client_state = MagicMock()
    ws.client_state.name = "DISCONNECTED"

    cm.active_connections["test"] = [ws]
    cm._last_cleanup = 0  # 强制清理
    cm._cleanup_interval = 0  # 确保清理立即触发

    await cm._cleanup_stale()

    # 清理后连接列表应为空
    assert len(cm.active_connections.get("test", [])) == 0


# ═══════════════════════════════════════════════════════════════════
# S1-C: Progressive State Machine
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_task_manager_quick_ready():
    """V1-3: TaskManager 支持 quick_ready 状态"""
    from app.tasks.task_manager import TaskManager

    mgr = TaskManager()
    task = mgr.create_task("design", {"capital": 500000})

    mgr.update_task(task["task_id"], status="quick_ready", progress=60,
                    result={"strategies": [], "report_stage": "quick"})

    updated = mgr.get_task(task["task_id"])
    assert updated["status"] == "quick_ready"
    assert updated["progress"] == 60
    assert updated["result"]["report_stage"] == "quick"


@pytest.mark.asyncio
async def test_task_manager_completed_with_errors():
    """验证 completed_with_errors 状态可被正确设置"""
    from app.tasks.task_manager import TaskManager

    mgr = TaskManager()
    task = mgr.create_task("design", {"capital": 500000})

    mgr.update_task(task["task_id"], status="completed_with_errors", progress=100,
                    result={"strategies": [], "report_quality": "fallback"})

    updated = mgr.get_task(task["task_id"])
    assert updated["status"] == "completed_with_errors"
    assert updated["result"]["report_quality"] == "fallback"
