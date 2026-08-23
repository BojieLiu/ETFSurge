"""round35 B1-F1a/F1b (docs/round35-architecture-review.md §4.1/§6.1) —

① 纯度门禁相对导入盲区修复：check_engine_purity 必须把 `from ..x.y` 解析为
   app.x.y 再做前缀匹配（D1 门禁级缺陷：旧实现丢弃 ast.ImportFrom.level，
   rationale.py 的上层依赖静默绕过门禁）。
② composite_signal/_cap 下沉 engine/signal.py 后的平价与兼容性。

含负向 fixture（防「门禁静默通过」回归——门禁自身需要被测试）。
"""
import ast
import importlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import check_engine_purity as purity  # noqa: E402


# ── F1a: 相对导入解析 ──────────────────────────────────────────────

def _pkg_parts():
    return ["app", "engine"]


def test_relative_import_level2_resolves_to_app_analysis():
    """正向解析：level=2 → 上跳到 app 拼接 → 命中禁入前缀。"""
    resolved = purity._resolve("analysis.signal", 2, _pkg_parts())
    assert resolved == "app.analysis.signal"
    assert any(
        resolved == pkg or resolved.startswith(pkg + ".")
        for pkg in purity.FORBIDDEN_PACKAGES
    )


def test_relative_import_level1_stays_in_engine():
    """合法内部引用：from .budgets import X (level=1) → app.engine.budgets ✓放行。"""
    resolved = purity._resolve("budgets", 1, _pkg_parts())
    assert resolved == "app.engine.budgets"


def test_absolute_import_unchanged():
    assert purity._resolve("app.services.foo", 0, _pkg_parts()) == "app.services.foo"


def test_from_import_module_none_level1(tmp_path):
    """边界：`from . import budgets`（module=None, level=1）→ 解析为 app.engine 合法。"""
    f = tmp_path / "probe.py"
    f.write_text("from . import budgets\n", encoding="utf-8")
    tree = ast.parse(f.read_text(encoding="utf-8"))
    pairs = list(purity._iter_imports(tree))
    assert ("", 1) in pairs or ("budgets", 1) in pairs
    # 解析结果不落在任何禁入包
    for module, level in pairs:
        resolved = purity._resolve(module, level, _pkg_parts())
        assert not any(
            resolved == pkg or resolved.startswith(pkg + ".")
            for pkg in purity.FORBIDDEN_PACKAGES
        )


def test_gate_catches_relative_upper_layer_import(tmp_path):
    """负向（防门禁静默通过回归）：伪引擎文件含 `from ..analysis.x import y`
    → check_file 违规列表非空且消息含 app.analysis.x。"""
    fake = tmp_path / "fake_engine_mod.py"
    fake.write_text("from ..analysis.x import y\n", encoding="utf-8")
    # 以真实 engine 目录内文件身份检查（relative_to 需要 ENGINE_DIR 前缀）
    staged = purity.ENGINE_DIR / "_gate_probe_tmp.py"
    staged.write_text("from ..analysis.x import y\n", encoding="utf-8")
    try:
        violations = purity.check_file(staged)
        assert violations, "门禁未抓到相对导入的上层依赖——D1 盲区回归！"
        assert any("app.analysis.x" in v for v in violations)
    finally:
        staged.unlink(missing_ok=True)


def test_gate_passes_engine_internal_relative_import(tmp_path):
    """对照：同目录内 `from .signal import composite_signal` → 无违规。"""
    staged = purity.ENGINE_DIR / "_gate_probe_ok_tmp.py"
    staged.write_text("from .signal import composite_signal\n", encoding="utf-8")
    try:
        assert purity.check_file(staged) == []
    finally:
        staged.unlink(missing_ok=True)


def test_real_engine_tree_has_no_upper_layer_import():
    """全量扫描当前 engine 树（rationale.py 下沉后应 OK；若再引入上层依赖即 FAIL）。"""
    rc = purity.main()
    assert rc == 0


# ── F1b: composite_signal 平价与兼容 ───────────────────────────────

@pytest.fixture(scope="module")
def engine_signal():
    from app.engine import signal as mod

    return mod


@pytest.fixture(scope="module")
def analysis_signal():
    from app.analysis import signal as mod

    return mod


def test_sink_parity_double_weak_not_buy(engine_signal):
    """589720 回归锚：双弱不判多——技术 -0.408 / 估值 -0.462 / 动量 +1.047 → hold 非 buy。
    （动量原始值 >1 被 cap 到 1.0，加权 0.4*(-0.408)+0.4*(-0.462)+0.2*1.0 = -0.068）"""
    out = engine_signal.composite_signal(-0.408, -0.462, 1.047)
    assert out["signal"] == "hold"
    assert out["components"]["momentum"] == pytest.approx(1.0)


def test_sink_cap_boundary(engine_signal):
    """cap 边界：极端输入 |score| ≤ 1.0。"""
    out = engine_signal.composite_signal(9.9, 9.9, 9.9)
    assert out["components"] == {"technical": 1.0, "valuation": 1.0, "momentum": 1.0}


def test_reexport_same_object(analysis_signal, engine_signal):
    """兼容：analysis 路径 re-export 与 engine 单一实现是同一对象（防再次复制）。"""
    assert analysis_signal.composite_signal is engine_signal.composite_signal
    assert analysis_signal._cap is engine_signal._cap


def test_legacy_import_path_still_works(analysis_signal):
    """旧调用点 `from app.analysis.signal import composite_signal` 仍可用，
    with_gate 复用下沉实现。"""
    fn = getattr(analysis_signal, "composite_signal")
    out = fn(0.5, 0.5, 0.5)
    assert out["signal"] == "buy"
