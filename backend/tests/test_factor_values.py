# -*- coding: utf-8 -*-
"""round35 §15.6-FS1 (docs/round35-architecture-review.md) —
零值阈值单点 is_meaningful_value：容差按因子覆盖，tracking_error 特判入表。
"""
import pytest

from app.core.factor_values import DEFAULT_ZERO_TOLERANCE, FACTOR_ZERO_TOLERANCE, is_meaningful_value


def test_default_tolerance() -> None:
    assert is_meaningful_value("technical.ma.sma_5", 0.002) is True
    assert is_meaningful_value("technical.ma.sma_5", 0.0005) is False


def test_tracking_error_special_case() -> None:
    """round14 P2-Z 口径：合法跟踪误差 0.001~0.02 不得判零，仅排除真 0。"""
    assert FACTOR_ZERO_TOLERANCE["etf.tracking_error"] == 1e-6
    assert is_meaningful_value("etf.tracking_error", 5e-4) is True   # 默认容差下会被误杀的合法值
    assert is_meaningful_value("etf.tracking_error", 9e-7) is False  # 真 0（数值噪声）


def test_boundary_is_strict_greater() -> None:
    """canonical 判定为严格大于——恰好等于容差的值视为占位零。"""
    tol = DEFAULT_ZERO_TOLERANCE
    assert is_meaningful_value("x.y.z", tol) is False
    assert is_meaningful_value("x.y.z", tol * 1.0001) is True


@pytest.mark.parametrize("bad", ["0.05", None, [0.1]])
def test_non_numeric_is_meaningless(bad) -> None:
    """R58：数据源异常可能给 str/None/容器——一律无意义。"""
    assert is_meaningful_value("any.code", bad) is False


def test_negative_values_are_meaningful_by_magnitude() -> None:
    assert is_meaningful_value("momentum.x", -0.02) is True
    assert is_meaningful_value("momentum.x", -1e-4) is False
