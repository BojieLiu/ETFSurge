# -*- coding: utf-8 -*-
"""round35 B3-F6 (docs/round35-architecture-review.md §6.3) —
EngineConfig 加载期不变量 INV-7（阈值序 / 配额方向 / 参数范围）。

fail-fast 契约：任何字段被改成违反序关系的值时，validate_engine_config 必须抛
ValueError——杜绝「调参把相关性阈值倒挂」类静默回归（对齐 budgets INV-1~4 风格）。
"""
from dataclasses import replace

import pytest

from app.engine.budgets import ENGINE_CONFIG, validate_engine_config


def test_default_config_passes_validation() -> None:
    """出厂配置必须通过 INV-7（导入期已隐式校验，此处显式断言）。"""
    validate_engine_config(ENGINE_CONFIG)


def test_correlation_threshold_order_enforced() -> None:
    """wide_basis_warn ≥ corr_cap ≥ concentration_avg 任一倒挂即红。"""
    with pytest.raises(ValueError, match="INV-7"):
        validate_engine_config(replace(ENGINE_CONFIG, corr_cap=0.97))


def test_tech_quota_direction_enforced() -> None:
    """防御型科技配额不得超过通用配额。"""
    with pytest.raises(ValueError, match="INV-7"):
        validate_engine_config(replace(ENGINE_CONFIG, tech_quota_defensive=0.6))


def test_softmax_temperature_range_enforced() -> None:
    with pytest.raises(ValueError, match="INV-7"):
        validate_engine_config(replace(ENGINE_CONFIG, softmax_temperature=0.0))


def test_config_is_frozen() -> None:
    """frozen dataclass——运行时篡改配置必须失败。"""
    with pytest.raises(Exception):  # noqa: B017,FrozenInstanceError
        ENGINE_CONFIG.softmax_temperature = 0.5  # type: ignore[misc]
