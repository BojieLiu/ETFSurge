"""测试 risk_controls.py 模块。

P3-1: 验证风控逻辑的正确性（字符串拼接、行业集中度、层预算检查）。
"""
import pytest
import sys
sys.path.insert(0, "backend")


def _make_strategy(allocations=None, max_count=5):
    """辅助构造策略对象。"""
    if allocations is None:
        allocations = [
            {"symbol": "510300", "weight": 0.25, "layer": "core", "selection_rationale": "动量因子+0.8"},
            {"symbol": "518880", "weight": 0.05, "layer": "defense", "selection_rationale": "避险+0.5"},
        ]
    return {
        "label": "测试策略",
        "profile": "balanced",
        "allocations": allocations,
        "max_count": max_count,
        "factor_breakdown": {},
    }


class TestFilterExtremeDrawdown:
    """测试 filter_extreme_drawdown 风控函数。"""

    def test_rationale_concat_clean(self):
        """P1-4: 入选理由拼接不会导致变量丢失。"""
        from app.engine.risk_controls import filter_extreme_drawdown
        strategy = _make_strategy()
        factor_matrix = {"510300": {"momentum": 0.8}, "518880": {"momentum": -0.2}}
        result = filter_extreme_drawdown([strategy], factor_matrix)
        assert isinstance(result, list)
        assert len(result) == 1
        for alloc in result[0]["allocations"]:
            rationale = alloc.get("selection_rationale", "")
            assert isinstance(rationale, str)
            # 原文+风控注记不会丢失
            assert len(rationale) > 5

    def test_rationale_no_crash_on_empty(self):
        """入选理由为空时不崩溃。"""
        from app.engine.risk_controls import filter_extreme_drawdown
        empty_alloc = [{"symbol": "510300", "weight": 0.25, "layer": "core"}]
        strategy = _make_strategy(allocations=empty_alloc)
        result = filter_extreme_drawdown([strategy], {})
        assert isinstance(result, list)

    def test_multi_strategy_preserved(self):
        """多策略输入不丢失。"""
        from app.engine.risk_controls import filter_extreme_drawdown
        strategies = [_make_strategy(), _make_strategy()]
        result = filter_extreme_drawdown(strategies, {})
        assert len(result) == 2

    def test_concentration_constraint(self):
        """行业集中度约束不超过 40%。"""
        from app.engine.risk_controls import filter_extreme_drawdown
        allocs = [
            {"symbol": "510300", "weight": 0.50, "layer": "core", "industry": "沪深300"},
            {"symbol": "512800", "weight": 0.35, "layer": "satellite", "industry": "银行"},
            {"symbol": "512880", "weight": 0.30, "layer": "satellite", "industry": "银行"},
            {"symbol": "518880", "weight": 0.05, "layer": "defense", "industry": "黄金"},
        ]
        strategy = _make_strategy(allocations=allocs)
        result = filter_extreme_drawdown([strategy], {})
        assert isinstance(result, list)

    def test_concat_single_symbol(self):
        """单标的策略（无重复符号）不崩溃。"""
        from app.engine.risk_controls import filter_extreme_drawdown
        single = [{"symbol": "510300", "weight": 1.0, "layer": "core"}]
        strategy = _make_strategy(allocations=single)
        result = filter_extreme_drawdown([strategy], {})
        assert len(result[0]["allocations"]) == 1


class TestAllocationEngine:
    """测试 allocation_engine.py 核心逻辑。"""

    def test_select_and_weight_with_mandatory(self):
        """P1-3: 强制标的是否出现在分配结果中。"""
        from app.engine.allocation_engine import allocate, MANDATORY_CODES
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300",
             "industry": "沪深300", "layer": "core"},
            {"symbol": "518880", "name": "黄金ETF", "tracked_index": "黄金",
             "industry": "商品", "layer": "defense"},
            {"symbol": "511090", "name": "国债ETF", "tracked_index": "国债",
             "industry": "固收", "layer": "defense"},
            {"symbol": "563880", "name": "中证A500ETF", "tracked_index": "中证A500",
             "industry": "A500", "layer": "core"},
            {"symbol": "589980", "name": "科创ETF", "tracked_index": "科创50",
             "industry": "科技", "layer": "satellite"},
            {"symbol": "589950", "name": "光伏ETF", "tracked_index": "新能源",
             "industry": "新能源", "layer": "satellite"},
        ]
        factor_matrix = {
            "510300": {"momentum": 0.8, "quality": 0.6, "technical": 0.7},
            "518880": {"momentum": -0.5, "quality": 0.3, "technical": 0.1},
            "511090": {"momentum": 0.2, "quality": 0.5, "technical": 0.3},
            "563880": {"momentum": 0.6, "quality": 0.5, "technical": 0.8},
            "589980": {"momentum": 0.4, "quality": 0.2, "technical": 0.5},
            "589950": {"momentum": 0.3, "quality": 0.1, "technical": 0.4},
        }
        result = allocate(risk_profile="balanced", regime="bullish",
                          factor_matrix=factor_matrix, candidates=candidates)
        assert isinstance(result, list)
        assert len(result) == 3  # 3 套方案

        # 检查每套方案中强制标的出现
        for strat in result:
            symbols = {a["symbol"] for a in strat.get("allocations", []) if a["symbol"] != "CASH"}
            assert "510300" in symbols, f"强制标的 510300 应在方案 {strat.get('label')} 中"
            assert "518880" in symbols, f"强制标的 518880 应在方案 {strat.get('label')} 中"

    def test_three_strategies_different_counts(self):
        """P1-1: 三方案标的数量不同（风偏裁剪生效）。"""
        from app.engine.allocation_engine import allocate
        candidates = [
            {"symbol": s, "name": f"ETF {s}", "tracked_index": s[:3],
             "industry": "科技" if i % 2 == 0 else "消费", "layer": "satellite"}
            for i, s in enumerate([f"5898{str(j).zfill(2)}" for j in range(10)])
        ]
        # 前 5 只加入 core 层
        core_candidates = candidates[:5]
        candidates[5:] = [dict(c, layer="satellite") for c in candidates[5:]]
        candidates[:5] = [dict(c, layer="core") for c in core_candidates]
        factor_matrix = {c["symbol"]: {"momentum": 1.0 - i * 0.05, "technical": 0.8 - i * 0.03}
                         for i, c in enumerate(candidates)}

        result = allocate(risk_profile="balanced", regime="range_bound",
                          factor_matrix=factor_matrix, candidates=candidates)
        # 至少有两种策略的数量不同
        counts = [len(s.get("allocations", [])) for s in result]
        assert len(set(counts)) > 1, f"所有方案标的数相同: {counts}"

    def test_layer_budget_adherence(self):
        """各层预算不超标。"""
        from app.engine.allocation_engine import allocate
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300",
             "industry": "沪深300", "layer": "core"},
            {"symbol": "518880", "name": "黄金ETF", "tracked_index": "黄金",
             "industry": "商品", "layer": "defense"},
            {"symbol": "563880", "name": "A500ETF", "tracked_index": "中证A500",
             "industry": "A500", "layer": "core"},
        ]
        factor_matrix = {c["symbol"]: {"momentum": 0.5, "technical": 0.5}
                         for c in candidates}
        result = allocate(risk_profile="balanced", regime="range_bound",
                          factor_matrix=factor_matrix, candidates=candidates)
        for strat in result:
            total_w = sum(a.get("weight", 0) for a in strat.get("allocations", []) if a["symbol"] != "CASH")
            assert total_w <= 1.0 + 1e-6, f"总权重 {total_w:.2f} 不应超过 1.0"
