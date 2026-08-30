"""round46: token_usage summary by_provider 维度——定位 LLM 调用源.

背景: by_model 只按 model 名聚合（deepseek-v4-flash-free 无法区分
opencode_zen 与 b_ai 来源），round44 C 方案守卫发现 delta 时无法归因。
本 round 在 summary() 加 by_provider 段（与 by_model 同结构），空 provider
归 "unknown"。

验证:
1. by_provider 出现在 summary() 返回 dict
2. 按 provider 正确分桶（calls/errors/tokens）
3. 空 provider 字符串归 "unknown"
4. by_model 行为不变（向后兼容）
"""
from __future__ import annotations

import asyncio

import pytest

from app.monitor.token_usage import TokenUsageStore, UsageRecord


@pytest.fixture
def store(tmp_path, monkeypatch):
    """隔离的 TokenUsageStore（DB 在 tmp，不碰生产 data/）。"""
    s = TokenUsageStore(max_records=100)
    monkeypatch.setattr(s, "_db_path", tmp_path / "token_usage.db")
    s._init_db()
    return s


def _rec(provider, model, fn="probe", ok=True):
    return UsageRecord(
        function_name=fn,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        model=model,
        timestamp=1000000.0,
        success=ok,
        duration_ms=100.0,
        provider=provider,
    )


def test_summary_includes_by_provider(store):
    """summary() 返回 dict 含 by_provider 段."""
    out = asyncio.run(store.summary())
    assert "by_provider" in out, f"summary 应含 by_provider: {sorted(out)}"


def test_by_provider_buckets_calls_and_errors(store):
    """provider 维度正确分桶 calls/errors/tokens."""
    asyncio.run(store.record(_rec("opencode_zen", "m1")))
    asyncio.run(store.record(_rec("opencode_zen", "m2")))
    asyncio.run(store.record(_rec("b_ai", "m3", ok=False)))

    out = asyncio.run(store.summary())
    bp = out["by_provider"]
    assert bp["opencode_zen"]["calls"] == 2
    assert bp["opencode_zen"]["errors"] == 0
    assert bp["opencode_zen"]["total_tokens"] == 60
    assert bp["b_ai"]["calls"] == 1
    assert bp["b_ai"]["errors"] == 1


def test_by_provider_empty_provider_goes_to_unknown(store):
    """空 provider 字符串归 'unknown'（与 by_model 的 m or 'unknown' 同口径）."""
    asyncio.run(store.record(_rec("", "m1")))
    out = asyncio.run(store.summary())
    assert out["by_provider"]["unknown"]["calls"] == 1


def test_by_provider_same_model_different_providers_separated(store):
    """同 model 不同 provider 分开统计——by_model 合并、by_provider 分开.

    这是 round44 C 方案 delta 归因的关键场景.
    """
    asyncio.run(store.record(_rec("opencode_zen", "deepseek-v4-flash-free")))
    asyncio.run(store.record(_rec("b_ai", "deepseek-v4-flash-free")))
    asyncio.run(store.record(_rec("opencode_zen", "deepseek-v4-flash-free", ok=False)))

    out = asyncio.run(store.summary())
    # by_model: 同 model 合并 = 3 calls
    assert out["by_model"]["deepseek-v4-flash-free"]["calls"] == 3
    assert out["by_model"]["deepseek-v4-flash-free"]["errors"] == 1
    # by_provider: 分开
    assert out["by_provider"]["opencode_zen"]["calls"] == 2
    assert out["by_provider"]["opencode_zen"]["errors"] == 1
    assert out["by_provider"]["b_ai"]["calls"] == 1
    assert out["by_provider"]["b_ai"]["errors"] == 0


def test_by_model_unchanged_backward_compatible(store):
    """向后兼容: by_model 输出结构与 round45 之前一致."""
    asyncio.run(store.record(_rec("opencode_zen", "m1")))
    out = asyncio.run(store.summary())
    bm = out["by_model"]["m1"]
    assert set(bm.keys()) == {"calls", "errors", "prompt_tokens", "completion_tokens",
                              "total_tokens", "avg_duration_ms"}, (
        f"by_model 结构漂移: {sorted(bm)}"
    )
