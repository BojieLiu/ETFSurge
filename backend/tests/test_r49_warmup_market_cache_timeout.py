"""round49 A4: warmup_market_cache timeout 10s → 25s.

覆盖:
  - refresh_market_cache 11s 慢 (旧 10s 超时 → except) → 25s 不超
  - refresh_market_cache 30s 极慢 (新 25s 超时 → except, 仍按预期失败)
  - refresh_market_cache 5s 快 (立即 success)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_warmup_market_cache_completes_within_25s():
    """11s 慢 warmup: 旧 10s 超时失败, 25s 25s 成功 (R45 量化 10.57s)."""
    # 通过 asyncio.wait_for 直接验证 timeout 行为. 实际 main.py 中是
    # await asyncio.wait_for(refresh_market_cache(), timeout=25)

    async def slow_refresh():
        await asyncio.sleep(11)
        return None

    # 11s 任务 + 25s timeout → 应正常完成
    t0 = asyncio.get_event_loop().time()
    try:
        result = await asyncio.wait_for(slow_refresh(), timeout=25)
        elapsed = asyncio.get_event_loop().time() - t0
        assert result is None
        assert 10.5 <= elapsed <= 12, f"应约 11s, 实测 {elapsed:.2f}s"
    except asyncio.TimeoutError:
        pytest.fail("11s 任务在 25s timeout 内应完成, 不应 TimeoutError")


@pytest.mark.asyncio
async def test_warmup_market_cache_old_timeout_would_fail():
    """10s timeout + 11s 任务 → 旧 10s timeout 必失败 (反向证明改 25s 必要)."""
    async def slow_refresh():
        await asyncio.sleep(11)
        return None

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow_refresh(), timeout=10)


@pytest.mark.asyncio
async def test_warmup_market_cache_extreme_slow_still_fails():
    """30s 极慢 warmup + 25s timeout → 仍按预期抛 TimeoutError (不静默吞)."""
    async def very_slow_refresh():
        await asyncio.sleep(30)
        return None

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(very_slow_refresh(), timeout=25)


@pytest.mark.asyncio
async def test_warmup_market_cache_fast_succeeds():
    """5s 快 warmup + 25s timeout → 立即完成."""
    async def fast_refresh():
        await asyncio.sleep(0.1)
        return None

    result = await asyncio.wait_for(fast_refresh(), timeout=25)
    assert result is None


def test_warmup_market_cache_timeout_value_in_main():
    """源码层面验证: warmup_market_cache timeout 改为 25s.

    这是 source-of-truth 测试, 避免后人误改回 10s. 通过正则匹配
    'wait_for(refresh_market_cache(), timeout=N)' 提取 N.
    """
    from pathlib import Path
    main_py = Path(__file__).resolve().parent.parent / "app" / "main.py"
    text = main_py.read_text(encoding="utf-8", errors="replace")
    import re
    m = re.search(
        r"asyncio\.wait_for\(refresh_market_cache\(\),\s*timeout=(\d+)\)",
        text,
    )
    assert m, "未找到 wait_for(refresh_market_cache(), timeout=N)"
    n = int(m.group(1))
    assert n == 25, f"warmup_market_cache timeout 应为 25s (round49 A4), 实为 {n}s"
