"""
R5-2-10: 国内宏观/流动性数据管道。

- fetch_lpr: LPR 取最后一行字段映射
- fetch_bond_yields: 中美利差计算
- fetch_cpi_ppi: 今值 nan/日期>3月 → stale=true
- akshare 异常 → None + 1h 失败缓存（二次调用不调源）
- 24h 成功缓存
- build_full_context: market='A' → domestic_macro；market='HK' → 无该段；4 源全失败 → unavailable=true

mock akshare，无网络。
"""
import asyncio
import pandas as pd
import pytest
from unittest.mock import patch

from app.fetchers import macro_fetcher
from app.services import llm_context
from app.services.cache_service import sync_memory_cache


def _rt(fn, timeout=15):
    return fn()


def _clear():
    sync_memory_cache.clear()


# ── fetch_lpr ───────────────────────────────────────────────
def test_lpr_last_row_mapping(monkeypatch):
    _clear()
    df = pd.DataFrame([
        ["2026-07-20", 3.0, 3.5],
        ["2026-07-21", 3.0, 3.45],
    ], columns=["日期", "LPR1Y", "LPR5Y"])

    def _fake_ak():
        return df

    with patch("akshare.macro_china_lpr", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_lpr()
    assert r["lpr_1y"] == 3.0
    assert r["lpr_5y"] == 3.45, "应取最后一行（最新一期）"
    assert r["date"] == "2026-07-21"
    assert r["stale"] is False


# ── fetch_bond_yields ───────────────────────────────────────
def test_bond_yields_spread_calc(monkeypatch):
    _clear()
    df = pd.DataFrame([
        ["2026-07-31", 1.7141, 4.75, 0.454],
    ], columns=["日期", "中国国债收益率10年", "美国国债收益率10年", "中国10年-2年期限利差"])

    def _fake_ak():
        return df

    with patch("akshare.bond_zh_us_rate", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_bond_yields()
    assert r["cn_10y"] == pytest.approx(1.7141)
    assert r["us_10y"] == pytest.approx(4.75)
    # (1.7141 - 4.75) * 100 = -303.59 bp
    assert r["spread_bp"] == pytest.approx(-303.59, abs=0.5), f"利差 {r['spread_bp']}"


# ── fetch_cpi_ppi stale ─────────────────────────────────────
def test_cpi_ppi_stale_when_nan(monkeypatch):
    _clear()
    cpi_df = pd.DataFrame([
        ["2026-07", 100.5, float("nan"), -0.1],
    ], columns=["月份", "全国-价格", "全国-同比增长", "全国-环比增长"])
    ppi_df = pd.DataFrame([
        ["2026-07", 103.5, float("nan")],
    ], columns=["月份", "指数", "当月同比增长"])

    def _fake_cpi():
        return cpi_df

    def _fake_ppi():
        return ppi_df

    with patch("akshare.macro_china_cpi", side_effect=_fake_cpi), \
         patch("akshare.macro_china_ppi", side_effect=_fake_ppi), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_cpi_ppi()
    assert r is not None
    assert r["stale"] is True, "今值 nan → stale=true"
    assert "滞后" in r["note"] or "缺失" in r["note"], f"note 应说明原因: {r['note']}"


def test_cpi_ppi_stale_when_old_date(monkeypatch):
    _clear()
    cpi_df = pd.DataFrame([
        ["2025-09", 100.2, 0.2, -0.1],  # > 3 个月前
    ], columns=["月份", "全国-价格", "全国-同比增长", "全国-环比增长"])
    ppi_df = pd.DataFrame([
        ["2025-09", 102.1, -2.1],
    ], columns=["月份", "指数", "当月同比增长"])

    def _fake_cpi():
        return cpi_df

    def _fake_ppi():
        return ppi_df

    with patch("akshare.macro_china_cpi", side_effect=_fake_cpi), \
         patch("akshare.macro_china_ppi", side_effect=_fake_ppi), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_cpi_ppi()
    assert r["stale"] is True, "日期>3个月 → stale=true"
    assert "2025-09" in r["note"], f"note 应含滞后日期: {r['note']}"


def test_cpi_ppi_real_values_from_wide_tables(monkeypatch):
    """round13 修正：宽表同比接口真实取值（cpi_yoy/ppi_yoy 各自独立，非共用月率）。

    回归守护：旧实现错用 monthly 长表（今值=CPI 月率）导致 cpi_yoy==ppi_yoy 假数据；
    此处 mock 降序宽表（最新行在首行）验证取值正确 + 升降序兼容。
    """
    _clear()
    cpi_df = pd.DataFrame([
        ["2026-07", 100.5, 0.5, -0.1],   # 最新（降序首行）
        ["2026-06", 101.0, 1.0, -0.3],
        ["2025-09", 100.2, 0.2, -0.1],   # 旧数据在后
    ], columns=["月份", "全国-价格", "全国-同比增长", "全国-环比增长"])
    ppi_df = pd.DataFrame([
        ["2026-07", 103.5, 3.5],         # 最新（降序首行）
        ["2026-06", 104.1, 4.1],
    ], columns=["月份", "指数", "当月同比增长"])

    with patch("akshare.macro_china_cpi", side_effect=lambda: cpi_df), \
         patch("akshare.macro_china_ppi", side_effect=lambda: ppi_df), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r = macro_fetcher.fetch_cpi_ppi()
    assert r["cpi_yoy"] == 0.5, f"CPI 同比取最新行: {r}"
    assert r["ppi_yoy"] == 3.5, f"PPI 同比取最新行: {r}"
    assert r["cpi_yoy"] != r["ppi_yoy"], "cpi/ppi 必须独立取值（防月率共用假数据）"
    assert r["date"] == "2026-07"


# ── 失败缓存 / 成功缓存 ────────────────────────────────────
def test_fail_cached_1h_second_call_no_source(monkeypatch):
    """akshare 异常 → None + 1h 失败缓存（二次调用不调源）。"""
    _clear()
    calls = {"n": 0}

    def _fake_ak():
        calls["n"] += 1
        raise RuntimeError("source down")

    with patch("akshare.macro_china_lpr", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        assert macro_fetcher.fetch_lpr() is None
        assert macro_fetcher.fetch_lpr() is None
    assert calls["n"] == 1, f"失败缓存应阻止第二次触源，实际 {calls['n']} 次"


def test_success_cached_24h(monkeypatch):
    """24h 成功缓存——成功结果二次调用不触源。"""
    _clear()
    calls = {"n": 0}
    df = pd.DataFrame([["2026-07-20", 3.0, 3.5]], columns=["日期", "LPR1Y", "LPR5Y"])

    def _fake_ak():
        calls["n"] += 1
        return df

    with patch("akshare.macro_china_lpr", side_effect=_fake_ak), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        r1 = macro_fetcher.fetch_lpr()
        r2 = macro_fetcher.fetch_lpr()
    assert r1 == r2
    assert calls["n"] == 1, "成功结果应命中 24h 缓存"


# ── build_full_context 集成 ─────────────────────────────────
class _FakeHubMin:
    """最小 hub（build_full_context 的其他段全返回空）。"""

    def get_market_regime(self, market="A"):
        return "range_bound"

    def get_market_sentiment(self):
        return {}

    def get_index_realtime(self):
        return []

    async def get_global_indices(self):
        return {}

    def get_sector_momentum(self):
        return []

    def get_hot_plates(self):
        return []

    def get_sector_heat(self):
        return []

    async def get_all_realtime(self):
        return []

    async def get_news(self):
        return []

    def get_news_headlines(self):
        return []

    def get_news_macro(self):
        return []

    async def get_commodities(self):
        return []

    async def get_portfolio(self):
        return []

    async def get_fund_flow(self, sym, timeout=8):
        return {}

    async def get_market_fundamentals(self, symbol):
        return None

    async def get_global_liquidity(self):
        return {}


@pytest.mark.asyncio
async def test_context_a_includes_domestic_macro(monkeypatch):
    """market='A' → context 含 domestic_macro（含 LPR）。"""
    df = pd.DataFrame([["2026-07-20", 3.0, 3.5]], columns=["日期", "LPR1Y", "LPR5Y"])

    def _fake_lpr():
        return df

    with patch("akshare.macro_china_lpr", side_effect=_fake_lpr), \
         patch("akshare.bond_zh_us_rate", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_money_supply", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_cpi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_ppi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_pmi_yearly", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_gdp_yearly", side_effect=RuntimeError("down")), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        ctx = await llm_context.build_full_context(
            _FakeHubMin(), market="A",
            include_regime=False, include_sentiment=False, include_indices=False,
            include_sectors=False, include_news=False, include_portfolio=False,
            include_fund_flow=False, include_commodities=False, include_global_liquidity=False,
        )
    macro = ctx.get("domestic_macro")
    assert macro is not None, "A 股 context 应含 domestic_macro（R5-2-10）"
    assert macro["lpr"]["lpr_1y"] == 3.0
    assert macro["unavailable"] is False


@pytest.mark.asyncio
async def test_context_hk_omits_domestic_macro():
    """market='HK' → 无 domestic_macro 键。"""
    ctx = await llm_context.build_full_context(
        _FakeHubMin(), market="HK",
        include_regime=False, include_sentiment=False, include_indices=False,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False, include_global_liquidity=False,
    )
    assert "domestic_macro" not in ctx, "HK 上下文不应含 domestic_macro"


@pytest.mark.asyncio
async def test_context_all_macro_sources_down_unavailable(monkeypatch):
    """四源全失败 → domestic_macro.unavailable == true（LLM 显式写不可用，不编造）。"""
    _clear()
    with patch("akshare.macro_china_lpr", side_effect=RuntimeError("down")), \
         patch("akshare.bond_zh_us_rate", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_money_supply", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_cpi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_ppi", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_pmi_yearly", side_effect=RuntimeError("down")), \
         patch("akshare.macro_china_gdp_yearly", side_effect=RuntimeError("down")), \
         patch.object(macro_fetcher, "run_in_thread", _rt):
        ctx = await llm_context.build_full_context(
            _FakeHubMin(), market="A",
            include_regime=False, include_sentiment=False, include_indices=False,
            include_sectors=False, include_news=False, include_portfolio=False,
            include_fund_flow=False, include_commodities=False, include_global_liquidity=False,
        )
    assert ctx.get("domestic_macro", {}).get("unavailable") is True, \
        f"四源全失败应 unavailable=true: {ctx.get('domestic_macro')}"


# ── R08 (round58 §1 M7): 北向实时已停更 → 沪深港通日频历史净流入 ─────────────
# ⚠️ 2026-09-28 实测校正（两处方案文档前提被推翻，见实施记录）：
#   ① akshare 1.18.94 `stock_hsgt_hist_em` 的**默认 symbol 就是「北向资金」**，
#      返回列**无「北向/南向」前缀**（日期/当日成交净买额/买入成交额/卖出成交额/
#      历史累计净买额/当日资金流向/…）。方案 §2 P2-3「默认列含北向/南向」不成立，
#      按前缀分组取列会恒 None（R08 曾因此完全失效，运行时验证抓出）。
#   ② 该净额序列**最后可得日 = 2024-08-16**（2761 行中 2264 行有值，其后为 NaN）。
#      方案「近 5 日净流入」不可得 → 实施为「最后可得日 + 停更时长」披露，
#      **超期不返回任何数值**（宁可占位也不给 2 年前的数当当前资金行为）。
# 保留纪律：① 不传 symbol（cp936 mangling 坑）→ 默认参数 + inspect 取口径标签；
# ② 24h 缓存；③ 列口径不识别 → None（不编造）。

_HSGT_DF_COLS = ["日期", "当日成交净买额", "买入成交额", "卖出成交额",
                 "历史累计净买额", "当日资金流向", "沪深300"]


def _hsgt_df(dates=None, net=None):
    """构造 stock_hsgt_hist_em 形状的 df（默认用「今天往前 2 个交易日」= 新鲜）。"""
    import datetime as _dt
    import pandas as pd
    if dates is None:
        today = _dt.date.today()
        dates = [(today - _dt.timedelta(days=i)).isoformat()
                 for i in (2, 1, 0)]
    if net is None:
        net = [8.0e8, 1.2e9, -3.0e8]
    rows = [[d, n, abs(n) / 2, abs(n) / 2, 1.0e11, 1.0, 3900.0]
            for d, n in zip(dates, net, strict=False)]
    return pd.DataFrame(rows, columns=_HSGT_DF_COLS)


def test_r08_hsgt_history_normalized():
    """R08: 新鲜序列归一为 {date, north_net}（south_net 本轮未接=恒 None）。"""
    _clear()
    with patch("akshare.stock_hsgt_hist_em", return_value=_hsgt_df()), \
         patch.object(macro_fetcher, "_hsgt_default_caliber",
                      return_value="CALIBER-SENTINEL"):
        out = macro_fetcher.fetch_hsgt_history(days=3)
    assert out is not None
    assert out["stale"] is False
    assert out["stale_days"] <= macro_fetcher.HSGT_FRESH_DAYS
    assert len(out["rows"]) == 3
    assert out["rows"][-1]["north_net"] == pytest.approx(-3.0e8)
    assert out["rows"][-1]["south_net"] is None
    assert out["cadence"] == "daily-history"
    # 口径标签必须经 _hsgt_default_caliber 程序化取（不写死中文字面量）
    assert out["caliber"] == "CALIBER-SENTINEL"
    _clear()


def test_r08_net_col_preferred_over_buy_minus_sell():
    """R08 负向：净额必须取「当日…净…」列，不得把 净+买入+卖出 相加
    （重复计数，实测 1.2e9 会被算成 1.3e9）。"""
    import pandas as pd
    _clear()
    df = pd.DataFrame([["2026-09-28", 1.2e9, 6.0e8, 5.0e8, 1.0e11, 1.0, 3900.0]],
                      columns=_HSGT_DF_COLS)
    with patch("akshare.stock_hsgt_hist_em", return_value=df):
        out = macro_fetcher.fetch_hsgt_history(days=1)
    assert out["rows"][-1]["north_net"] == pytest.approx(1.2e9), \
        "误把买入/卖出或累计列当日净额"
    _clear()


def test_r08_buy_minus_sell_fallback_when_no_net_col():
    """R08 兼容：源若只剩「累计净」而无「当日净」→ 用 买入额-卖出额 兜底。"""
    import pandas as pd
    import datetime as _dt
    _clear()
    today = _dt.date.today().isoformat()
    df = pd.DataFrame(
        [[today, 6.0e8, 5.0e8, 1.0e11, 1.0, 3900.0]],
        columns=["日期", "买入成交额", "卖出成交额", "历史累计净买额",
                 "当日资金流向", "沪深300"],
    )
    with patch("akshare.stock_hsgt_hist_em", return_value=df):
        out = macro_fetcher.fetch_hsgt_history(days=1)
    assert out["rows"][-1]["north_net"] == pytest.approx(1.0e8), \
        "无当日净列时应回退 买入-卖出，且不得取累计列"
    _clear()


def test_r08_stale_series_returns_no_numbers():
    """R08 核心负向（2026-09-28 实测）：停更序列（最后可得 2024-08-16）必须
    stale=True + rows=[] + 给出 last_available，**不得返回任何净流入数值**。"""
    _clear()
    stale_df = _hsgt_df(dates=["2024-08-14", "2024-08-15", "2024-08-16"],
                        net=[-1.0e6, 2.0e6, -3.0e6])
    with patch("akshare.stock_hsgt_hist_em", return_value=stale_df):
        out = macro_fetcher.fetch_hsgt_history(days=5)
    assert out is not None
    assert out["stale"] is True
    assert out["rows"] == [], "停更序列不得返回数值行"
    assert out["as_of"] is None
    assert out["last_available"] == "2024-08-16"
    assert out["stale_days"] > macro_fetcher.HSGT_FRESH_DAYS
    _clear()


def test_r08_all_nan_rows_returns_none():
    """R08 负向：净额整列 NaN（停更后接口返行但无值）→ None，不得空造行。"""
    import pandas as pd
    _clear()
    nan_df = pd.DataFrame(
        [["2026-09-28", None, None, None, None, None, 3900.0],
         ["2026-09-27", None, None, None, None, None, 3900.0]],
        columns=_HSGT_DF_COLS,
    )
    with patch("akshare.stock_hsgt_hist_em", return_value=nan_df):
        assert macro_fetcher.fetch_hsgt_history(days=5) is None
    _clear()


def test_r08_no_hardcoded_chinese_symbol_argument():
    """R08 负向守卫：调用 akshare 时**不得**传 symbol（cp936 字面量坑）；
    口径标签改由 inspect 读函数签名默认值，源码不落中文 symbol。"""
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(macro_fetcher.fetch_hsgt_history))
    tree = ast.parse(src)
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
        == "stock_hsgt_hist_em"
    ]
    assert calls, "未找到 stock_hsgt_hist_em 调用点（实现被改写？）"
    for node in calls:
        assert not [k for k in node.keywords if k.arg == "symbol"], \
            "stock_hsgt_hist_em 被传了 symbol 参数（cp936 字面量坑）"
        assert not node.args, "stock_hsgt_hist_em 被传了位置参数"
    # 口径标签必须程序化取（inspect.signature），不得写死
    assert "inspect.signature" in inspect.getsource(
        macro_fetcher._hsgt_default_caliber)
    # 单元测试实证：默认口径可程序化解析出（akshare 装了才能跑）
    assert macro_fetcher._hsgt_default_caliber(), \
        "inspect 未能取到默认口径标签（akshare 签名变化？）"


def test_r08_cached_second_call_zero_network():
    """R08: 24h 缓存生效——二次调用零网络（日频数据不得进请求链）。"""
    _clear()
    with patch("akshare.stock_hsgt_hist_em", return_value=_hsgt_df()) as m:
        first = macro_fetcher.fetch_hsgt_history(days=3)
        second = macro_fetcher.fetch_hsgt_history(days=3)
    assert m.call_count == 1, f"日频数据未缓存，触源 {m.call_count} 次"
    assert first == second
    _clear()


def test_r08_source_failure_returns_none():
    """R08 负向：源异常 → None（调用方占位，不编造净流入）。"""
    _clear()
    with patch("akshare.stock_hsgt_hist_em", side_effect=RuntimeError("down")):
        assert macro_fetcher.fetch_hsgt_history(days=5) is None
    _clear()


def test_r08_unknown_column_layout_returns_none():
    """R08 负向：列口径无法识别（未来 akshare 改列名）→ None，不得瞎猜映射。"""
    import pandas as pd
    _clear()
    weird = pd.DataFrame([["2026-09-24", 1.0, 2.0]], columns=["日期", "列A", "列B"])
    with patch("akshare.stock_hsgt_hist_em", return_value=weird):
        assert macro_fetcher.fetch_hsgt_history(days=5) is None
    _clear()


def test_r08_prompt_states_no_realtime_northbound():
    """R08 负向：报告 prompt 必须写明「北向实时自 2024-08 起停止披露」，
    防止 LLM 编造当日北向数据（反幻觉口径纪律）。"""
    from app.analysis.llm import _build_report_prompt
    p = _build_report_prompt(
        indices=[], commodities=[], market_data=[], indicators={},
        news=[], macro_news=[],
        hsgt={"as_of": "2026-09-24", "stale": False,
              "rows": [{"date": "2026-09-24", "north_net": 1.2e9,
                        "south_net": None}]},
    )
    assert "资金行为" in p
    assert "2024-08" in p
    assert "沪深港通日频历史净流入" in p
    # 真实值必须进 prompt（不得只给 caveat 不给数）
    assert "2026-09-24" in p and "+12.00 亿" in p


def test_r08_prompt_stale_shows_stop_date_without_numbers():
    """R08 核心负向：停更时 prompt 只报最后可得日 + 停更时长，**不给数值**。"""
    from app.analysis.llm import _build_report_prompt
    p = _build_report_prompt(
        indices=[], commodities=[], market_data=[], indicators={},
        news=[], macro_news=[],
        hsgt={"as_of": None, "stale": True, "stale_days": 773,
              "last_available": "2024-08-16", "rows": [], "cadence": "daily-history"},
    )
    assert "2024-08-16" in p
    assert "773" in p
    assert "亿" not in p.split("### 资金行为")[1].split("###")[0].split(
        "沪深港通日频净额")[-1], "停更时不得出现任何净流入金额"


def test_r08_hub_method_degrades_to_none(monkeypatch):
    """R08 接线守卫：hub.get_hsgt_flow_history 存在且异常时返回 None。"""
    from app.services.market_data_hub import MarketDataHub
    assert callable(MarketDataHub().get_hsgt_flow_history)
    monkeypatch.setattr(macro_fetcher, "fetch_hsgt_history",
                        lambda days=5: (_ for _ in ()).throw(RuntimeError("boom")))
    assert MarketDataHub().get_hsgt_flow_history(5) is None


def test_r08_router_wires_hsgt_into_prompt():
    """R08 真实调用点：router 必须调 hub 并透传（0 引用=脚手架）。"""
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "app" / "routers" / "analysis.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    called = any(isinstance(n, ast.Attribute) and n.attr == "get_hsgt_flow_history"
                 for n in ast.walk(tree))
    assert called, "router 未调用 hub.get_hsgt_flow_history"
    kw = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_build_report_prompt":
            kw |= {k.arg for k in n.keywords if k.arg}
    assert {"hsgt", "margin_change", "fund_flow"} <= kw, f"资金段未透传: {sorted(kw)}"
