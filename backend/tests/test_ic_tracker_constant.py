"""
U3/N06 (round2-unfixed-fix-plan.md U3 / round3-diagnosis-and-optimization-plan.md N06):
IC 数据被全 0 批次覆盖。

- compute_ic 常量输入（nunique()==1）返回 None 而非 0（不再产生 ConstantInputWarning+NaN→0）。
- compute_periodic_ic 跳过 None / 样本不足的因子（不写 0.0）。
- factor_registry._last_ic_batch 覆盖守卫：新批次无有效信号时保留旧值 + WARNING。
- save_ic_batch_to_db 过滤 None/NaN。

无网络，纯函数测试。
"""

import pandas as pd
import pytest

from app.factors.ic_tracker import ICTracker
from app.factors.factor_registry import FactorRegistry


class TestComputeIcConstantInput:
    def test_constant_factor_returns_none(self):
        """U3 R1: 常量因子值 → None（跳过），不再返回 0.0。"""
        tracker = ICTracker()
        fv = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0])
        rets = pd.Series([0.01, 0.02, -0.01, 0.03, 0.00])
        assert tracker.compute_ic(fv, rets) is None

    def test_constant_returns_returns_none(self):
        """U3 R1: 常量收益序列 → None。"""
        tracker = ICTracker()
        fv = pd.Series([0.5, 0.6, 0.7, 0.8, 0.9])
        rets = pd.Series([0.01, 0.01, 0.01, 0.01, 0.01])
        assert tracker.compute_ic(fv, rets) is None

    def test_insufficient_samples_returns_none(self):
        """U3 R1: 样本 <3 → None（原 0.0）。"""
        tracker = ICTracker()
        fv = pd.Series([0.5, 0.6])
        rets = pd.Series([0.01, 0.02])
        assert tracker.compute_ic(fv, rets) is None

    def test_normal_input_returns_ic(self):
        """正常输入仍返回有效 IC（回归保护）。"""
        tracker = ICTracker()
        fv = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
        rets = pd.Series([0.01, 0.02, -0.01, 0.04, 0.03])
        ic = tracker.compute_ic(fv, rets)
        assert ic is not None
        assert isinstance(ic, float)


class TestComputePeriodicIc:
    def test_constant_batch_skips_constant_factors(self):
        """U3 R2: 常量输入的因子不出现在 ic_results（不再写 0.0）。"""
        tracker = ICTracker()
        # symbol_a/b/c 因子值全常量 → 应被跳过
        factor_values = {
            "a": {"f1": 0.5, "f2": 1.0},
            "b": {"f1": 0.5, "f2": 2.0},
            "c": {"f1": 0.5, "f2": 3.0},
        }
        market_data = {
            "a": {"close": [1.0, 1.01, 1.02, 1.03, 1.04]},
            "b": {"close": [2.0, 2.02, 2.03, 2.05, 2.06]},
            "c": {"close": [3.0, 3.01, 3.02, 3.04, 3.05]},
        }
        result = tracker.compute_periodic_ic(factor_values, market_data)
        # f1 常量 → 不在结果；f2 有区分度 → 在结果
        assert "f1" not in result, "常量因子不得写入 IC 批次（会覆盖有效值）"
        assert "f2" in result

    def test_no_market_data_returns_empty(self):
        """market_data 缺失 → 空 dict（不产生假批次）。"""
        tracker = ICTracker()
        assert tracker.compute_periodic_ic({"a": {"f1": 0.5}}, None) == {}


class TestLastIcBatchGuard:
    def test_no_signal_batch_keeps_previous(self, caplog):
        """U3 R2: 全 0 因子值在 compute_periodic_ic 分组阶段即被排除 → 空批次。"""
        import logging
        from app.factors.ic_tracker import ic_tracker as tracker
        with caplog.at_level(logging.WARNING, logger="app.factors.ic_tracker"):
            ic_batch = tracker.compute_periodic_ic(
                {"a": {"f1": 0.0}, "b": {"f1": 0.0}, "c": {"f1": 0.0}},
                {"a": {"close": [1, 2, 3]}, "b": {"close": [1, 2, 3]}, "c": {"close": [1, 2, 3]}},
            )
        # 全 0 因子值在 compute_periodic_ic 分组阶段即被排除（abs(val)<0.001）
        assert ic_batch == {}, "全 0 因子不应产生 IC 批次"

    @pytest.mark.asyncio
    async def test_compute_all_zero_batch_keeps_previous(self, caplog):
        """U3 R2: compute() 收到全 0 批次 → _last_ic_batch 保留旧值 + WARNING。"""
        import logging
        from unittest.mock import patch
        from app.factors.factor_registry import registry as reg
        from app.factors.ic_tracker import ic_tracker

        reg._last_ic_batch = {"f1": 0.25, "f2": -0.18}  # 有效旧值
        market_data = {
            "510300": {
                "close": [4.0 + i * 0.01 for i in range(60)],
                "high": [4.0 + i * 0.02 for i in range(60)],
                "low": [4.0 - i * 0.005 for i in range(60)],
                "volume": [2_000_000 + i * 500 for i in range(60)],
            }
        }
        with patch.object(ic_tracker, "compute_periodic_ic",
                          return_value={"f1": 0.0, "f2": 0.0}), \
             patch.object(ic_tracker, "record"):
            with caplog.at_level(logging.WARNING, logger="app.factors.factor_registry"):
                await reg.compute(["510300"], market_data=market_data)

        assert reg._last_ic_batch == {"f1": 0.25, "f2": -0.18}, \
            "全 0 批次不得覆盖有效旧值"
        assert any("no valid signal" in r.message for r in caplog.records), \
            "全 0 批次必须打 WARNING"

    @pytest.mark.asyncio
    async def test_compute_valid_batch_overwrites(self):
        """U3 R2: 含有效 IC 的批次正常覆盖。"""
        from unittest.mock import patch
        from app.factors.factor_registry import registry as reg
        from app.factors.ic_tracker import ic_tracker

        reg._last_ic_batch = {"f1": 0.25}
        market_data = {
            "510300": {
                "close": [4.0 + i * 0.01 for i in range(60)],
                "high": [4.0 + i * 0.02 for i in range(60)],
                "low": [4.0 - i * 0.005 for i in range(60)],
                "volume": [2_000_000 + i * 500 for i in range(60)],
            }
        }
        with patch.object(ic_tracker, "compute_periodic_ic",
                          return_value={"f1": 0.31}), \
             patch.object(ic_tracker, "record"):
            await reg.compute(["510300"], market_data=market_data)

        assert reg._last_ic_batch.get("f1") == 0.31, "有效批次应覆盖旧值"

    def test_save_ic_batch_filters_nan_and_none(self):
        """U3: 落库过滤 None/NaN/0。"""
        tracker = ICTracker()
        # 用内存会话替代 DB——save_ic_batch_to_db 需要 AsyncSession，
        # 此处只验证过滤逻辑可通过 mock 会话计数。
        class _FakeSession:
            def __init__(self):
                self.added = []

            def add(self, record):
                self.added.append(record)

            async def commit(self):
                pass

        import asyncio
        sess = _FakeSession()
        batch = {"f1": 0.25, "f2": 0.0, "f3": None, "f4": float("nan")}
        count = asyncio.run(tracker.save_ic_batch_to_db(sess, batch))
        assert count == 1, "只有 f1 有效"
        assert len(sess.added) == 1
        assert sess.added[0].factor_code == "f1"
