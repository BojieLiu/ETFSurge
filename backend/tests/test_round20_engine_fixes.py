"""
round20 (docs/archived/round20-container-acceptance-diagnosis.md) 引擎层修正测试。

TDD 顺序说明：P2-6 / P1-1 / P2-5 / P1-2 / P1-3·P1-6 的实现代码因子代理不可用
由主代理先行落地，本文件为回归固化（实现先行、测试补锁）；P0-1/P0-3/P0-5/P1-8
等项严格遵循「先写失败单测 → 实现 → 补单测」流程（见 test_round20_timeline.py 等）。

覆盖：
- P2-6 plan A: 跨方案重叠惩罚按层拆分——进攻层卫星不被防御资产污染；
- P1-1: enforce_max_correlation——高相关对（r>=0.9）合计权重削减 + 低因子分一方被削 + 报告标注；
- P2-5: check_structure_reasonableness——负信号防御层提示 / 防御层 median_r 高却称低相关 / 进攻现金>20% 告警；
- P1-2: rationale._layer_phrase——correlation_median<0.3 时必含「低相关」措辞；
- P1-3·P1-6: signal.generate_signal——KDJ.J>100 / RSI>80 超买钝化不得给 BUY；
  RSI<30 超卖不得盲目给 decrease（不因超卖加分到反向）。

纯函数测试，无 I/O。
"""

from app.engine.allocation_engine import (
    allocate,
    enforce_max_correlation,
    check_structure_reasonableness,
)
from app.engine.rationale import build_rationale
from app.analysis.signal import generate_signal


def _factor_matrix(candidates):
    return {c["symbol"]: {"technical": 0.5, "momentum": 0.5,
                          "valuation": 0.5, "sentiment": 0.5}
            for c in candidates}


def _base_candidates():
    """含强制标的 + 核心 + 卫星 + 防御（与 test_allocation_engine_fixes 同构）。"""
    return [
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
        {"symbol": "159338", "name": "中证A500ETF", "layer": "core",
         "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
        {"symbol": "588000", "name": "科创50ETF", "layer": "core",
         "tracked_index": "科创50", "industry": "宽基指数", "segment": "科创"},
        {"symbol": "159915", "name": "创业板ETF", "layer": "core",
         "tracked_index": "创业板指", "industry": "宽基指数", "segment": "创业板"},
        {"symbol": "510050", "name": "上证50ETF", "layer": "core",
         "tracked_index": "上证50", "industry": "宽基指数", "segment": "上证50"},
        {"symbol": "512480", "name": "半导体ETF", "layer": "satellite",
         "tracked_index": "半导体", "segment": "半导体"},
        {"symbol": "515030", "name": "新能源ETF", "layer": "satellite",
         "tracked_index": "新能源", "segment": "新能源"},
        {"symbol": "512010", "name": "医药ETF", "layer": "satellite",
         "tracked_index": "医药", "segment": "医药"},
        {"symbol": "512880", "name": "证券ETF", "layer": "satellite",
         "tracked_index": "证券", "segment": "证券"},
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
         "tracked_index": "黄金", "segment": "黄金"},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "tracked_index": "国债", "segment": "国债"},
    ]


# ─── P2-6 plan A: 每层独立重叠惩罚 ────────────────────────────────

class TestP2_6PerLayerOverlapPenalty:
    def test_aggressive_satellite_not_polluted_by_defense_symbols(self):
        """P2-6 (round20 §6 P2-6): 进攻层卫星候选不得因防御层已选而被惩罚剔除。

        旧逻辑用单一 _used_symbols_for_overlap：防御层先选 518880/511090 后，
        进攻层卫星同符号会被惩罚 → 卫星不足 4 只、现金虚高。
        验收：aggressive 卫星层 >= 2 只（候选充足时），且与防御层共享符号不受影响。
        """
        cands = _base_candidates()
        strategies = allocate(risk_profile="aggressive", regime="range_bound",
                              factor_matrix=_factor_matrix(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "aggressive":
                continue
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            # 卫星候选 4 只（512480/515030/512010/512880）充足 → 至少选出 2 只
            assert len(sat) >= 2, f"aggressive 卫星层仅 {len(sat)} 只（<2），疑似被防御层符号污染"
            non_cash = sum(a.get("weight", 0) for a in s["allocations"]
                           if a.get("symbol") != "CASH")
            assert non_cash >= 0.7, f"aggressive 非现金权重 {non_cash:.2f} < 0.70（现金虚高）"

    def test_same_symbol_ok_across_layers(self):
        """同一符号同时出现在卫星/防御层候选时，层间互不惩罚（plan A 核心）。"""
        cands = _base_candidates()
        # 加入一只"跨层"标的：既作卫星主题、又作防御候选（模拟 511090 被防御先选）
        cands.append({"symbol": "513100", "name": "纳指ETF", "layer": "satellite",
                      "tracked_index": "纳指", "segment": "纳指"})
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=_factor_matrix(cands), candidates=cands)
        for s in strategies:
            if s["id"] != "balanced":
                continue
            def_ = [a for a in s["allocations"] if a.get("layer") == "defense"]
            assert len(def_) >= 1, "防御层应保留黄金/国债候选（不被卫星惩罚）"


# ─── P1-1: 高相关对权重约束 ───────────────────────────────────────

class TestP1_1MaxCorrelation:
    def _mk_strategy(self, allocs):
        return [{"id": "balanced", "allocations": allocs}]

    def test_high_corr_pair_reduced(self):
        """P1-1: r=0.95 的一对（非强制锚）合计权重 0.45 超阈值 → 削到 <=0.25，削低因子分一方。

        注：用非强制锚代码（半导体 512480 / 芯片 512760）以隔离「强制锚豁免」逻辑（见 R2）。
        """
        allocs = [
            {"symbol": "512480", "name": "半导体", "layer": "satellite",
             "weight": 0.25, "factor_score": 0.8, "factor_breakdown": {}},
            {"symbol": "512760", "name": "芯片", "layer": "satellite",
             "weight": 0.20, "factor_score": 0.4, "factor_breakdown": {}},
            {"symbol": "518880", "name": "黄金", "layer": "defense",
             "weight": 0.15, "factor_score": 0.6, "factor_breakdown": {}},
            {"symbol": "CASH", "weight": 0.40},
        ]
        matrix = {("512480", "512760"): 0.95}
        strategies = enforce_max_correlation(self._mk_strategy(allocs), matrix,
                                             threshold=0.9, max_combined_weight=0.25)
        s = strategies[0]
        pair = {a["symbol"]: a["weight"] for a in s["allocations"]
                if a["symbol"] in ("512480", "512760")}
        # 合计 <= 阈值（0.25）
        assert pair["512480"] + pair["512760"] <= 0.25 + 1e-9
        # 低因子分一方（512760, fs=0.4）被削减
        assert pair["512760"] < 0.20 + 1e-9
        # 报告标注 correlation_warnings
        warnings = s["risk_metrics"]["correlation_warnings"]
        assert len(warnings) == 1
        assert warnings[0]["reduced_symbol"] == "512760"
        assert "关联度提示" in warnings[0]["note"]
        # Σ 权重保持 = 1
        assert abs(sum(a["weight"] for a in s["allocations"] if a["symbol"] != "CASH") - 0.60) < 0.01

    def test_low_corr_pair_untouched(self):
        """r=0.5 < 0.9 → 不动，无 warning。"""
        allocs = [
            {"symbol": "512480", "weight": 0.30, "factor_score": 0.8},
            {"symbol": "512760", "weight": 0.30, "factor_score": 0.6},
            {"symbol": "CASH", "weight": 0.40},
        ]
        matrix = {("512480", "512760"): 0.5}
        s = enforce_max_correlation([{"id": "x", "allocations": allocs}], matrix)[0]
        assert "correlation_warnings" not in s.get("risk_metrics", {})
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        assert weights["512480"] == 0.30


# ─── round24 R2/R24⑤: 强制锚关联度削减豁免 ─────────────────────────

class TestR2MandatoryCorrelationExemption:
    """R2: 强制锚（沪深300/中证A500/黄金/国债）永不被关联度削减击穿 ≥5% 地板。

    design 570 实证：balanced 方案 159338 中证A500（强制锚）被 enforce_max_correlation
    削到 1%，违反 M7「核心单只 ≥5%」。根因是削减未继承 MANDATORY_CODES 豁免。
    """

    def _mk(self, allocs):
        return [{"id": "balanced", "allocations": allocs}]

    def test_both_mandatory_anchors_not_reduced(self):
        """双方强制锚（510300↔159338，r=0.98）合计 0.45 超阈 → 仅标注、不削减，各自 ≥5%。"""
        allocs = [
            {"symbol": "510300", "name": "沪深300", "layer": "core",
             "weight": 0.25, "factor_score": 0.8},
            {"symbol": "159338", "name": "中证A500", "layer": "core",
             "weight": 0.20, "factor_score": -0.96},  # 原 R2 触发方（深负因子分）
            {"symbol": "518880", "name": "黄金", "layer": "defense",
             "weight": 0.15, "factor_score": 0.6},
            {"symbol": "CASH", "weight": 0.40},
        ]
        matrix = {("510300", "159338"): 0.98}
        # 即便 159338 因子分极深负，也不得被削到 1%
        s = enforce_max_correlation(self._mk(allocs), matrix,
                                    threshold=0.9, max_combined_weight=0.25)[0]
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        assert weights["159338"] >= 0.05 - 1e-9, f"强制锚 159338 被削到 {weights['159338']}"
        assert weights["510300"] >= 0.05 - 1e-9
        # 标注存在且不含被削减标的
        warnings = s["risk_metrics"]["correlation_warnings"]
        assert len(warnings) == 1
        assert warnings[0]["reduced_symbol"] is None
        assert "豁免" in warnings[0]["note"]
        # 双方强制锚权重不变
        assert weights["159338"] == 0.20
        assert weights["510300"] == 0.25

    def test_one_mandatory_anchor_kept(self):
        """单方强制锚（510300, r=0.95 与非强制 512480 高相关，合计 0.30）→ 削非强制方，强制方 ≥5%。"""
        allocs = [
            {"symbol": "510300", "name": "沪深300", "layer": "core",
             "weight": 0.10, "factor_score": 0.9},
            {"symbol": "512480", "name": "半导体", "layer": "satellite",
             "weight": 0.20, "factor_score": 0.3},
            {"symbol": "CASH", "weight": 0.70},
        ]
        matrix = {("510300", "512480"): 0.95}
        s = enforce_max_correlation(self._mk(allocs), matrix,
                                    threshold=0.9, max_combined_weight=0.25)[0]
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        # 强制锚不被削减
        assert weights["510300"] == 0.10
        # 非强制方被削到合计 <= 阈值
        assert weights["510300"] + weights["512480"] <= 0.25 + 1e-9
        assert weights["512480"] < 0.20 + 1e-9
        warnings = s["risk_metrics"]["correlation_warnings"]
        assert warnings[0]["reduced_symbol"] == "512480"

    def test_defense_anchor_not_reduced(self):
        """防御强制锚（518880 黄金）与非强制高相关 → 黄金不被削，非强制方被削。"""
        allocs = [
            {"symbol": "518880", "name": "黄金", "layer": "defense",
             "weight": 0.20, "factor_score": 0.7},
            {"symbol": "159985", "name": "豆粕", "layer": "defense",
             "weight": 0.20, "factor_score": 0.2},
            {"symbol": "CASH", "weight": 0.60},
        ]
        matrix = {("518880", "159985"): 0.93}
        s = enforce_max_correlation(self._mk(allocs), matrix,
                                    threshold=0.9, max_combined_weight=0.25)[0]
        weights = {a["symbol"]: a["weight"] for a in s["allocations"]}
        assert weights["518880"] == 0.20          # 强制锚不动
        # 非强制方被削
        assert weights["518880"] + weights["159985"] <= 0.25 + 1e-9


# ─── P2-5: 结构合理性检查 ─────────────────────────────────────────

class TestP2_5StructureChecks:
    def test_negative_signal_defense_gets_note(self):
        """防御层含 factor_score<=-0.5 标的 → rationale 追加「负信号防御标的」提示。"""
        allocs = [
            {"symbol": "159338", "layer": "defense", "factor_score": -0.6,
             "selection_rationale": "防御配置"},
            {"symbol": "CASH", "weight": 0.5},
        ]
        strategies = check_structure_reasonableness(
            [{"id": "defensive", "allocations": allocs}])
        a = strategies[0]["allocations"][0]
        assert "负信号防御标的" in a["selection_rationale"]
        ws = strategies[0]["risk_metrics"]["structure_warnings"]
        assert any(w["type"] == "negative_signal_in_defense" for w in ws)

    def test_defense_high_median_r_gets_note(self):
        """防御层 median_r>=0.35 却称「低相关/避险」→ 追加高相关提示。"""
        allocs = [
            {"symbol": "159915", "layer": "defense", "factor_score": 0.2,
             "selection_rationale": "与权益低相关，避险配置"},
            {"symbol": "CASH", "weight": 0.5},
        ]
        strategies = check_structure_reasonableness(
            [{"id": "defensive", "allocations": allocs}],
            correlation_medians={"159915": 0.55})
        a = strategies[0]["allocations"][0]
        assert "非低相关对冲资产" in a["selection_rationale"]

    def test_aggressive_cash_over_20pct_flagged(self):
        """进攻型现金 >20% → structure_warning（自洽校验）。"""
        allocs = [
            {"symbol": "510300", "layer": "core", "weight": 0.30},
            {"symbol": "512480", "layer": "satellite", "weight": 0.20},
            {"symbol": "CASH", "weight": 0.50},
        ]
        strategies = check_structure_reasonableness(
            [{"id": "aggressive", "allocations": allocs}])
        ws = strategies[0]["risk_metrics"]["structure_warnings"]
        assert any(w["type"] == "aggressive_cash_over_20pct" for w in ws)


# ─── P1-2: 低相关措辞确定性 ───────────────────────────────────────

class TestP1_2DeterministicLowCorrPhrase:
    def test_low_corr_median_yields_low_corr_phrase(self):
        """P1-2: correlation_median=0.2（<0.3）→ rationale 必含「低相关」。"""
        r = build_rationale(
            code="511090",
            layer="defense",
            strategy="defensive",
            meta={"name": "30年国债ETF", "tracked_index": "国债"},
            factor_scores={},
            regime="range_bound",
            industry="国债",
            correlation_median=0.2,
        )
        assert "低相关" in r, f"correlation_median=0.2 应命中低相关措辞，实际: {r}"

    def test_high_corr_median_no_low_corr_phrase(self):
        """median=0.7（>=0.3）→ 不得出现「低相关」措辞。"""
        r = build_rationale(
            code="510300",
            layer="core",
            strategy="balanced",
            meta={"name": "沪深300ETF", "tracked_index": "沪深300"},
            factor_scores={},
            regime="range_bound",
            industry="宽基指数",
            correlation_median=0.7,
        )
        assert "低相关" not in r, f"median=0.7 不应出现低相关措辞，实际: {r}"


# ─── P1-3·P1-6: 超买钝化守卫 ──────────────────────────────────────

class TestP1_3OverboughtGuard:
    def test_kdj_j_over_100_no_buy(self):
        """D-B1: KDJ.J=101.67 超买钝化 → 不得给 BUY。"""
        res = generate_signal({
            "rsi": 60,
            "macd": {"dif": 0.5, "dea": 0.3},
            "kdj": {"k": 80, "d": 70, "j": 101.67},
            "ma": {"ma5": 10, "ma20": 9.5},
        })
        assert res["signal"] != "buy", f"J>100 超买钝化不得 BUY，实际 {res}"
        assert any("超买" in r for r in res["reasons"])

    def test_rsi_over_80_no_buy(self):
        """RSI>80 极端超买 → 不得给 BUY。"""
        res = generate_signal({
            "rsi": 85,
            "macd": {"dif": 0.8, "dea": 0.5},
            "kdj": {"k": 60, "d": 55, "j": 70},
            "ma": {"ma5": 10, "ma20": 9.0},
        })
        assert res["signal"] != "buy", f"RSI>80 不得 BUY，实际 {res}"

    def test_oversold_rsi_not_blind_decrease(self):
        """P1-6: RSI<30 超卖 + 技术面偏多 → 不得盲目给 decrease（方向一致才降）。"""
        res = generate_signal({
            "rsi": 25,
            "macd": {"dif": 0.2, "dea": 0.1},   # 多头
            "kdj": {"k": 20, "d": 25, "j": 18},  # 超卖区
            "ma": {"ma5": 10, "ma20": 9.8},     # 多头排列
        })
        assert res["signal"] != "sell", f"超卖+多头不应判 sell，实际 {res}"


# ─── P1-7 (round20): 引擎 c2_bonus 动态板块奖励 ──────────────────

class TestP1_7DynamicSectorReward:
    def test_strong_sector_etf_rewarded_in_aggressive(self):
        """P1-7: 当日强势板块（医药 +7%）对应 ETF 在 aggressive 卫星层应获动态奖励
        （非 _RISKY_THEMES 静态科技列表）——composite 不被 -0.3 过滤、可入选。

        负向断言（验收）：强势板块 ETF 无奖励且被过滤 → FAIL。
        场景：医药 ETF 估值/情绪数据缺失（valuation=0 → valuation_missing=True →
        c2_bonus 分支生效），强势板块动态奖励 +1.5 使 composite 为正。
        """
        from app.engine.allocation_engine import allocate

        cands = _base_candidates()
        # 加入医药/创新药主题 ETF（非科技，_RISKY_THEMES 不含）
        cands.append({"symbol": "159992", "name": "创新药ETF", "layer": "satellite",
                      "tracked_index": "创新药", "segment": "创新药",
                      "industry": "医药"})
        cands.append({"symbol": "512170", "name": "医疗ETF", "layer": "satellite",
                      "tracked_index": "医疗", "segment": "医疗",
                      "industry": "医药"})
        # 当日强势板块：医药 +7%（涨幅前 3）
        sector_momentum = [
            {"sector_name": "医疗服务", "name": "医疗服务", "change_pct": 7.2},
            {"sector_name": "化学制药", "name": "化学制药", "change_pct": 5.1},
            {"sector_name": "半导体", "name": "半导体", "change_pct": 4.0},
        ]
        # 医药 ETF 估值缺失（valuation=0）→ c2_bonus 分支触发；其余估值正常
        fm = _factor_matrix(cands)
        for sym in ("159992", "512170"):
            fm[sym] = {"technical": 0.5, "momentum": 0.5,
                       "valuation": 0.0, "sentiment": 0.0}
        strategies = allocate(
            risk_profile="aggressive", regime="range_bound",
            factor_matrix=fm, candidates=cands,
            sector_momentum=sector_momentum,
        )
        for s in strategies:
            if s["id"] != "aggressive":
                continue
            sat = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            sat_syms = {a["symbol"] for a in sat}
            # 医药/医疗至少一只入选（强势板块动态奖励，非科技静态列表）
            assert sat_syms & {"159992", "512170"}, (
                f"强势板块（医药+7%）ETF 未入选 aggressive 卫星层（无动态奖励被过滤）: {sat_syms}"
            )
            # 卫星层 ≥2 只（P2-6 配套验收）
            assert len(sat) >= 2, f"aggressive 卫星层仅 {len(sat)} 只"

