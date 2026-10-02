# -*- coding: utf-8 -*-
"""L1 intent-routing gold set — AI advisor (round60 C0).

Why a data-driven gold set instead of more asserts in ``test_advice_p0a_slots.py``
The existing intent tests (`:132-198`) assert ``classify()`` — the single primary
intent — on24 statements / 22 distinct queries. Two gaps follow from that:

1. ``classify_all()`` (:80-100), the function the router actually calls
   (``analysis.py:661``), had **no** direct assertion on its ordered result. The
   router's ETF-map gate tests ``"product" in intents`` (``analysis.py:727``) and
   the prompt builder branches on the primary, so both halves of that list are
   load-bearing.
2. Zero coverage for english queries, non-A markets, cross-asset pairs,
   portfolio self-reference, symbol comparison, and follow-up anaphora.

The gold set snapshots what the classifier does *today* (2026-10-02 decision:
"lock current behaviour"). Cases tagged ``source="gap-*"`` are known capability
gaps — their locked value is today's behaviour, not the ideal one. Editing an
expectation to make a gap look fixed defeats the purpose; fix the word list and
let the case go red, then update it deliberately.

Design: docs/advice-goldset-design.md §5 (schema) / §6.2 (expectation policy).
Scorer: scripts/advice_evals/scorers.py::score_intent.

Mutation evidence (why this suite is trusted)
----------------------------------------------
Claiming "133 assertions, therefore covered" is worthless on its own, so the set
was validated by mutating ``intent.py`` and checking that the suite notices.
Result: **91 of 99 mutations killed, 8 survived — and all 8 are provably inert.**

Method (throwaway probe, not committed because it rewrites a source file in place):
substitute each word-list entry with a sentinel of the same shape, then re-run
every case in a **fresh subprocess with ``-B``** and clear ``__pycache__``.
Both details matter: rapid rewrites inside one second let a stale
``intent.cpython-*.pyc`` be reused, which reported 9 mutations as survivors that
a clean interpreter kills. An earlier in-process run also disagreed with a
direct check for the same reason (module cache cross-talk). A mutation that does
not apply is worse than no mutation — it looks like coverage — so every
replacement string is asserted to have matched.

The 8 survivors are all *structurally dead* words: a shorter entry in the same
matching pass already subsumes them, so they can never change any outcome.

    价值陷阱 ⊂ 陷阱      支撑位 ⊂ 支撑      压力位 ⊂ 压力      阻力位 ⊂ 阻力
    买点   ⊂ 买(裸词) 卖点 ⊂ 卖(裸词) 买入 ⊂ 买(裸词) 卖出 ⊂ 卖(裸词)

Deleting them is provably behaviour-neutral; see the proposal in
docs/advice-goldset-design.md §13.2.

Five rounds of this loop drove the set from 64 to143 cases. Every round found
either a keyword with no case at all (44 of 88 were untested when the loop
started) or a case whose target word was masked by a second matching word, so
removing it changed nothing. Both failure modes are now structurally prevented:
``test_every_keyword_is_exercised_by_some_case`` blocks the first, and the
"唯一触发词" convention recorded in the K-family notes is what the second round
taught.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis.intent import classify, classify_all
from scripts.advice_evals.scorers import diff_intent, score_intent

GOLDEN_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "advice_evals" / "goldens" / "l1_intent.jsonl"
)

#: Intents the classifier is allowed to return. Anything else means the priority
#: chain was edited without updating the gold set, which must fail loudly.
_KNOWN_INTENTS = {
    "valuation", "product", "risk", "event",
    "rotation", "technical", "allocation", "general",
}


def _load_cases() -> list[dict]:
    cases: list[dict] = []
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            cases.append(json.loads(line))
    return cases


CASES = _load_cases()
CASE_IDS = [c["id"] for c in CASES]


# ── meta-tests: the gold set must stay trustworthy ─────────────────────────


def test_goldset_file_exists_and_has_cases():
    assert GOLDEN_PATH.exists(), f"missing gold set: {GOLDEN_PATH}"
    assert len(CASES) >= 60, f"gold set shrank to {len(CASES)} cases (floor 60)"


def test_case_ids_are_unique():
    dupes = {i for i in CASE_IDS if CASE_IDS.count(i) > 1}
    assert not dupes, f"duplicate case ids: {sorted(dupes)}"


def test_every_case_is_traceable_and_annotated():
    """A case without provenance is unreviewable, so it is a build error.

    This is the check that keeps the gold set from decaying into a pile of
    guesses: ``source`` must say where the expectation came from and ``notes``
    must explain it (AGENTS.md: no conclusion without evidence).
    """
    for case in CASES:
        assert case.get("source"), f"{case['id']}: missing source"
        assert case.get("notes"), f"{case['id']}: missing notes"
        assert case["expect"]["intents"] == sorted(
            case["expect"]["intents"],
            key=lambda i: [
                "valuation", "product", "risk", "event",
                "rotation", "technical", "allocation",
            ].index(i),
        ), f"{case['id']}: expect.intents is not in priority-chain order"


def test_expectations_only_use_known_intents():
    for case in CASES:
        for intent in case["expect"]["intents"]:
            assert intent in _KNOWN_INTENTS, f"{case['id']}: unknown intent {intent!r}"
        assert case["expect"]["primary"] in _KNOWN_INTENTS


def test_all_seven_intents_plus_general_are_covered():
    """Every rung of the priority chain needs at least one positive case.

    Without this, an intent could quietly lose all coverage by a word-list edit
    that stops matching, and nothing would notice.
    """
    covered = {c["expect"]["primary"] for c in CASES}
    missing = _KNOWN_INTENTS - covered
    assert not missing, f"intents with no case where they are primary: {sorted(missing)}"


def test_gap_cases_are_labelled():
    """Capability-gap cases must declare themselves.

    A gap case whose behaviour later gets fixed should be a deliberate edit, and
    the label is what makes that visible in review.
    """
    for case in CASES:
        if not case["source"].startswith("gap-") and not case["source"].startswith("D"):
            continue
        assert "缺口" in case["notes"] or "D8" in case["source"] or "D1" in case["source"], (
            f"{case['id']}: source={case['source']} but notes do not explain the gap"
        )


# ── the gold set itself ───────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_intent_routing_matches_gold(case: dict):
    query = case["question"]
    payload = {"intents": classify_all(query), "primary": classify(query)}
    verdict = score_intent(payload, case["expect"])
    assert verdict == "pass", (
        f"{case['id']} intent regression on {query!r}: "
        f"{diff_intent(payload, case['expect'])} (source={case['source']})"
    )


@pytest.mark.parametrize(
    "query",
    ["哪些板块低估？买哪只ETF？", "支撑位跌破要不要减仓", "风险提示有哪些"],
)
def test_primary_is_head_of_composite_list(query: str):
    """``classify`` must stay consistent with ``classify_all``.

    The two are used together in the router (primary drives the prompt branch,
    the full list drives the ETF-map gate). If they drift, one of them is stale.
    """
    intents = classify_all(query)
    assert classify(query) == (intents[0] if intents else "general")


def test_composite_cases_exist_so_the_list_is_actually_exercised():
    """Guard against a gold set that only ever locks single-intent results.

    A list assertion over a one-element list cannot detect an ordering or
    completeness regression, which is the whole reason C0 exists.
    """
    composite = [c for c in CASES if len(c["expect"]["intents"]) > 1]
    assert len(composite) >= 8, f"only {len(composite)} composite cases; need >= 8"
    empty = [c for c in CASES if not c["expect"]["intents"]]
    assert len(empty) >= 8, f"only {len(empty)} general/no-hit cases; need >= 8"


def test_every_keyword_is_exercised_by_some_case():
    """Every entry of every word list must appear in at least one gold query.

    Mutation testing found this gap three times over: deleting ``pb``, ``ROE`` or
    ``市净率`` from ``_VALUATION_KWS`` left all80 cases green, i.e. those keywords
    shipped untested. Enumerating keywords by hand does not scale — the next
    person to add one will forget. This test makes the gold set self-maintaining:
    a keyword added without a case fails the build instead of shipping blind.

    ASCII keywords match case-insensitively, because ``PE``/``pe`` and
    ``PB``/``pb`` are listed as separate entries but are one keyword to a reader.
    """
    from app.analysis import intent as intent_mod

    word_lists = {
        "valuation": intent_mod._VALUATION_KWS,
        "product": intent_mod._PRODUCT_PHRASES,
        "risk": intent_mod._RISK_PRIMARY,
        "risk_aux": intent_mod._RISK_AUX_NEED,
        "event": intent_mod._EVENT_KWS,
        "rotation": intent_mod._ROTATION_KWS,
        "technical": intent_mod._TECHNICAL_KWS,
        "technical_retrace": intent_mod._TECHNICAL_RETRACE_KWS,
        "allocation": intent_mod._ALLOCATION_KWS,
        "allocation_bare": intent_mod._ALLOCATION_BARE,
    }
    queries = [c["question"].lower() for c in CASES]
    unexercised: list[str] = []
    for list_name, keywords in word_lists.items():
        for kw in keywords:
            needle = kw.lower()
            if not any(needle in q for q in queries):
                unexercised.append(f"{list_name}:{kw}")
    assert not unexercised, (
        "keywords added to intent.py but never exercised by a gold case (ship blind): "
        + ", ".join(sorted(unexercised))
    )


def test_literal_only_rules_each_have_a_case():
    """The non-keyword rules in ``intent.py`` need coverage too.

    ``风险``+aux, ``防御``+调仓 and ``安全垫`` are conjunctions and lone literals,
    so they sit outside every word list. Mutation testing showed deleting the
    ``安全垫`` or ``防御`` rules kept the suite green; these three cases pin them
    (B12 the negative, B19 the positive conjunction, B18 the lone literal).
    """
    by_id = {c["id"]: c["question"] for c in CASES}
    assert "风险提示有哪些" in by_id.values(), "B12 missing: 风险提示 must not trigger risk"
    assert "防御板块要减仓吗" in by_id.values(), "B19 missing: 防御+减仓 must trigger risk"
    assert "安全垫够用吗" in by_id.values(), "B18 missing: 安全垫 must trigger risk"