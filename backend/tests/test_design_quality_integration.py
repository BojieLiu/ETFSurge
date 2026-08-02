"""
P1-1 (R4-15) / P1-2 (R4-14) 集成验收：候选池含 A500/红利时，三方案核心层
含 A500 + 沪深300、卫星层无宽基、任意两方案核心层重叠（剔除公共底仓）≤1。

与 verify_e2e 的 design-quality 门禁断言同口径（数据源正常时的验收方式）。

mock 候选池（含行业字段），无网络。
"""

from app.engine.allocation_engine import allocate


def _fm(candidates):
    return {c["symbol"]: {"technical": 0.5, "momentum": 0.5,
                          "valuation": 0.3, "sentiment": 0.2}
            for c in candidates}


def _candidate_pool():
    """含 A500/沪深300/红利/A100/上证50/中证500 的 core 层 + 主题/行业卫星层。"""
    core = [
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
        {"symbol": "560600", "name": "中证A500ETF", "layer": "core",
         "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
        {"symbol": "159338", "name": "中证A500ETF泰康", "layer": "core",
         "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
        {"symbol": "562000", "name": "中证A100ETF", "layer": "core",
         "tracked_index": "A100", "industry": "unknown", "segment": "A100"},
        {"symbol": "512890", "name": "红利低波ETF", "layer": "core",
         "tracked_index": "红利低波", "industry": "红利低波", "segment": "红利低波"},
        {"symbol": "515080", "name": "中证红利ETF", "layer": "core",
         "tracked_index": "中证红利", "industry": "中证红利", "segment": "中证红利"},
        {"symbol": "510050", "name": "上证50ETF", "layer": "core",
         "tracked_index": "上证50", "industry": "宽基指数", "segment": "上证50"},
        {"symbol": "510500", "name": "中证500ETF", "layer": "core",
         "tracked_index": "中证500", "industry": "宽基指数", "segment": "中证500"},
        {"symbol": "510880", "name": "红利ETF", "layer": "core",
         "tracked_index": "上证红利", "industry": "红利", "segment": "红利"},
        {"symbol": "563080", "name": "中证A50ETF", "layer": "core",
         "tracked_index": "A50", "industry": "宽基指数", "segment": "A50"},
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
         "tracked_index": "黄金", "industry": "商品", "segment": "黄金"},
        {"symbol": "511090", "name": "国债ETF", "layer": "defense",
         "tracked_index": "国债", "industry": "固收", "segment": "国债"},
    ]
    satellite = [
        {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
         "tracked_index": "半导体", "industry": "半导体", "segment": "半导体"},
        {"symbol": "159869", "name": "游戏ETF", "layer": "satellite",
         "tracked_index": "游戏", "industry": "游戏", "segment": "游戏"},
        {"symbol": "515170", "name": "食品饮料ETF", "layer": "satellite",
         "tracked_index": "食品饮料", "industry": "食品饮料", "segment": "食品饮料"},
        {"symbol": "512880", "name": "证券ETF", "layer": "satellite",
         "tracked_index": "证券", "industry": "证券", "segment": "证券"},
        {"symbol": "515790", "name": "光伏ETF", "layer": "satellite",
         "tracked_index": "光伏", "industry": "光伏", "segment": "光伏"},
        # 卫星层原始候选混入宽基（P1-1 验收4 应排除）
        {"symbol": "588000", "name": "科创50ETF", "layer": "satellite",
         "tracked_index": "科创50", "industry": "宽基指数", "segment": "科创"},
        {"symbol": "159915", "name": "创业板ETF", "layer": "satellite",
         "tracked_index": "创业板", "industry": "宽基指数", "segment": "创业板"},
    ]
    return {"core": core, "satellite": satellite, "defense": [],
            "opportunistic": [], "research": []}


def test_design_quality_integration():
    """P1-1/P1-2: 三方案核心含 A500+沪深300、卫星无宽基、核心重叠≤1。"""
    pool = _candidate_pool()
    flat = pool["core"] + pool["satellite"]
    strategies = allocate(risk_profile="balanced", regime="range_bound",
                          factor_matrix=_fm(flat), candidates=flat)
    assert len(strategies) == 3

    core_syms_list = []
    for s in strategies:
        allocs = s["allocations"]
        core = [a for a in allocs if a.get("layer") == "core"]
        sat = [a for a in allocs if a.get("layer") == "satellite"]
        core_syms = {a["symbol"] for a in core}
        core_syms_list.append(core_syms)

        # P1-1 验收2（用户决策 f84fe5c）: 核心层含宽基锚——「沪深300 或 A500 皆可」
        # 作公共底仓；A500 至少进入一个方案核心层（不再要求每方案同时含两者）
        assert bool(core_syms & {"510300", "560600", "159338"}), \
            f"{s['id']} 核心层缺宽基锚(510300/560600/159338): {sorted(core_syms)}"
        # P1-1 验收4: 卫星层无宽基（A100/中证500/沪深300/科创50/创业板）
        for a in sat:
            assert a["symbol"] not in ("562000", "588000", "159915", "510300"), \
                f"{s['id']} 卫星层混入宽基 {a['symbol']}"
            assert not _is_wide_name(a), f"{s['id']} 卫星层混入宽基 {a['symbol']}"

    # P1-1 验收2 补充（用户决策 f84fe5c）: A500 至少进入一个方案核心层
    assert any(cs & {"560600", "159338"} for cs in core_syms_list), \
        "A500(560600/159338) 未进入任何方案核心层"

    # P1-2: 任意两方案核心层重叠（剔除公共底仓 510300 + 强制标的）≤1
    # 强制标的（MANDATORY_CODES: 510300/560600/518880/511090）允许跨方案重复
    _MANDATORY = {"510300", "560600", "518880", "511090"}
    for i in range(3):
        for j in range(i + 1, 3):
            a = {s for s in core_syms_list[i] if s not in _MANDATORY}
            b = {s for s in core_syms_list[j] if s not in _MANDATORY}
            overlap = a & b
            assert len(overlap) <= 1, \
                f"{strategies[i]['id']} vs {strategies[j]['id']} 核心重叠 {sorted(overlap)}（>1）"


def _is_wide_name(a):
    text = (a.get("name") or "") + (a.get("tracked_index") or "")
    return any(k in text for k in ("A100", "中证500", "沪深300", "上证50", "科创50", "创业板"))
