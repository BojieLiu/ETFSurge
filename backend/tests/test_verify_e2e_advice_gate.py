# -*- coding: utf-8 -*-
"""Meta-test for the verify_e2e advice gate (round60 D7).

A gate that cannot fail is not a gate. Before this commit the advice check in
``scripts/verify_e2e.py`` reported PASS on a 45s timeout and on any exception, with
the rationale "the LLM is slow, that is not a template regression" -- so the advice
endpoint could be dead and verify_e2e would still be green.

Testing that required either running the whole verify_e2e suite against a live
backend (too heavy, and it would assert on live market data) or asserting on the
gate's own source. This does the latter, precisely: it walks the AST, finds every
``except`` handler, and fails if any of them calls ``check(...)`` with a literal
``True`` for the advice endpoint. That targets the exact regression (a swallowed
failure) without pinning formatting or the surrounding code.

The one allowance: STORM_SKIP (round36 section 8-C) is the sanctioned way to
distinguish an environment problem from a regression, so it stays available for
other endpoints; this test only forbids turning the advice reachability check into
an unconditional PASS.
"""
from __future__ import annotations

import ast
from pathlib import Path

VERIFY_E2E = (
    Path(__file__).resolve().parents[1] / "scripts" / "verify_e2e.py"
)
ADVICE_LABEL_HINTS = ("llm-advice",)


def _check_calls_under_handlers(tree: ast.AST) -> list[tuple[str | None, ast.AST]]:
    """Every ``check(label, ok, ...)`` call that sits inside an ``except`` block.

    Returns (label_constant_or_None, handler_type_source) pairs so a failure can
    name both the check and the handler type it hides under.
    """
    found: list[tuple[str | None, ast.AST]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        handler_type = ast.unparse(node.type) if node.type else "bare-except"
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            fn = inner.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name != "check":
                continue
            found.append((
                inner.args[0].value if inner.args and isinstance(inner.args[0], ast.Constant)
                else None,
                handler_type,
            ))
    return found


def test_verify_e2e_exists():
    assert VERIFY_E2E.exists(), f"missing gate script: {VERIFY_E2E}"


def test_advice_failure_is_never_reported_as_pass():
    tree = ast.parse(VERIFY_E2E.read_text(encoding="utf-8"))
    offenders = [
        (label, handler)
        for label, handler in _check_calls_under_handlers(tree)
        if label and any(h in str(label) for h in ADVICE_LABEL_HINTS)
    ]
    assert not offenders, (
        "advice checks inside an except handler would fail-open: "
        + "; ".join(f"check({label!r}, ...) under except {handler}" for label, handler in offenders)
    )


def test_advice_endpoint_has_an_explicit_reachability_check():
    """The endpoint must be asserted reachable, with a failure path.

    Text-level but narrow: these two literals are the contract between the retry
    loop and its verdict, and neither can be satisfied by accident.
    """
    src = VERIFY_E2E.read_text(encoding="utf-8")
    assert "llm-advice/stream 端点可达" in src, "advice reachability check is missing"
    assert 'check("llm-advice/stream 端点可达", False' in src, (
        "the reachability check must have a False path, otherwise a dead endpoint "
        "is still green"
    )


def test_advice_check_retries_before_failing():
    """One retry, so a single slow response is not mistaken for a dead endpoint.

    This is the deliberate trade: a bare FAIL would turn routine LLM latency into
    red builds, and the old unconditional PASS made the gate meaningless. One retry
    separates "slow" from "dead" while keeping a real failure visible.
    """
    src = VERIFY_E2E.read_text(encoding="utf-8")
    assert "for _attempt in (1, 2):" in src, (
        "the advice check should retry once before failing (D7)"
    )


def test_old_swallow_is_gone():
    """The exact pre-fix lines, so a revert cannot pass unnoticed."""
    src = VERIFY_E2E.read_text(encoding="utf-8")
    for gone in (
        'check("llm-advice/stream 内容", True, "请求超时',
        'check("llm-advice/stream 内容", True, f"请求异常',
    ):
        assert gone not in src, f"the fail-open advice check is back: {gone!r}"