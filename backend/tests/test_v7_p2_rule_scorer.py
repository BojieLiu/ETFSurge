"""v7 P2: rule_scorer 单测——四 scorer 三态判定 + field_path 解析 + 边界。"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.evals.scorers.rule_scorer import (
    score_case, score_format, score_quote, score_refusal, score_multi_step,
    _resolve_path,
)


class TestResolvePath:
    def test_simple_and_nested(self):
        ok, v = _resolve_path({"data": [{"price": 4.0}]}, "data[0].price")
        assert ok and v == 4.0

    def test_missing_key(self):
        ok, _ = _resolve_path({"data": 1}, "source")
        assert not ok

    def test_out_of_range_index(self):
        ok, _ = _resolve_path({"data": []}, "data[0]")
        assert not ok


class TestScoreQuote:
    def test_present_pass_and_fail(self):
        assert score_quote({"data": 1}, {"field_path": "data", "op": "present"}) == "pass"
        assert score_quote({}, {"field_path": "data", "op": "present"}) == "fail"
        assert score_quote({"data": None}, {"field_path": "data", "op": "present"}) == "fail"

    def test_approx_within_tolerance(self):
        assert score_quote({"price": 4.01}, {"field_path": "price", "op": "approx",
                                             "value": 4.0, "tolerance": 0.01}) == "pass"
        assert score_quote({"price": 4.5}, {"field_path": "price", "op": "approx",
                                            "value": 4.0, "tolerance": 0.01}) == "fail"


class TestScoreFormat:
    def test_envelope_complete_pass(self):
        payload = {"data": 1, "as_of": "t", "source": "s", "degraded": False}
        assert score_format(payload, {}) == "pass"

    def test_missing_field_fail(self):
        payload = {"data": 1, "as_of": "t", "degraded": False}  # 缺 source
        assert score_format(payload, {}) == "fail"

    def test_degraded_true_still_pass(self):
        payload = {"data": None, "as_of": "t", "source": "s", "degraded": True}
        assert score_format(payload, {}) == "pass"


class TestScoreRefusal:
    def test_honest_missing_pass(self):
        payload = {"data": None, "degraded": True, "error": "not found"}
        assert score_refusal(payload, {"must_refuse": True}) == "pass"

    def test_missing_without_degraded_flag_fail(self):
        payload = {"data": None, "degraded": False}
        assert score_refusal(payload, {"must_refuse": True}) == "fail"

    def test_data_present_when_refuse_expected_fail(self):
        payload = {"data": "编造的价格", "degraded": False}
        assert score_refusal(payload, {"must_refuse": True}) == "fail"

    def test_data_present_when_allowed_pass(self):
        payload = {"data": {"price": 4.0}, "degraded": False}
        assert score_refusal(payload, {"must_refuse": False}) == "pass"


class TestScoreMultiStep:
    def test_all_steps_ok_pass(self):
        payload = {"steps": [{"output": {"data": 1}}, {"output": {"data": 2}}]}
        assert score_multi_step(payload, {"min_steps": 2}) == "pass"

    def test_step_error_fail(self):
        payload = {"steps": [{"output": {"data": 1}}, {"error": "timeout"}]}
        assert score_multi_step(payload, {"min_steps": 2}) == "fail"

    def test_empty_steps_error(self):
        assert score_multi_step({"steps": []}, {}) == "error"


class TestDispatch:
    def test_unknown_type_error(self):
        assert score_case("nope", {}, {}) == "error"

    def test_factor_uses_quote_scorer(self):
        assert score_case("factor", {"rsi_14": 55.0},
                          {"field_path": "rsi_14", "op": "present"}) == "pass"
