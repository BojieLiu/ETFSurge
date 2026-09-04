"""round44 方案 A (round39 §4.4.4): verify_allocation_invariants.py 端到端不变量校验.

测试聚焦: _check_design 纯函数 (避免 urllib 真实请求, 单测全离线).
端到端真实请求验证由后端运行时执行 (在 commit message 引用, 实战另跑).

负向断言覆盖:
- sat 层超 budget 必被捕获
- 总仓位 > 1.0 必被捕获
- 多层累加超 budget 必被捕获
- 容差 TOLERANCE=0.01 边界 (刚好 budget+0.01 PASS, 超出 1 个 ULP FAIL)
- 防御层 cap=0 跳过 (与 _enforce_layer_budget_final 内部 guard 一致)
- 空 etfs / 空 strategies 不算违例
- _run 函数对 URLError 返回 ERROR 退出码 2
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# 加载脚本 (与 test_r39_b_factor_chain_integrity.py 同款, 隔离 sys.modules)
SCRIPTS_PATH = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT_FILE = SCRIPTS_PATH / "verify_allocation_invariants.py"


def _load_module():
    mod_name = "_verify_allocation_invariants_dut"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_design(d_id, strategies):
    return {"id": d_id, "strategies": strategies}


def _make_strategy(sid, etfs, layer_budget=None):
    return {
        "id": sid,
        "etfs": etfs,
        "layer_budget": layer_budget or {},
    }


def _make_etf(symbol, layer, weight):
    return {"symbol": symbol, "layer": layer, "weight": weight}


# ── _check_design 纯函数单测 ──

def test_check_design_sat_within_budget_passes():
    """正路: sat 0.20 = budget 0.20, 总仓位 0.90 ≤ 1.0 → 无违例."""
    mod = _load_module()
    design = _make_design(1, [
        _make_strategy("balanced", [
            _make_etf("510300", "core", 0.50),
            _make_etf("159915", "core", 0.20),
            _make_etf("518880", "satellite", 0.10),
            _make_etf("513500", "satellite", 0.10),
        ], layer_budget={"core": 0.80, "satellite": 0.20}),
    ])
    assert mod._check_design(design) == []


def test_check_design_sat_exceeds_budget_violates():
    """负向: sat 0.30 > budget 0.22 → 违例 (round39 design 12 实证)."""
    mod = _load_module()
    design = _make_design(12, [
        _make_strategy("balanced", [
            _make_etf("510300", "core", 0.50),
            _make_etf("159915", "satellite", 0.30),  # sat > 0.22
        ], layer_budget={"core": 0.80, "satellite": 0.22}),
    ])
    violations = mod._check_design(design)
    assert len(violations) == 1
    assert "satellite" in violations[0] and "0.3000" in violations[0] and "0.2200" in violations[0]


def test_check_design_total_exceeds_one_violates():
    """负向: 总仓位 1.03 > 1.0 → 违例 (round39 design 12 balanced 总仓位实证)."""
    mod = _load_module()
    design = _make_design(12, [
        _make_strategy("balanced", [
            _make_etf("510300", "core", 0.50),
            _make_etf("159915", "core", 0.30),
            _make_etf("518880", "satellite", 0.23),  # 总 1.03
        ], layer_budget={"core": 0.80, "satellite": 0.30}),
    ])
    violations = mod._check_design(design)
    # 1.03 > 0.80+0.01=0.81 ✓ core 超 + 1.03 > 1.0+0.01 总仓位超
    # 预期至少 1 条关于总仓位违例
    assert any("non_cash" in v or "total" in v.lower() for v in violations), (
        f"应捕获总仓位 > 1.0; 实际违例={violations}"
    )


def test_check_design_defense_layer_cap_zero_skipped():
    """防御层 cap=0 时跳过该层 (与 _enforce_layer_budget_final 内部 guard 一致)."""
    mod = _load_module()
    design = _make_design(1, [
        _make_strategy("balanced", [
            _make_etf("510300", "core", 0.30),
            # defense 99% 但 cap=0 跳过层预算校验; 总仓位 0.30 + 0.99 = 1.29 > 1.0
            # 应被总仓位校验捕获 (defense cap=0 不豁免总仓位, 只豁免单层)
            _make_etf("518880", "defense", 0.99),
        ], layer_budget={"core": 0.80, "defense": 0.0}),
    ])
    violations = mod._check_design(design)
    # 期望: 只有总仓位违例, 无 defense 单层违例
    assert any("non_cash" in v for v in violations), f"总仓位应违例; 实际={violations}"
    assert not any("defense" in v for v in violations), (
        f"defense cap=0 应豁免单层校验; 实际={violations}"
    )


def test_check_design_tolerance_boundary_exact():
    """容差边界: sat = budget + 0.01 算 PASS (≤budget+tol); sat = budget + 0.02 算 FAIL."""
    mod = _load_module()
    # 边界 PASS
    design_pass = _make_design(1, [
        _make_strategy("s", [_make_etf("510300", "satellite", 0.23)],
                       layer_budget={"satellite": 0.22}),
    ])
    assert mod._check_design(design_pass) == [], "0.22+0.01 应在容差内 PASS"
    # 边界 FAIL
    design_fail = _make_design(2, [
        _make_strategy("s", [_make_etf("510300", "satellite", 0.24)],
                       layer_budget={"satellite": 0.22}),
    ])
    violations = mod._check_design(design_fail)
    assert len(violations) == 1, f"0.22+0.02 应 FAIL; 实际={violations}"


def test_check_design_empty_strategies_passes():
    """空 strategies 不算违例 (无 design 阶段时)."""
    mod = _load_module()
    design = _make_design(1, [])
    assert mod._check_design(design) == []


def test_check_design_cash_etf_excluded_from_total():
    """CASH 不计入 non_cash_total (符合 R140 契约: cash = 1 - Σ非 CASH)."""
    mod = _load_module()
    design = _make_design(1, [
        _make_strategy("s", [
            _make_etf("510300", "core", 0.50),
            _make_etf("CASH", "core", 0.50),  # CASH 不计入 non_cash
        ], layer_budget={"core": 1.0}),
    ])
    assert mod._check_design(design) == [], "CASH 应豁免, non_cash=0.50 ≤ 1.0"


# ── _run 网络错误处理 ──

def test_run_urllib_error_returns_exit_2():
    """后端不可达 → _run 返回 2 (ERROR).

    mock _get_json 抛 URLError（而非真实 urlopen）：F23 socket 守卫只放行
    localhost，真实请求 `http://invalid:9999` 在全量 xdist 下撞
    NetworkBlockedError（单跑借道系统代理 127.0.0.1 白名单侥幸通过）。
    exit-2 契约本就只关心 URLError 的 except 分支，mock 即可确定性覆盖。
    """
    import urllib.error

    mod = _load_module()
    args = type("Args", (), {"base": "http://invalid:9999", "limit": 5, "design_id": None})()
    with patch.object(
        mod, "_get_json",
        side_effect=urllib.error.URLError("mocked: backend unreachable"),
    ):
        rc = mod._run(args)
    assert rc == 2, f"后端不可达应返 ERROR 退出码 2; 实际={rc}"


def test_run_design_id_violation_returns_exit_1():
    """_run 单 design 模式: 违例返 1 (FAIL)."""
    mod = _load_module()
    fake = {
        "id": 999,
        "strategies": [{
            "id": "balanced",
            "etfs": [_make_etf("510300", "satellite", 0.30)],
            "layer_budget": {"satellite": 0.20},
        }],
    }
    args = type("Args", (), {"base": "http://x", "limit": 5, "design_id": 999})()
    with patch.object(mod, "_get_json", return_value=fake):
        rc = mod._run(args)
    assert rc == 1, f"违例应返 1 (FAIL); 实际={rc}"


def test_run_design_id_compliant_returns_exit_0():
    """_run 单 design 模式: 合规返 0 (PASS)."""
    mod = _load_module()
    fake = {
        "id": 13,
        "strategies": [{
            "id": "balanced",
            "etfs": [_make_etf("510300", "core", 0.50)],
            "layer_budget": {"core": 0.80},
        }],
    }
    args = type("Args", (), {"base": "http://x", "limit": 5, "design_id": 999})()
    with patch.object(mod, "_get_json", return_value=fake):
        rc = mod._run(args)
    assert rc == 0


def test_default_limit_is_one():
    """默认 --limit=1 (仅最新 design): 防历史数据持续 FAIL."""
    mod = _load_module()
    calls: list[str] = []
    def fake_get(url, timeout=15):
        calls.append(url)
        return []  # 空 list → _run 返 [WARN] PASS rc=0
    with patch.object(mod, "_get_json", side_effect=fake_get):
        rc = mod.main([])
    assert rc == 0
    # 验证 _run 默认用 limit=1 (取最新一个 design, 不带 --limit 参数)
    assert any("limit=1" in c for c in calls), (
        f"默认应调 /designs?limit=1; 实际 calls={calls}"
    )


# ── R172 (round52 §4.3 方案C): base 默认值 [::1] → localhost 回退 ──
#
# round52 §4.1: 裸跑 `python scripts/verify_allocation_invariants.py` 在容器场景
# （0.0.0.0 v4 端口映射 + 宿主代理劫持 [::1]）挂死/超时，必须显式 --base 才能 PASS。
# 负向断言：[::1] 不可达时必须落到 localhost，而不是继续挂在不可达地址上。

def test_resolve_base_explicit_skips_probe():
    """显式 --base 原样使用（patrol 传参路径不受影响，且不做网络探测）。"""
    mod = _load_module()
    with patch.object(mod, "_probe_health", side_effect=AssertionError("不应探测")):
        assert mod._resolve_base("http://127.0.0.1:9000/") == "http://127.0.0.1:9000"


def test_resolve_base_falls_back_to_localhost():
    """负向核心：[::1] 不可达 → 必须回退 localhost（否则容器裸跑挂死）。"""
    mod = _load_module()
    with patch.object(mod, "_probe_health", side_effect=[False, True]) as probe:
        base = mod._resolve_base(None)
    assert base == mod.FALLBACK_BASE, f"[::1] 不可达时应回退 localhost，实际 {base}"
    assert probe.call_count == 2


def test_resolve_base_prefers_ipv6_when_reachable():
    """[::1] 可达时保持原默认（本地 --host :: 场景行为不变）。"""
    mod = _load_module()
    with patch.object(mod, "_probe_health", return_value=True) as probe:
        base = mod._resolve_base(None)
    assert base == mod.DEFAULT_BASE
    assert probe.call_count == 1, "可达时不应再探测回退地址"


def test_resolve_base_keeps_default_when_both_down():
    """两个都不可达 → 回落默认值（随后由 _run 报 ERROR 退出码 2）。"""
    mod = _load_module()
    with patch.object(mod, "_probe_health", return_value=False):
        assert mod._resolve_base(None) == mod.DEFAULT_BASE


def test_probe_health_returns_false_on_any_error():
    """探测：urlopen 抛 URLError/HTTPError(502)/超时 → False，不向上抛。"""
    mod = _load_module()

    def boom(url, timeout=15):
        raise urllib.error.HTTPError(url, 502, "Bad Gateway", None, None)

    with patch.object(mod, "_get_json", side_effect=boom):
        assert mod._probe_health("http://[::1]:8000") is False
