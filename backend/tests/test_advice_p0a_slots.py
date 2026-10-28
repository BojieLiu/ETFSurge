# -*- coding: utf-8 -*-
"""round10 P0-A: llm-advice 注入槽位契约——_build_advice_stream_prompt 必须消费
build_full_context 注入的全部槽位（market_regime/market_sentiment/market_data/
hot_plates/sector_heat/news/fund_flow），空槽才显式降级。

验收口径（docs/archived/round10-container-rediagnosis.md §10 P0-A）：三市场投顾返回
不再出现「暂无实时指数数据/暂无板块热力数据/市场状态未知」模板；hot_plates /
sector_heat 有数据时要进 prompt。
"""
import pytest

from app.analysis.llm import _build_advice_stream_prompt
from app.analysis.intent import classify, classify_all


def test_prompt_includes_regime_and_sentiment():
    ctx = {
        "market_regime": "range_bound",
        "market_sentiment": {"sentiment_label": "中性", "sentiment_index": 50},
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
    }
    prompt = _build_advice_stream_prompt("当前A股怎么配置", ctx)
    assert "市场状态: range_bound" in prompt
    assert "市场情绪: 中性 (50/100)" in prompt


def test_prompt_includes_hot_plates():
    """hot_plates 注入后 prompt 含「热点板块」段（P0-A 槽位消费）。"""
    ctx = {
        "market_regime": "bullish",
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
        "hot_plates": [
            {"name": "人工智能", "change_pct": 6.2, "reason": "资金流入"},
            {"name": "半导体", "change_pct": 4.8},
        ],
    }
    prompt = _build_advice_stream_prompt("今天有哪些热点", ctx)
    assert "热点板块" in prompt
    assert "人工智能" in prompt
    assert "半导体" in prompt
    assert "+6.20%" in prompt


def test_prompt_includes_sector_heat():
    """sector_heat 注入后 prompt 含「板块热力（涨幅榜）」段。"""
    ctx = {
        "market_regime": "volatile",
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
        "sector_heat": [
            {"name": "CRO/CMO", "change_pct": 10.84},
            {"name": "通信", "change_pct": 3.76},
        ],
    }
    prompt = _build_advice_stream_prompt("板块分析", ctx)
    assert "板块热力" in prompt
    assert "CRO/CMO" in prompt
    assert "10.84%" in prompt


def test_prompt_empty_slots_no_placeholder_text():
    """空槽时不输出「暂无实时指数数据」等占位符——引擎依赖注入数据而非硬编码占位。"""
    ctx = {
        "market_regime": "",
        "market_sentiment": {},
        "market_data": [],
        "news": [],
        "sector_momentum": [],
        "fund_flow": {},
        "hot_plates": [],
        "sector_heat": [],
    }
    prompt = _build_advice_stream_prompt("今天行情如何", ctx)
    assert "暂无实时指数数据" not in prompt
    assert "暂无板块热力" not in prompt
    assert "市场状态未知" not in prompt


# ── P3-G (round10 §10 P3-G): router 注入槽 ⊆ 引擎消费槽 契约 ──────────
# router（llm_advice_stream, analysis.py）通过 build_full_context + 显式写入的
# key 集合，必须覆盖 _build_advice_stream_prompt 消费的全部 key——漏一个即
# 「槽位错配」回归。此测试在源码层断言（只读 import，不调用 LLM）。

def test_router_injected_keys_cover_prompt_consumed_keys():
    """router 注入的 context key 必须 ⊇ prompt 消费的 key（P3-G 契约）。"""
    import ast as _ast
    import re as _re
    from pathlib import Path

    router_src = Path(__file__).resolve().parent.parent / "app" / "routers" / "analysis.py"
    llm_src = Path(__file__).resolve().parent.parent / "app" / "analysis" / "llm" / "reports.py"

    # 收集 llm_advice_stream 中写入 ctx_key 的 key（"user_ctx[\"x\"] = ..." 与 ctx.get）
    _r_text = router_src.read_text(encoding="utf-8")
    injected = set(_re.findall(r'user_ctx\["([a-z_]+)"\]\s*=', _r_text))
    # build_full_context 输出 key（间接注入，保守列出常见槽）
    # round59: index_technical / support_levels 同源于 build_full_context
    # （services/llm_context.py §5b，TechnicalMixin 只读缓存），非 router 显式赋值。
    injected |= {"market_regime", "market_sentiment", "index_realtime",
                 "sector_momentum", "news", "fund_flow", "hot_plates",
                 "sector_heat", "market_snapshot", "market_data",
                 "index_technical", "support_levels"}

    _l_text = llm_src.read_text(encoding="utf-8")
    # 只扫 _build_advice_stream_prompt 函数体（防其他函数 ctx.get 干扰）
    _fn_start = _l_text.index("def _build_advice_stream_prompt(")
    _fn_body = _l_text[_fn_start:]
    # 函数结束 = 下一个顶层 def（行首 def 且缩进为 0）
    _next_def = _fn_body.find("\ndef ", 1)
    if _next_def != -1:
        _fn_body = _fn_body[:_next_def]
    consumed = set(_re.findall(r'ctx\.get\("([a-z_]+)"', _fn_body))

    missing = sorted(consumed - injected)
    assert not missing, f"router 未注入但引擎消费的槽位: {missing}"
    assert "market_data" in injected and "sector_momentum" in injected


# ── L1 v2 意图分类契约（并入自 test_advice_intent_v1.py，F1 baseline 归位）──
# 契约: api-contracts/analysis/advice-valuation.md §2-§3、§10 正反例。
# 优先级: valuation > product > risk > event > rotation > allocation > general；
# classify_all 返回按优先级排好的命中意图（可复合），classify 取首个。

def test_valuation_queries():
    assert classify("现在有哪些板块是指数比较低估的？") == "valuation"
    assert classify("沪深300现在PE分位多少，贵吗？") == "valuation"
    assert classify("这些低估的是不是价值陷阱？") == "valuation"


def test_composite_valuation_wins_over_product():
    # 低估+ETF映射复合：valuation 主路由（sess-1ef0 实证）
    assert classify("哪些板块低估？买哪只ETF？") == "valuation"
    assert classify_all("哪些板块低估？买哪只ETF？") == ["valuation", "product"]


def test_risk_queries():
    assert classify("止损线设哪") == "risk"
    assert classify("回撤太大怎么办") == "risk"


def test_product_queries():
    assert classify("买哪只银行ETF") == "product"
    assert classify("512800现在能买吗") == "product"


def test_negative_cases():
    assert classify("风险提示有哪些") == "general"  # 固定话术不判 risk
    assert classify("买点到了吗") == "allocation"  # 裸买归 allocation
    assert classify("881001怎么看") == "general"  # 裸板块码不判 product
    assert classify("今天天气不错") == "general"


def test_other_intents():
    assert classify("市场风格是成长还是价值？") == "rotation"
    assert classify("降息对组合有什么影响？") == "event"
    assert classify("当前市场怎么调仓？") == "allocation"


# ── round59 R08: technical intent classification ─────────────────────
# 契约: api-contracts/analysis/advice-valuation.md §3.3、§10 正反例。
# 优先级: valuation > product > risk > event > rotation > technical > allocation > general

def test_technical_intent_positive():
    """技术面意图正例：主关键词 + 回撤族（带后缀）"""
    assert classify("这轮A股下跌的支撑位会是怎么样的") == "technical"
    assert classify("回撤到多少支撑") == "technical"
    assert classify("上证均线在哪") == "technical"
    # 技术词胜出，不被 allocation 抢走
    assert classify("支撑位跌破要不要减仓") == "technical"


def test_technical_intent_negative():
    """技术面意图反例：不得误判 technical"""
    # 裸回撤归 risk（risk 优先级更前）
    assert classify("回撤太大怎么办") == "risk"
    assert classify("最大回撤是多少") == "risk"
    # 无技术词归 allocation
    assert classify("买点到了吗") == "allocation"


def test_technical_priority_over_allocation():
    """technical 优先级高于 allocation：复合问技术词胜出"""
    assert classify("支撑位在哪，能不能加仓") == "technical"
    assert classify_all("支撑位在哪，能不能加仓") == ["technical", "allocation"]


def test_technical_priority_under_rotation():
    """technical 优先级低于 rotation：轮动词优先"""
    assert classify("轮动到支撑位") == "rotation"
    assert classify_all("轮动到支撑位") == ["rotation", "technical"]

# ---------------------------------------------------------------------------
# round59 R01(prompt)/R03/R09：技术面段与关键价位表渲染
# 契约: api-contracts/analysis/llm-report-chat.md §5.1-§5.2、advice-valuation.md §6
#
# 病灶（doc M1/M2/M3）：问支撑位 → prompt 无技术面数据 + 板块名全渲染成 "?" +
# 无条件追加「行业轮动分析框架」+ 800 字上限把答案压成一句免责。
# 下列断言全部针对**渲染出的字符串**，不是内部状态。
# ---------------------------------------------------------------------------

def _r59_levels(price=3842.20, fib_reason=None):
    """构造一份方向标注正确的 support_levels（引擎真实产出的形状）。"""
    return {
        "symbol": "000001", "name": "上证指数", "as_of": "2026-09-30",
        "price_now": price,
        "dynamic": [
            {"level": "MA20", "value": 3905.64, "kind": "resist", "basis": "20日均线"},
            {"level": "BOLL下轨", "value": 3821.74, "kind": "support", "basis": "波动率下沿"},
        ],
        "structural": [
            {"level": "近60日低点", "value": 3741.11, "kind": "support", "basis": "前低"},
        ],
        "fib": {
            "s1": 3881.13, "s2": 3854.40, "s3": 3827.66,
            "anchor_low": 3741.11, "anchor_high": 3967.68,
            "anchor_low_index": 68, "anchor_high_index": 114, "k_primary": 3,
            "fib_unavailable_reason": fib_reason,
            "fib_levels": [
                {"level": "回撤 38.2%", "value": 3881.13, "kind": "resist",
                 "basis": "上一轮上涨段 [3741.11, 3967.68] 回撤 38.2%"},
                {"level": "回撤 61.8%", "value": 3827.66, "kind": "support",
                 "basis": "上一轮上涨段 [3741.11, 3967.68] 回撤 61.8%"},
            ],
        },
    }


def _r59_tech_entry(as_of="2026-09-30"):
    return {"symbol": "000001", "name": "上证指数", "as_of": as_of,
            "close": 3842.20, "ma5": 3864.23, "ma10": 3890.23, "ma20": 3905.64,
            "ma60": 3904.04, "boll_upper": 3989.53, "boll_mid": 3905.64,
            "boll_lower": 3821.74, "rsi": 40.35, "kdj_j": 7.59,
            "volume_ratio_5_20": 1.04}


def _r59_ctx(**kw):
    ctx = {"market_regime": "range_bound",
           "market_sentiment": {"sentiment_label": "偏弱", "sentiment_index": 45},
           "market_data": [{"name": "上证指数", "price": 3842.2, "change_pct": -1.67}],
           "technical_intent": True,
           "index_technical": [_r59_tech_entry()],
           "support_levels": {"000001": _r59_levels()},
           "sector_momentum": [{"sector": "半导体", "change_pct": 2.5}],
           "fund_flow": {"total_symbols": 30, "total_net_inflow": 2000,
                         "positive_flow_count": 12, "negative_flow_count": 18}}
    ctx.update(kw)
    return ctx


def _r59_prompt(ctx=None, query="这轮A股下跌的支撑位会是怎么样的？"):
    from app.analysis.llm.reports import _build_advice_stream_prompt
    return _build_advice_stream_prompt(query, ctx if ctx is not None else _r59_ctx())


def test_r59_technical_section_precedes_realtime_quotes():
    """R01：技术面段必须在实时行情之前（实时行情只有现价，回答不了位置问题）。"""
    p = _r59_prompt()
    assert "## 技术面" in p and "## 实时行情" in p
    assert p.index("## 技术面") < p.index("## 实时行情")
    assert "MA20 3905.64" in p and "BOLL下轨 3821.74" in p
    assert "as_of 2026-09-30" in p


def test_r59_missing_as_of_renders_placeholder_not_numbers():
    """负向：缺 as_of -> 占位并禁引用，绝不照样输出裸数值（无法判断多旧）。"""
    p = _r59_prompt(_r59_ctx(index_technical=[_r59_tech_entry(as_of=None)]))
    assert "（数据源暂不可用）" in p
    assert "不得引用" in p
    assert "MA20 3905.64" not in p, "缺 as_of 却仍输出了裸数值"


def test_r59_empty_slot_omits_section_entirely():
    """负向：槽位为空 -> 整段不出现，不得留「暂无技术面数据」后继续编点位。"""
    p = _r59_prompt(_r59_ctx(index_technical=[], support_levels={}))
    assert "## 技术面" not in p
    assert "### 关键价位" not in p
    assert "暂无技术面数据" not in p


def test_r59_key_price_table_separates_support_and_resist():
    """R02b/R09：支撑族与阻力族分行 + 方向标注，两族不得混列。"""
    p = _r59_prompt()
    assert "### 关键价位" in p
    assert "· 支撑位" in p and "· 阻力位" in p
    # 阻力档（3881.13 / 3905.64）必须出现在阻力族标题之后
    resist_at = p.index("· 阻力位")
    assert p.index("3881.13") > resist_at, "回撤 38.2%(现价上方) 被列进支撑族"
    support_at = p.index("· 支撑位")
    assert p.index("3827.66") > support_at, "回撤 61.8%(现价下方) 被列进阻力族"
    assert "触发条件" in p and "失效条件" in p


def test_r59_fib_unavailable_states_reason_and_emits_no_levels():
    """负向：fib_unavailable_reason 非空 -> 说明原因且不输出任何 fib 价位。"""
    lv = _r59_levels()
    lv["fib"] = {"s1": None, "s2": None, "s3": None, "anchor_low": None,
                 "anchor_high": None, "k_primary": None, "fib_levels": [],
                 "fib_unavailable_reason": "no_upleg_brackets_price"}
    p = _r59_prompt(_r59_ctx(support_levels={"000001": lv}))
    assert "Fib 回撤位不可用" in p
    assert "回撤 38.2%" not in p and "回撤 61.8%" not in p


def test_r59_sector_key_renders_name_not_question_mark():
    """R03：market_trends 输出的 key 是 'sector'；旧链只认 sector_name -> 全渲染 '?'。"""
    p = _r59_prompt(_r59_ctx(sector_momentum=[{"sector": "半导体", "change_pct": 2.5},
                                            {"sector": "银行", "change_pct": -0.8}]))
    assert "半导体" in p and "银行" in p
    assert "- ?: " not in p, "板块名仍渲染成 ? 占位"


def test_r59_technical_intent_drops_rotation_framework_and_fund_flow():
    """R09：问支撑位时不得注入轮动框架与资金流（doc M2 的直接病灶）。"""
    p = _r59_prompt()
    assert "行业轮动分析框架" not in p
    assert "### 资金流向" not in p


def test_r59_non_technical_intent_keeps_rotation_and_fund_flow():
    """反向守卫：非 technical 意图必须**仍然**有轮动框架与资金流（防过度收窄）。"""
    p = _r59_prompt(_r59_ctx(technical_intent=False))
    assert "行业轮动分析框架" in p
    assert "### 资金流向" in p
    assert "### 关键价位" not in p


def test_r59_instruction_block_is_last_not_buried_between_data_sections():
    """R11：指令块必须在全部数据段之后（夹在中间会被数据淹没）。"""
    p = _r59_prompt()
    assert p.rindex("请按以下框架回答") > p.index("## 技术面")
    assert p.rindex("请按以下框架回答") > p.index("### 关键价位")
import json
from scripts.advice_evals.scorers import diff_intent, score_intent, diff_prompt, score_prompt

# ── merged from test_advice_goldset_l1.py (round60, R212) ──

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
    ``市净率`` from ``_VALUATION_KWS`` left all 80 cases green, i.e. those keywords
    shipped untested. Enumerating keywords by hand does not scale -- the next
    person to add one will forget. This test makes the gold set self-maintaining:
    a keyword added without a case fails the build instead of shipping blind.

    ASCII keywords match case-insensitively, because ``PE``/``pe`` and
    ``PB``/``pb`` are listed as separate entries but are one keyword to a reader.

    round60 W3: ``_RISK_AUX_NEED`` was removed -- bare ``风险`` became a primary
    keyword, which makes the "风险 + 怎么办/如何应对/怎么控" conjunction redundant.
    The precision it used to buy now comes from the explicit ``_RISK_EXCLUDE``
    table instead, and ``_RISK_EXCLUDE`` is covered by
    test_risk_exclusion_phrasings_stay_general.
    """
    from app.analysis import intent as intent_mod

    word_lists = {
        "valuation": intent_mod._VALUATION_KWS,
        "product": intent_mod._PRODUCT_PHRASES,
        "risk": intent_mod._RISK_PRIMARY,
        "risk_exclude": intent_mod._RISK_EXCLUDE,
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


def test_no_structurally_dead_keywords():
    """No word list entry may be shadowed by a shorter entry in the same group.

    A word is dead when a shorter word in the same matching group is a substring of
    it: any query that matches the long word necessarily matches the short one, so
    the long word can never change an outcome. Eight such words shipped in intent.py
    (价值陷阱, 支撑位, 压力位, 阻力位, 买点, 卖点, 买入, 卖出) and mutation testing had
    to prove it -- they looked load-bearing and were not.

    This test makes the cleanup permanent and cheap, instead of relying on someone
    remembering to re-run a mutation matrix. Direction matters: it is the LONG word
    that dies, so the report names the longer entry.

    Grouping follows which lists are consulted together: allocation matches
    ``_ALLOCATION_KWS`` and, when product has not matched, the bare verbs too.
    """
    from app.analysis import intent as intent_mod

    groups = {
        "valuation": intent_mod._VALUATION_KWS,
        "product": intent_mod._PRODUCT_PHRASES,
        "risk": intent_mod._RISK_PRIMARY,
        "event": intent_mod._EVENT_KWS,
        "rotation": intent_mod._ROTATION_KWS,
        "technical": tuple(intent_mod._TECHNICAL_KWS) + tuple(intent_mod._TECHNICAL_RETRACE_KWS),
        "allocation": tuple(intent_mod._ALLOCATION_KWS) + tuple(intent_mod._ALLOCATION_BARE),
    }
    dead = []
    for group, words in groups.items():
        for longer in words:
            shadowed_by = [s for s in words if s != longer and s in longer]
            if shadowed_by:
                dead.append(f"{group}:{longer} (shadowed by {shadowed_by})")
    assert not dead, (
        "these words can never change a classification -- a shorter entry in the "
        f"same group already matches every query they would: {dead}"
    )


def test_risk_exclusion_phrasings_stay_general():
    """The fixed report boilerplate must not route to risk.

    ``general_analyst.md:3`` tells every answer to include a risks-and-scenarios
    paragraph, so 「风险提示」 style phrasing is product vocabulary, not a user risk
    question. Before round60 W3 this precision was a coincidence: the string
    contained no risk keyword, so the auxiliary-word gate was never consulted.
    If someone later added 「风险提示」 to _RISK_PRIMARY for an unrelated reason,
    every report would have routed to risk silently. The explicit exclusion table
    removes that dependency.
    """
    for query in ("风险提示有哪些", "风险提示和适用场景有哪些", "风险和适用场景"):
        assert classify(query) == "general", (
            f"boilerplate phrasing routed to risk: {query!r}"
        )


def test_bare_risk_word_now_routes_to_risk():
    """The coverage that motivated W3: natural risk phrasings used to miss."""
    for query in ("我的持仓风险有点大", "风险偏高吗", "这只票风险大不大", "风险可控吗"):
        assert classify(query) == "risk", f"bare 风险 still misses: {query!r}"


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

# ── merged from test_advice_goldset_l2.py (round60, R212) ──

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

import json
from pathlib import Path

import pytest

from app.analysis.llm.reports import _build_advice_stream_prompt
from scripts.advice_evals.scorers import diff_prompt, score_prompt

GOLDEN_PATH_L2 = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "advice_evals" / "goldens" / "l2_prompt.jsonl"
)


def _load_cases_l2() -> list[dict]:
    cases: list[dict] = []
    for line in GOLDEN_PATH_L2.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            cases.append(json.loads(line))
    return cases


CASES_L2 = _load_cases_l2()
CASE_IDS_L2 = [c["id"] for c in CASES_L2]


# ── meta-tests ────────────────────────────────────────────────────────────


def test_goldset_file_exists_and_has_cases():
    assert GOLDEN_PATH_L2.exists(), f"missing gold set: {GOLDEN_PATH_L2}"
    assert len(CASES_L2) >= 3, f"gold set has only {len(CASES_L2)} cases"


def test_case_ids_are_unique():
    dupes = {i for i in CASE_IDS_L2 if CASE_IDS_L2.count(i) > 1}
    assert not dupes, f"duplicate case ids: {sorted(dupes)}"


def test_every_case_is_traceable_and_annotated():
    for case in CASES_L2:
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
    with_includes = [c for c in CASES_L2 if c["expect"].get("must_include")]
    with_excludes = [c for c in CASES_L2 if c["expect"].get("must_not_include")]
    assert len(with_includes) >= 3, f"only {len(with_includes)} positive cases"
    assert len(with_excludes) >= 3, f"only {len(with_excludes)} negative cases"


# ── the gold set itself ───────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES_L2, ids=CASE_IDS_L2)
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
    composite = [c for c in CASES_L2 if c["ctx"].get("product_intent") and c["ctx"].get("valuation_intent")]
    assert composite, "no composite valuation+product case pins the flag semantics"


def test_dead_slots_never_reach_the_prompt():
    """Slots the router collects but no prompt builder consumes must stay absent.

    ``market_snapshot`` is written at analysis.py:239-241 and read by nothing;
    ``global_liquidity`` and ``domestic_macro`` are collected at
    llm_context.py:195-226 and consumed by no advice section. Locking their
    absence keeps a future edit from "helpfully" injecting stale or oversized
    context into every answer.
    """
    poisoned = dict(CASES_L2[0]["ctx"])
    poisoned["market_snapshot"] = "SNAPSHOT_SENTINEL"
    poisoned["global_liquidity"] = {"us_10y": 4.1}
    poisoned["domestic_macro"] = {"pmi": 50.1}
    prompt = _build_advice_stream_prompt(CASES_L2[0]["question"], poisoned)
    for sentinel in ("SNAPSHOT_SENTINEL", "4.1", "50.1"):
        assert sentinel not in prompt, f"dead slot leaked into prompt: {sentinel}"