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