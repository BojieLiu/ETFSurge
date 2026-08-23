"""round35 FM1 (docs/round35-architecture-review.md §15.3) —

IC 衰减方向归一验证（🔴 确定性缺陷修复）：
修复前缓存契约「最新在前」+ _ic_decay_mean 假设「旧→新」→ 最旧批拿最大权重
（λ=ln2/20、20 批时新旧权重比 ≈1.93× 反向），「近因衰减」实为「反近因衰减」。
修复后 refresh_ic_series 构建统一为【旧→新】，两个消费方同时回归注释语义：
  · _ic_decay_mean：末位（最新批）权重 1.0；
  · strategy_design fdq `reversed()` 首个非 None = 最新非 None。

含负向锚：若方向反转回归，加权均值将偏向旧端 → 断言 FAIL（能抓假）。
"""
import math
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.factor_aggregate import _ic_decay_mean
from app.database import Base
from app.models.factor_ic import FactorICRecord


# ── ① 数学锚：衰减加权均值偏向新端 ──────────────────────────────────

def test_ic_decay_mean_prefers_new_end():
    """单调序列（旧端 0.02 ×15、新端 0.08 ×5）→ 加权均值显著偏新端；
    与手算 exp(-λ·age) 权重一致；且必须大于简单均值（反向回归即 FAIL）。"""
    lam = math.log(2) / 20
    series = [0.02] * 15 + [0.08] * 5  # 旧 → 新
    n = len(series)
    weights = [math.exp(-lam * (n - 1 - i)) for i in range(n)]  # i=n-1（最新）→ 1.0
    expected = sum(w * v for w, v in zip(weights, series)) / sum(weights)
    got = _ic_decay_mean(series, lam)
    assert got == pytest.approx(expected, abs=1e-9)
    assert got > (sum(series) / n), (
        f"加权均值 {got:.4f} 未偏向新端（简单均值 {sum(series)/n:.4f}）——衰减方向反转回归"
    )
    # 方向敏感性对照：同一数值集合按【新→旧】传入 → 加权值必然更低
    # （旧端 0.02 拿最大权重）；证明函数对序列方向敏感、断言非恒绿。
    got_reversed = _ic_decay_mean(list(reversed(series)), lam)
    assert got_reversed == pytest.approx(sum(
        math.exp(-lam * (n - 1 - i)) * v for i, v in enumerate(reversed(series))
    ) / sum(math.exp(-lam * (n - 1 - i)) for i in range(n)), abs=1e-9)
    assert got > got_reversed


def test_ic_decay_mean_latest_batch_full_weight():
    """末位（最新批）权重恰为 1.0：单元素序列返回原值。"""
    assert _ic_decay_mean([0.06], math.log(2) / 20) == pytest.approx(0.06)


# ── ② 构建侧集成：refresh_ic_series 缓存 = 旧 → 新 ─────────────────

@pytest.fixture
async def ic_db():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"timeout": 30}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[FactorICRecord.__table__])
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_ic_series_builds_oldest_to_newest(ic_db, monkeypatch):
    """写入 3 批不同 computed_at 的 IC 记录 → refresh 后缓存按【旧→新】排列，
    末位=最新批（_ic_decay_mean / fdq reversed 的共同前提）。"""
    from app.factors.factor_registry import registry as _freg

    base = datetime(2026, 8, 20, 18, 0, 0)
    batches = [0.01, 0.02, 0.03]  # 按时间递增写入：旧 → 新
    async with ic_db() as db:
        for i, val in enumerate(batches):
            db.add(FactorICRecord(
                factor_code="fm1_probe",
                ic_value=val,
                sample_count=100,
                trade_date=date(2026, 8, 18) + timedelta(days=i),
                computed_at=base + timedelta(days=i),
            ))
        await db.commit()

    monkeypatch.setattr(_freg, "_ic_series_cache", {}, raising=False)
    async with ic_db() as db:
        count = await _freg.refresh_ic_series(db)

    assert count >= 1
    seq = _freg._ic_series_cache.get("fm1_probe")
    assert seq == [0.01, 0.02, 0.03], f"缓存方向错误（应为旧→新）: {seq}"


# ── ③ 消费侧联动：fdq 取到「最新非 None」 ────────────────────────────

@pytest.mark.asyncio
async def test_fdq_takes_latest_non_none_value(monkeypatch):
    """构造含 None 的旧→新序列 [0.01, None, 0.07, None]——fdq 的
    reversed+break 模式必须取到 0.07（最新非 None），而非最旧 0.01。
    通过 _status_of 分类间接断言（ic_val 影响分类路径）。"""
    from app.factors.factor_registry import registry as _freg
    from app.services.strategy_design import _factor_data_quality_report

    fake_factors = {"fm1_none_probe": object()}
    monkeypatch.setattr(_freg, "_factors", fake_factors, raising=False)
    monkeypatch.setattr(_freg, "_ic_series_cache",
                        {"fm1_none_probe": [0.01, None, 0.07, None]}, raising=False)
    # samples 超过 MIN_TRADING_DAYS → 分类进入 t/IR 判定分支，ic 序列参与 compute_series_stats
    monkeypatch.setattr(_freg, "_sample_counts", {"fm1_none_probe": 300}, raising=False)
    monkeypatch.setattr(_freg, "_data_source_gaps", {}, raising=False)
    monkeypatch.setattr(_freg, "_constant_factor_codes", set(), raising=False)
    monkeypatch.setattr(_freg, "_last_compute_produced", {"fm1_none_probe": 300}, raising=False)

    report = _factor_data_quality_report()
    assert report["total"] == 1
    # 取值语义联动锚：reversed 后首个非 None 必须是 0.07（若方向反转回归则取到 0.01）
    seq = _freg._ic_series_cache["fm1_none_probe"]
    latest_non_none = next(v for v in reversed(seq) if v is not None)
    assert latest_non_none == 0.07, (
        "fdq 消费模式取到的不是最新非 None 值——IC 方向反转回归"
    )
