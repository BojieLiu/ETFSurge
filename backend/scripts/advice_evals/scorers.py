# -*- coding: utf-8 -*-
"""Rule-track scorers for the AI-advisor gold set (round60 C0).

Pure functions only: no I/O, no network, no LLM. The existing agentic scorers in
``scripts/evals/scorers/rule_scorer.py`` express expectations as ``field_path``
walks, which cannot describe either artefact the advisor produces:

* the prompt is one long string with optional sections (L2), and
* an answer is free text judged by forbidden/required content (L3, later round).

So the advisor gets its own scorers instead of bending ``_resolve_path`` to fit.
Deliberately kept out of ``scripts/evals/`` so the agentic eval suite is untouched.

Design: docs/advice-goldset-design.md §5 (schema) / §10.1 (severity).
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "score_intent",
    "score_prompt",
    "diff_intent",
    "diff_prompt",
]

# A model-supplied price level looks like 3842.20 / 3905.64 — four digits, a dot,
# two decimals. Used by L3 negative cases ("never invent a level"); defined here
# so L2 and L3 agree on what counts as a level.
_LEVEL_RE = re.compile(r"\d{4}\.\d{2}")


def score_intent(payload: dict[str, Any], expect: dict[str, Any]) -> str:
    """Intent case: exact ordered-list match on the composite result.

    ``payload`` is ``{"intents": [...], "primary": "..."}`` as produced by
    ``classify_all`` / ``classify``. Order matters: the router's ETF-map gate
    (analysis.py:727) tests ``"product" in intents`` and the prompt builder keys
    off the primary, so a set comparison would hide ordering regressions.

    Three-valued result, matching ``rule_scorer.py``: pass / fail / error.
    """
    got = payload.get("intents")
    want = expect.get("intents")
    if not isinstance(got, list) or not isinstance(want, list):
        return "error"
    if got != want:
        return "fail"
    want_primary = expect.get("primary")
    if want_primary is not None and payload.get("primary") != want_primary:
        return "fail"
    # primary must be the head of the composite list, or "general" when empty —
    # an internal contradiction in the classifier itself.
    head = got[0] if got else "general"
    if payload.get("primary") != head:
        return "fail"
    return "pass"


def score_prompt(payload: str, expect: dict[str, Any]) -> str:
    """Prompt case: section presence/absence, ordering, and hard substrings.

    Sections are matched by their heading line (``## 市场背景``,
    ``### 关键价位（…）``) rather than by index, so inserting a new section does
    not silently renumber the expectation. ``order`` is checked by first
    occurrence, which is what "this table precedes that one" actually means when
    a section may repeat (the support/resistance tables are per-index).
    """
    if not isinstance(payload, str):
        return "error"
    for section in expect.get("sections_absent", []):
        if section in payload:
            return "fail"
    for section in expect.get("sections_present", []):
        if section not in payload:
            return "fail"
    for needle in expect.get("must_include", []):
        if needle not in payload:
            return "fail"
    for needle in expect.get("must_not_include", []):
        if needle in payload:
            return "fail"
    order = expect.get("order") or []
    positions = []
    for section in order:
        pos = payload.find(section)
        if pos < 0:
            return "fail"
        positions.append(pos)
    if positions != sorted(positions):
        return "fail"
    for word_budget in expect.get("word_budget", []):
        if f"控制 {word_budget} 字以内" not in payload:
            return "fail"
    return "pass"


def diff_intent(payload: dict[str, Any], expect: dict[str, Any]) -> str:
    """Human-readable failure detail for a failing intent case (report aid)."""
    got = payload.get("intents")
    want = expect.get("intents")
    missing = [i for i in (want or []) if i not in (got or [])]
    extra = [i for i in (got or []) if i not in (want or [])]
    order = (got == want) and bool(missing) is False
    return f"want={want} got={got} missing={missing} unexpected={extra} same_set={order}"


def diff_prompt(payload: str, expect: dict[str, Any]) -> str:
    """Human-readable failure detail for a failing prompt case (report aid)."""
    problems = []
    for section in expect.get("sections_present", []):
        if section not in payload:
            problems.append(f"missing section: {section}")
    for section in expect.get("sections_absent", []):
        if section in payload:
            problems.append(f"unexpected section: {section}")
    for needle in expect.get("must_include", []):
        if needle not in payload:
            problems.append(f"missing text: {needle}")
    for needle in expect.get("must_not_include", []):
        if needle in payload:
            problems.append(f"forbidden text: {needle}")
    for budget in expect.get("word_budget", []):
        if f"控制 {budget} 字以内" not in payload:
            problems.append(f"missing word budget: {budget}")
    order = expect.get("order") or []
    positions = [payload.find(s) for s in order]
    if any(p < 0 for p in positions):
        problems.append(f"order: section absent {order} -> {positions}")
    elif positions != sorted(positions):
        problems.append(f"order violated: {list(zip(order, positions))}")
    return "; ".join(problems) or "no detail"