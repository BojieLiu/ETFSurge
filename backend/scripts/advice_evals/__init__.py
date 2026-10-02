"""AI-advisor gold set (round60).

Sits next to, but separate from, ``scripts/evals/``: that harness scores the
agentic tool layer (MCP tools in ``app/agentic/``), this one scores the advisor
Q&A chain (``POST /api/v1/analysis/llm-advice/stream``). The existing five case
types (quote / factor / format / refusal / multi_step) express expectations as
``field_path`` walks, which cannot describe either artefact the advisor
produces — the prompt is one long string with optional sections, and an answer
is free text judged by required/forbidden content. Advisor cases therefore get
their own types and their own scorers, and the agentic suite is left untouched.

Layout:
- goldens/l1_intent.jsonl  intent-routing cases (143, each with source + notes)
- scorers.py               score_intent / score_prompt + diff reports (pure)

Layering (docs/advice-goldset-design.md §3):
- L1 intent   deterministic (pure substring), runs in CI with no I/O
- L2 prompt   deterministic (string assembly), runs in CI with fixture ctx
- L3 answer   non-deterministic (LLM at temperature 0.5), offline with repeats

Case format:
{"id": "B07", "type": "intent", "question": "支撑位跌破要不要减仓", "market": "A",
 "family": "disambig", "source": "contract§3.3", "notes": "technical 胜 allocation",
 "expect": {"intents": ["technical", "allocation"], "primary": "technical"}}

The gold set locks CURRENT behaviour (2026-10-02 decision). Cases whose
``source`` starts with ``gap-`` or a defect id are known capability gaps: the
locked value is what the product does today, not what it should do.

Run: cd backend && python -m pytest tests/test_advice_goldset_l1.py -q
"""