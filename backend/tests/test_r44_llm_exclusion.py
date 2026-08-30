"""round44 方案 C (round39 §4.4.4): verify_llm_exclusion.py mark_excluded 端到端断言 (delta 模式).

测试聚焦: _run_check / _run_snapshot 纯函数 (mock _get_json + tempfile baseline).
端到端真实请求验证由后端运行时执行 (实战另跑).

负向断言:
- excluded model delta > 0 → FAIL
- excluded model delta == 0 → PASS
- 空 excluded 列表 → PASS
- baseline 缺失 → WARN (不阻断)
- baseline 格式坏 → WARN (不阻断)
- 双 key 形式兼容 (model 名 vs provider/model 组合)
- snapshot 模式: 拉两次 + 保存 JSON
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPTS_PATH = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT_FILE = SCRIPTS_PATH / "verify_llm_exclusion.py"


def _load_module():
    mod_name = "_verify_llm_exclusion_dut"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _args(snapshot=False, baseline_file=None, base="http://x"):
    a = type("Args", (), {})()
    a.snapshot = snapshot
    a.baseline_file = baseline_file or "logs/patrol/llm_exclusion_baseline.json"
    a.base = base
    return a


# ── _run_snapshot 模式 ──

def test_snapshot_saves_baseline_to_file(tmp_path):
    """snapshot 模式: 拉 by_model + excluded, 保存到 baseline_file."""
    mod = _load_module()
    bf = tmp_path / "baseline.json"
    args = _args(snapshot=True, baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"by_model": {"m1": {"calls": 100}, "opencode_zen/m2": {"calls": 50}}},
            {"items": [{"provider": "opencode_zen", "model": "m2"}], "total": 1},
        ]
        rc = mod._run_snapshot(args)
    assert rc == 0
    assert bf.exists()
    saved = json.loads(bf.read_text(encoding="utf-8"))
    assert saved["calls"] == {"m1": 100, "opencode_zen/m2": 50}
    assert len(saved["excluded_items"]) == 1


def test_snapshot_endpoint_unreachable_returns_error(tmp_path):
    """snapshot 模式: 端点不可达 → rc=2."""
    mod = _load_module()
    args = _args(snapshot=True, baseline_file=str(tmp_path / "b.json"))
    with patch.object(mod, "_get_json", side_effect=OSError("refused")):
        rc = mod._run_snapshot(args)
    assert rc == 2


# ── _run_check delta 模式 ──

def test_check_baseline_missing_warns_no_block(tmp_path):
    """baseline 缺失 → WARN (不阻断), 提示先跑 --snapshot."""
    mod = _load_module()
    bf = tmp_path / "nope.json"  # 不创建
    args = _args(baseline_file=str(bf))
    rc, violations = mod._run_check(args)
    assert rc == 0  # WARN 不阻断
    assert any("baseline" in v for v in violations)


def test_check_baseline_malformed_warns_no_block(tmp_path):
    """baseline 格式坏 → WARN (不阻断)."""
    mod = _load_module()
    bf = tmp_path / "bad.json"
    bf.write_text("{not valid json", encoding="utf-8")
    args = _args(baseline_file=str(bf))
    rc, violations = mod._run_check(args)
    assert rc == 0
    assert any("解析失败" in v for v in violations)


def test_check_endpoint_unreachable_returns_error_rc(tmp_path):
    """check 模式: 端点不可达 → rc=2."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({"calls": {}, "excluded_items": []}), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json", side_effect=OSError("refused")):
        rc, violations = mod._run_check(args)
    assert rc == 2


def test_check_excluded_with_zero_delta_passes(tmp_path):
    """正路: excluded model 在 baseline 与当前都是 0 calls → delta=0 → PASS."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({
        "calls": {"deepseek-v4-flash-free": 0},
        "excluded_items": [{"provider": "opencode_zen", "model": "deepseek-v4-flash-free"}],
    }), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"items": [{"provider": "opencode_zen", "model": "deepseek-v4-flash-free"}], "total": 1},
            {"by_model": {"deepseek-v4-flash-free": {"calls": 0}}},
        ]
        rc, violations = mod._run_check(args)
    assert rc == 0
    assert violations == []


def test_check_excluded_with_positive_delta_violates(tmp_path):
    """负向: excluded model 在 baseline 0, 当前 5 → delta=+5 → FAIL."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({
        "calls": {"deepseek-v4-flash-free": 0},
        "excluded_items": [{"provider": "opencode_zen", "model": "deepseek-v4-flash-free"}],
    }), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"items": [{"provider": "opencode_zen", "model": "deepseek-v4-flash-free"}], "total": 1},
            {"by_model": {"deepseek-v4-flash-free": {"calls": 5}}},
        ]
        rc, violations = mod._run_check(args)
    assert rc == 1
    assert len(violations) == 1
    assert "delta=+5" in violations[0]
    assert "opencode_zen" in violations[0]


def test_check_excluded_with_negative_delta_passes(tmp_path):
    """excluded model 当前 0 比 baseline 10 少 (重启清零) → delta=-10 → PASS (只关心增量 > 0)."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({
        "calls": {"m1": 10},
        "excluded_items": [{"provider": "p", "model": "m1"}],
    }), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"items": [{"provider": "p", "model": "m1"}], "total": 1},
            {"by_model": {"m1": {"calls": 0}}},  # 比 baseline 少
        ]
        rc, violations = mod._run_check(args)
    assert rc == 0


def test_check_excluded_combined_key_supported(tmp_path):
    """兼容 by_model 双 key: model 名 vs provider/model 组合."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({
        "calls": {"opencode_zen/m1": 0},  # baseline 用组合 key
        "excluded_items": [{"provider": "opencode_zen", "model": "m1"}],
    }), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"items": [{"provider": "opencode_zen", "model": "m1"}], "total": 1},
            # 当前用 model 名 key
            {"by_model": {"m1": {"calls": 3}}},
        ]
        rc, violations = mod._run_check(args)
    assert rc == 1
    assert "delta=+3" in violations[0]


def test_check_empty_excluded_passes(tmp_path):
    """空 excluded 列表 → PASS (无可校验)."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({"calls": {}, "excluded_items": []}), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"items": [], "total": 0},
            {"by_model": {}},
        ]
        rc, violations = mod._run_check(args)
    assert rc == 0


def test_check_multiple_excluded_partial_violates(tmp_path):
    """多个 excluded: 任一违例即整体 FAIL."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({
        "calls": {"m1": 0, "m2": 0},
        "excluded_items": [
            {"provider": "p1", "model": "m1"},
            {"provider": "p2", "model": "m2"},
        ],
    }), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"items": [
                {"provider": "p1", "model": "m1"},
                {"provider": "p2", "model": "m2"},
            ], "total": 2},
            {"by_model": {"m1": {"calls": 0}, "m2": {"calls": 1}}},
        ]
        rc, violations = mod._run_check(args)
    assert rc == 1
    assert len(violations) == 1
    assert "p2:m2" in violations[0]


def test_check_excluded_missing_provider_or_model_skipped(tmp_path):
    """excluded item 缺字段 → 跳过, 不算校验."""
    mod = _load_module()
    bf = tmp_path / "b.json"
    bf.write_text(json.dumps({
        "calls": {"m1": 0},
        "excluded_items": [
            {"provider": "", "model": "m1"},
            {"provider": "p1", "model": ""},
            {"provider": "p1", "model": "m1"},  # 正常
        ],
    }), encoding="utf-8")
    args = _args(baseline_file=str(bf))
    with patch.object(mod, "_get_json") as mock_get:
        mock_get.side_effect = [
            {"items": [
                {"provider": "", "model": "m1"},
                {"provider": "p1", "model": ""},
                {"provider": "p1", "model": "m1"},
            ], "total": 3},
            {"by_model": {"m1": {"calls": 0}}},
        ]
        rc, violations = mod._run_check(args)
    assert rc == 0
