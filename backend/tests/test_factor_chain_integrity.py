"""round39 §4.4.4 方案 B (round40 实施): 关键因子断链断言.

实施点：backend/scripts/data_health_check.py test_factor_chain_integrity()。
对代表 ETF 跑 factor_registry.compute()，统计 CRITICAL_FACTOR_CODES 在
非空 meaningful 值上的覆盖率，断言至少 1 只 ETF 有非零值——
捕获「全断链」（zero_ratio=1.0）回归如 R146/R147-FIX/R148/R149/R150。

负向断言：
- 全断链（CRITICAL_FACTOR 在所有 ETF 都为 None / 占位 0）→ FAIL
- 非交易时段（全部 ETF 数据源空）→ WARN 不 FAIL（round31 R4-07 教训：误报比不报更糟）
- 仅部分断链 → 仍 PASS（合理降级：某几只 ETF 数据缺失）
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# CRITICAL_FACTOR_CODES: 与 data_health_check.py 内共享（同一份常量，避免漂移）
# R148 收口 (round41): key 必须是 "etf.industry_diversification"（factor_registry.py:713
# 的注册名), 不是 "factor.industry_diversification"——后者是 B 方案 round40 误写.
CRITICAL_FACTOR_CODES: tuple[str, ...] = (
    "etf.premium_discount",     # R146 修复目标
    "style.size.ln_mcap",       # R150 修复目标
    "style.size.ln_float_mcap", # R150 修复目标
    "etf.shares_change",        # R147-FIX 修复目标
    "etf.institutional_holdings_change",  # R147-FIX 关联
    "sentiment.news_heat",      # R149 修复目标
    "etf.industry_diversification",  # R148 修复目标（注意是 etf.* 不是 factor.*）
)

SCRIPTS_PATH = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT_FILE = SCRIPTS_PATH / "data_health_check.py"


def _load_module():
    """按需导入 data_health_check 脚本（隔离 sys.modules 避免重复）。"""
    mod_name = "_data_health_check_dut"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _patch_compute(monkeypatch, fake_output):
    """monkeypatch 脚本里的 FactorRegistry.compute 返回 fake_output."""
    import asyncio

    async def _fake_compute(symbols):
        return {s: dict(fake_output.get(s, {})) for s in symbols}

    def _fake_run(coro):
        # 取得 coro 的 symbols 然后调 fake_compute
        coro.close()
        # 简单兜底: 对固定 4 只 ETF 返回 fake_output 全集
        return {s: dict(fake_output.get(s, {})) for s in ("510300", "518880", "511090", "512480")}

    monkeypatch.setattr("asyncio.run", _fake_run)


def test_critical_factor_constant_is_nonempty():
    """CRITICAL_FACTOR_CODES 至少 5 项, 防后续误清空导致断言退化."""
    assert len(CRITICAL_FACTOR_CODES) >= 5
    for code in CRITICAL_FACTOR_CODES:
        assert isinstance(code, str) and code, f"非法 factor code: {code!r}"


def test_critical_factor_codes_match_script(monkeypatch):
    """脚本里的 CRITICAL_FACTOR_CODES 与本测试保持一致（防漂移）."""
    mod = _load_module()
    assert hasattr(mod, "CRITICAL_FACTOR_CODES"), "脚本缺 CRITICAL_FACTOR_CODES 常量"
    assert set(mod.CRITICAL_FACTOR_CODES) == set(CRITICAL_FACTOR_CODES), (
        f"漂移: 脚本={mod.CRITICAL_FACTOR_CODES} vs 测试={CRITICAL_FACTOR_CODES}"
    )


def test_factor_chain_integrity_passes_when_critical_factors_have_values(monkeypatch):
    """正路: 至少一只 ETF 在关键因子有非零 meaningful 值 → PASS."""
    fake_output = {
        "510300": {
            "etf.premium_discount": 0.003,  # ≥2bp 真实值（FS1 容差）
            "style.size.ln_mcap": 12.5,
            "style.size.ln_float_mcap": 12.4,
            "etf.shares_change": 0.05,
            "etf.institutional_holdings_change": 0.02,
            "sentiment.news_heat": 3.5,
            "etf.industry_diversification": 0.4,  # R148 修正 key (factor.* → etf.*)
        },
        "518880": {"etf.premium_discount": 0.001},
        "511090": {"style.size.ln_mcap": 11.0},
        "512480": {"etf.industry_diversification": 0.5},  # R148 修正
    }
    mod = _load_module()
    mod.PASS = 0
    mod.FAIL = 0
    mod.ERRORS = []
    _patch_compute(monkeypatch, fake_output)
    mod.test_factor_chain_integrity()
    assert mod.FAIL == 0, f"误报 FAIL: ERRORS={mod.ERRORS}"
    assert mod.PASS >= 1


def test_factor_chain_integrity_fails_when_critical_factor_totally_zero(monkeypatch, capfd):
    """负向: 全部 ETF 在某关键因子都是 0/None → 该因子断链 → FAIL."""
    fake_output = {
        "510300": {"etf.premium_discount": 0.0, "style.size.ln_mcap": 0.0},
        "518880": {"etf.premium_discount": 0.0, "style.size.ln_mcap": 0.0},
        "511090": {"etf.premium_discount": None, "style.size.ln_mcap": None},
        "512480": {"etf.premium_discount": 0.0, "style.size.ln_mcap": 0.0},
    }
    mod = _load_module()
    mod.PASS = 0
    mod.FAIL = 0
    mod.ERRORS = []
    _patch_compute(monkeypatch, fake_output)
    mod.test_factor_chain_integrity()
    # 至少 1 条 FAIL（断链的 critical factor）
    assert mod.FAIL >= 1, "未捕获全断链: 期望 FAIL 但全 PASS"
    # FAIL 名称应含「关键因子断链」+ detail 含因子名（premium_discount/ln_mcap）;
    # detail 在 print 出现, ERRORS 只存 name, 故用 capfd 拿 stdout 验证
    out, _ = capfd.readouterr()
    assert (
        "premium_discount" in out or "ln_mcap" in out
    ), f"FAIL detail 未点名具体因子: capfd={out!r}, mod.ERRORS={mod.ERRORS}"


def test_factor_chain_integrity_tolerates_off_hours_when_all_none(monkeypatch):
    """边界: 全部 ETF 全部因子都是 None (非交易时段数据源全空) → WARN, 不 FAIL.

    round31 R4-07 教训: 误报比不报更糟——非交易时段 lazy 注入未触发时,
    全 None 是预期状态, 只 WARN 不阻断.
    """
    fake_output = {
        "510300": {},
        "518880": {},
        "511090": {},
        "512480": {},
    }
    mod = _load_module()
    mod.PASS = 0
    mod.FAIL = 0
    mod.ERRORS = []
    _patch_compute(monkeypatch, fake_output)
    mod.test_factor_chain_integrity()
    # 全空 → 容忍, mod.FAIL == 0
    assert mod.FAIL == 0, (
        f"非交易时段全空应容忍为 WARN (PASS), 但被计 FAIL: {mod.ERRORS}"
    )
    assert mod.PASS >= 1, "全空容忍时应输出至少 1 条 PASS/WARN 提示"


def test_factor_chain_integrity_partial_break_acceptable(monkeypatch):
    """部分断链: 某只 ETF 数据缺失, 但其他 ETF 有值 → 仍 PASS (合理降级)."""
    fake_output = {
        "510300": {},  # 完全空
        "518880": {"etf.premium_discount": 0.003},  # 只有 premium
        "511090": {"style.size.ln_mcap": 11.0},  # 只有 ln_mcap
        "512480": {
            "etf.premium_discount": 0.001,
            "style.size.ln_mcap": 12.0,
            "style.size.ln_float_mcap": 11.9,
            "etf.shares_change": 0.05,
            "etf.institutional_holdings_change": 0.02,
            "sentiment.news_heat": 3.5,
            "etf.industry_diversification": 0.4,  # R148 修正
        },
    }
    mod = _load_module()
    mod.PASS = 0
    mod.FAIL = 0
    mod.ERRORS = []
    _patch_compute(monkeypatch, fake_output)
    mod.test_factor_chain_integrity()
    # 部分缺失但每个 factor 至少 1 只有值 → PASS
    assert mod.FAIL == 0, f"部分缺失应仍 PASS, 误报 FAIL: {mod.ERRORS}"
    assert mod.PASS >= 1
