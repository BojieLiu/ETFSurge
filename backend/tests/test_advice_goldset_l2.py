# -*- coding: utf-8 -*-
"""L2 prompt gold set — AI advisor (round60 C2).

The prompt is assembled by a pure function, so every assertion here is exact and
free: no network, no LLM, no fixtures on disk. That makes this layer cheap
enough to be a hard CI gate, and it is the layer where two of the product's real
defects lived:

* D5 — the "no ETF map, do not invent codes" guard was keyed on the valuation
  intent, so a plain product question ("which bank ETF should I buy") got no
  guard at all. That is a licence to fabricate ETF codes, the same failure shape
  as the ``sess-1ef0`` hallucination that this contract was written for.
* D2 / D8 / S8 — cold-cache technical wording, non-A-share scope statements and
  the commodity slot land in C3 and extend this file.

Scorer: scripts/advice_evals/scorers.py::score_prompt.
Design: docs/advice-goldset-design.md §3 (layering) / §5 (schema).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis.llm.reports import _build_advice_stream_prompt
from scripts.advice_evals.scorers import diff_prompt, score_prompt

GOLDEN_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "advice_evals" / "goldens" / "l2_prompt.jsonl"
)


def _load_cases() -> list[dict]:
    cases: list[dict] = []
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            cases.append(json.loads(line))
    return cases


CASES = _load_cases()
CASE_IDS = [c["id"] for c in CASES]


# ── meta-tests ────────────────────────────────────────────────────────────


def test_goldset_file_exists_and_has_cases():
    assert GOLDEN_PATH.exists(), f"missing gold set: {GOLDEN_PATH}"
    assert len(CASES) >= 3, f"gold set has only {len(CASES)} cases"


def test_case_ids_are_unique():
    dupes = {i for i in CASE_IDS if CASE_IDS.count(i) > 1}
    assert not dupes, f"duplicate case ids: {sorted(dupes)}"


def test_every_case_is_traceable_and_annotated():
    for case in CASES:
        assert case.get("source"), f"{case['id']}: missing source"
        assert case.get("notes"), f"{case['id']}: missing notes"
        assert isinstance(case.get("ctx"), dict), f"{case['id']}: ctx must be inline here"
        expect = case["expect"]
        assert expect.get("must_include") or expect.get("must_not_include"), (
            f"{case['id']}: an expectation with neither include nor nor list asserts nothing"
        )


def test_both_polarities_are_present():
    """A suite of only "must include" rows cannot catch over-triggering.

    The D5 fix adds a guard; without a case asserting the guard is *absent* for
    an unrelated question, a later edit could paste it into every prompt.
    """
    with_includes = [c for c in CASES if c["expect"].get("must_include")]
    with_excludes = [c for c in CASES if c["expect"].get("must_not_include")]
    assert len(with_includes) >= 3, f"only {len(with_includes)} positive cases"
    assert len(with_excludes) >= 3, f"only {len(with_excludes)} negative cases"


# ── the gold set itself ───────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_prompt_matches_gold(case: dict):
    prompt = _build_advice_stream_prompt(case["question"], case["ctx"])
    verdict = score_prompt(prompt, case["expect"])
    assert verdict == "pass", (
        f"{case['id']} prompt regression for {case['question']!r} "
        f"(ctx={case['ctx']}): {diff_prompt(prompt, case['expect'])} "
        f"(source={case['source']})"
    )


def test_router_and_prompt_agree_on_product_intent_flag():
    """``product_intent`` must mean what the ETF-map gate already meant.

    The router fills the map with ``if "product" in intents`` (analysis.py:727),
    so a flag computed as ``primary == "product"`` would disagree for composite
    questions like "which sectors are cheap, and which bank ETF should I buy" —
    where valuation wins the priority chain but the product sub-task still runs.
    """
    composite = [c for c in CASES if c["ctx"].get("product_intent") and c["ctx"].get("valuation_intent")]
    assert composite, "no composite valuation+product case pins the flag semantics"


def test_dead_slots_never_reach_the_prompt():
    """Slots the router collects but no prompt builder consumes must stay absent.

    ``market_snapshot`` is written at analysis.py:239-241 and read by nothing;
    ``global_liquidity`` and ``domestic_macro`` are collected at
    llm_context.py:195-226 and consumed by no advice section. Locking their
    absence keeps a future edit from "helpfully" injecting stale or oversized
    context into every answer.
    """
    poisoned = dict(CASES[0]["ctx"])
    poisoned["market_snapshot"] = "SNAPSHOT_SENTINEL"
    poisoned["global_liquidity"] = {"us_10y": 4.1}
    poisoned["domestic_macro"] = {"pmi": 50.1}
    prompt = _build_advice_stream_prompt(CASES[0]["question"], poisoned)
    for sentinel in ("SNAPSHOT_SENTINEL", "4.1", "50.1"):
        assert sentinel not in prompt, f"dead slot leaked into prompt: {sentinel}"