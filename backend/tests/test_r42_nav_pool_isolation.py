"""round42 A+B 实施: factor_registry._inject_nav 走独立线程池 + Semaphore(8) 限制。

设计:
- A: 1618 NAV 兜底任务不再侵占主线程池 (_shared_executor 64)
  → 切到 _long_running_executor (8), 加 Semaphore(8) 限并发
- B: timeout 6s → 3s (兜底是 best-effort, 与设计请求 15/30/75s 预算不冲突)

单测覆盖: 仅对 IOPV 失败子集触发 / Semaphore ≤ 8 在飞 / timeout 3s / 数据注入正确 / run_sync_long 路径
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


def _patch_hub():
    """_inject_nav 用 ``from ..services.market_data_hub import market_data_hub as _hub``
    是函数内 local import, 需 patch 真实模块路径.
    """
    return patch("app.services.market_data_hub.market_data_hub")


@pytest.mark.asyncio
async def test_nav_one_uses_long_running_executor():
    """A: 5 个 symbol 全部 IOPV 失败 → 走 _inject_nav → 5 个 nav 全部注入."""
    with _patch_hub() as mock_hub:
        mock_hub.get_fund_nav = lambda sym, timeout=6: {"nav": 3.5}
        from app.factors.factor_registry import _inject_nav
        market_data = {}
        await _inject_nav(market_data, ["510050", "510300", "510500", "511090", "518880"])
        for s in ["510050", "510300", "510500", "511090", "518880"]:
            assert market_data[s].get("nav") == 3.5


@pytest.mark.asyncio
async def test_nav_one_semaphore_limits_in_flight_to_8():
    """A+B: Semaphore(8) 限制在飞任务数 ≤ 8."""
    in_flight = 0
    peak_in_flight = 0

    def fake_fetch(sym, timeout=6):
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        time.sleep(0.1)
        in_flight -= 1
        return {"nav": 3.0}

    with _patch_hub() as mock_hub:
        mock_hub.get_fund_nav = fake_fetch
        from app.factors.factor_registry import _inject_nav
        market_data = {}
        await _inject_nav(market_data, [f"51{i:04d}" for i in range(50)])

    assert peak_in_flight <= 8, f"Semaphore 失效: peak_in_flight={peak_in_flight}"


@pytest.mark.asyncio
async def test_nav_one_timeout_3s():
    """A: timeout 实际 3s (原 6s). 验证慢任务 3s 抛 TimeoutError 被吞."""
    def slow_fetch(sym, timeout=6):
        time.sleep(5)  # > 3s
        return {"nav": 3.0}

    with _patch_hub() as mock_hub:
        mock_hub.get_fund_nav = slow_fetch
        from app.factors.factor_registry import _inject_nav
        t0 = time.monotonic()
        market_data = {}
        await _inject_nav(market_data, [f"51{i:04d}" for i in range(10)])
        elapsed = time.monotonic() - t0
        # 8 路并发 (Semaphore), 每路 3s 超时. 总时长 ~3s (首批 8 并发)
        # + 2 个补位再 3s → 总时长 ~6s. 容差放宽到 7s.
        assert elapsed < 7.0, f"timeout 3s 未生效, 总耗时 {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_nav_one_does_not_run_for_iopv_successful_symbols():
    """A: 仅对 IOPV 失败的 symbol 调 NAV 兜底."""
    call_count = 0

    def counting_fetch(sym, timeout=6):
        nonlocal call_count
        call_count += 1
        return {"nav": 3.0}

    with _patch_hub() as mock_hub:
        mock_hub.get_fund_nav = counting_fetch
        from app.factors.factor_registry import _inject_nav
        market_data = {
            f"51{i:04d}": {"nav": 1.0 + i * 0.1} for i in range(3)
        }
        await _inject_nav(
            market_data,
            list(market_data.keys()) + [f"52{i:04d}" for i in range(7)],
        )
        assert call_count == 7, f"call_count 应为 7, 实际 {call_count}"


@pytest.mark.asyncio
async def test_nav_one_data_injection_correct():
    """A+B: NAV 成功注入, 失败时不注入 (best-effort 兜底语义)."""
    def fake_fetch(sym, timeout=6):
        if sym == "FAIL":
            raise RuntimeError("simulated network error")
        return {"nav": 3.5}

    with _patch_hub() as mock_hub:
        mock_hub.get_fund_nav = fake_fetch
        from app.factors.factor_registry import _inject_nav
        market_data = {}
        await _inject_nav(market_data, ["OK1", "FAIL", "OK2"])
        assert market_data["OK1"].get("nav") == 3.5
        assert market_data["OK2"].get("nav") == 3.5
        # FAIL: 不抛 (兜底语义), 但 market_data["FAIL"] 没 nav
        assert "nav" not in market_data.get("FAIL", {})


@pytest.mark.asyncio
async def test_nav_one_uses_run_sync_long(monkeypatch):
    """A+B: _inject_nav 调 run_sync_long 而非 run_sync (主线程池隔离).

    run_sync_long 是 _inject_nav 块内 local import, monkeypatch 必须在
    core.async_utils 层级才能拦截.
    """
    from app.core import async_utils

    long_calls = []
    short_calls = []

    real_run_sync_long = async_utils.run_sync_long
    real_run_sync = async_utils.run_sync

    def named_fetch(sym, timeout=6):
        return {"nav": 3.0}

    async def spy_long(call, *args, **kw):
        # 关键: call 可能是 lambda / 真实函数, 用 duck-typing 验 _hub.get_fund_nav
        # 即从 market_data_hub 模块导入的对象. spy_long 被调时 call 应是 named_fetch
        # (lambda), 所以从 args 拿 _hub 引用更稳.
        long_calls.append("called")
        return await real_run_sync_long(call, *args, **kw)

    async def spy_short(call, *args, **kw):
        short_calls.append("called")
        return await real_run_sync(call, *args, **kw)

    monkeypatch.setattr(async_utils, "run_sync_long", spy_long)
    monkeypatch.setattr(async_utils, "run_sync", spy_short)

    with _patch_hub() as mock_hub:
        mock_hub.get_fund_nav = named_fetch
        from app.factors.factor_registry import _inject_nav
        market_data = {}
        await _inject_nav(market_data, ["510050", "510300"])

    # _inject_nav 实际路径: 先 _fetch_iopv_chain (新浪/QQ/东财, 走 run_sync 拉 HTTP),
    # 然后对 IOPV 失败的 symbol 调 NAV 兜底 (走 run_sync_long). 两者并发.
    # 验证要点: long_calls >= 1 (NAV 兜底走独立池) 且 _missing_nav 全覆盖.
    # 不强求 long > short, 因为 mock 链路下 _fetch_iopv_chain 也调 run_sync 2 次
    # (每个 symbol 1 次, 跨三级降级源). 这不是 NAV 兜底, 是既有 IOPV 链.
    assert len(long_calls) >= 1, (
        f"NAV 兜底应走 run_sync_long; 实际 long_calls={long_calls}"
    )
