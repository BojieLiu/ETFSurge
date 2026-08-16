"""round24 R24: 关联度/冗余控制缺口——近替代品双路检测 + 无价格对告警 + 组合级分散约束。

问题（round24 §12.1 R24 实证，design 570）：
- 防御方案三重持有大盘宽基（510300+159338+510050≈31%）未告警——仅 pairwise 且依赖
  K 线相关系数，降级盲时 r=None 静默跳过；
- 主题级「同主题不同发行商」冗余全方案未抓：588170+588200（科创半导体）、
  513120+159570（港股药）、512880+513090（券商 A/H）——r<0.9 或价格缺失时不约束；
- 组合级分散缺口：3 只大盘各自 pairwise 受限仍集体冗余可过。

修复（纯函数，engine 无 I/O）：
- `near_substitute_pairs`：独立于相关系数的「同主题近替代品」检测（名称/行业/tracked_index
  语义族）——即便 r<0.9 或价格缺失也告警；
- `portfolio_concentration_check`：组合平均 pairwise r > 0.8 且标的 ≥3 → concentration 告警；
- `enforce_max_correlation` 集成：近替代品对 r=None → unevaluated 告警（非静默跳过）；
  强制锚（MANDATORY_CODES）仍豁免削减（R2 不变式）。
"""

import pytest

from app.engine.allocation_engine import (
    enforce_max_correlation,
    near_substitute_pairs,
    portfolio_concentration_check,
    MANDATORY_CODES,
)


def _alloc(symbol, name, weight, layer="satellite", factor_score=0.0, tracked_index=""):
    return {
        "symbol": symbol, "name": name, "weight": weight,
        "layer": layer, "factor_score": factor_score, "tracked_index": tracked_index,
    }


class TestNearSubstitutePairs:
    """R24②: 近替代品双路检测（同主题不同发行商，独立于 K 线相关系数）。"""

    def test_semiconductor_pair_detected(self):
        """588170 科创半导体 + 588200 科创芯片 → near_substitute（科创族）。"""
        allocs = [
            _alloc("588170", "科创半导体ETF", 0.15, "satellite"),
            _alloc("588200", "科创芯片ETF", 0.15, "satellite"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        p = pairs[0]
        assert p["type"] == "near_substitute"
        assert set(p["pair"]) == {"588170", "588200"}
        assert p["combined_weight"] == pytest.approx(0.30, abs=1e-6)

    def test_hk_biotech_pair_detected(self):
        """513120 港股创新药 + 159570 港股通创新药 → near_substitute（医药族）。"""
        allocs = [
            _alloc("513120", "港股创新药ETF", 0.12, "satellite"),
            _alloc("159570", "港股通创新药ETF", 0.10, "satellite"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        assert pairs[0]["family"] == "医药生物"

    def test_broker_pair_detected(self):
        """512880 证券 + 513090 香港证券 → near_substitute（券商族）。"""
        allocs = [
            _alloc("512880", "证券ETF", 0.15, "satellite"),
            _alloc("513090", "香港证券ETF", 0.10, "satellite"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        assert pairs[0]["family"] == "券商"

    def test_large_cap_wide_basis_overlap_detected(self):
        """510300 沪深300 + 510050 上证50 → near_substitute（大盘宽基族，R24③）。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.20, "core"),
            _alloc("510050", "上证50ETF", 0.10, "core"),
        ]
        pairs = near_substitute_pairs(allocs)
        assert len(pairs) == 1
        assert pairs[0]["family"] == "大盘宽基"

    def test_unrelated_pairs_not_flagged(self):
        """黄金 518880 + 科创 588200 → 无近替代品（负向：误报 → FAIL）。"""
        allocs = [
            _alloc("518880", "黄金ETF", 0.10, "defense"),
            _alloc("588200", "科创芯片ETF", 0.10, "satellite"),
        ]
        assert near_substitute_pairs(allocs) == []

    def test_cash_and_self_not_flagged(self):
        allocs = [
            _alloc("CASH", "现金", 0.05, "cash"),
            _alloc("510300", "沪深300ETF", 0.20, "core"),
        ]
        assert near_substitute_pairs(allocs) == []


class TestPortfolioConcentrationCheck:
    """R24⑥: 组合级分散约束——平均 pairwise r 过高且标的够多 → concentration。"""

    def test_three_large_caps_collectively_redundant(self):
        """510300+159338+510050 两两 r≈0.98 → 组合平均 >0.8 → concentration 告警。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.15, "core"),
            _alloc("159338", "中证A500ETF", 0.10, "core"),
            _alloc("510050", "上证50ETF", 0.06, "core"),
        ]
        matrix = {
            ("510300", "159338"): 0.983, ("159338", "510050"): 0.939,
            ("510300", "510050"): 0.912,
        }
        out = portfolio_concentration_check(allocs, matrix)
        assert out is not None
        assert out["type"] == "concentration"
        assert out["avg_correlation"] > 0.8
        assert len(out["symbols"]) == 3

    def test_diversified_portfolio_no_concentration(self):
        """分散组合（黄金/科创/宽基，r 均低）→ 无告警（负向）。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.20, "core"),
            _alloc("518880", "黄金ETF", 0.10, "defense"),
            _alloc("588200", "科创芯片ETF", 0.10, "satellite"),
        ]
        matrix = {
            ("510300", "518880"): 0.1, ("518880", "588200"): 0.05,
            ("510300", "588200"): 0.4,
        }
        assert portfolio_concentration_check(allocs, matrix) is None

    def test_fewer_than_three_no_concentration(self):
        allocs = [
            _alloc("510300", "沪深300ETF", 0.30, "core"),
            _alloc("159338", "中证A500ETF", 0.20, "core"),
        ]
        matrix = {("510300", "159338"): 0.983}
        assert portfolio_concentration_check(allocs, matrix) is None


class TestEnforceMaxCorrelationR24:
    """R24 集成：近替代品无价格对告警 + 强制锚豁免不变式。"""

    def test_near_substitute_no_price_emits_unevaluated(self):
        """同主题近替代品但 r=None（价格缺失/降级盲）→ unevaluated 告警，非静默跳过。

        round25 R41-a: 近替代品检测已从 enforce_max_correlation 解耦为独立层
        apply_near_substitute_warnings（无条件执行，不依赖 corr_matrix）——本测试改测
        该独立层（enforce 内不再包裹近替代品）。
        """
        from app.engine.allocation_engine import apply_near_substitute_warnings
        allocs = [
            _alloc("588170", "科创半导体ETF", 0.15, "satellite"),
            _alloc("588200", "科创芯片ETF", 0.15, "satellite"),
            _alloc("510300", "沪深300ETF", 0.30, "core"),
        ]
        strat = {"id": "balanced", "allocations": [dict(a) for a in allocs]}
        # 矩阵只有 588170↔588200 缺失（r=None），其余对不存在
        matrix = {}
        out = apply_near_substitute_warnings([strat], matrix)
        warnings = out[0].get("risk_metrics", {}).get("correlation_warnings", [])
        unevaluated = [w for w in warnings if w.get("type") == "unevaluated"]
        assert len(unevaluated) == 1
        assert set(unevaluated[0]["pair"]) == {"588170", "588200"}
        assert "correlation" in unevaluated[0] and unevaluated[0]["correlation"] is None

    def test_mandatory_anchor_never_cut_by_near_substitute(self):
        """强制锚（510300）配近替代品（510050）→ 强制锚不被削减（R2 不变式）。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.25, "core", factor_score=-0.9),
            _alloc("510050", "上证50ETF", 0.15, "core", factor_score=0.5),
        ]
        strat = {"id": "balanced", "allocations": [dict(a) for a in allocs]}
        matrix = {("510300", "510050"): 0.983}
        out = enforce_max_correlation([strat], matrix)
        result = {a["symbol"]: a["weight"] for a in out[0]["allocations"]}
        assert result["510300"] >= 0.05, "强制锚不得被关联度削减击穿 5% 地板"

    def test_concentration_warning_integrated(self):
        """组合级 concentration 告警写入 risk_metrics。"""
        allocs = [
            _alloc("510300", "沪深300ETF", 0.15, "core"),
            _alloc("159338", "中证A500ETF", 0.10, "core"),
            _alloc("510050", "上证50ETF", 0.06, "core"),
        ]
        strat = {"id": "defensive", "allocations": [dict(a) for a in allocs]}
        matrix = {
            ("510300", "159338"): 0.983, ("159338", "510050"): 0.939,
            ("510300", "510050"): 0.912,
        }
        out = enforce_max_correlation([strat], matrix)
        warnings = out[0].get("risk_metrics", {}).get("correlation_warnings", [])
        assert any(w.get("type") == "concentration" for w in warnings)

    def test_normal_low_corr_no_new_warnings(self):
        """正常低相关组合（黄金+科创）→ 无近替代品/无浓度告警（负向：不误报）。"""
        allocs = [
            _alloc("518880", "黄金ETF", 0.10, "defense"),
            _alloc("588200", "科创芯片ETF", 0.10, "satellite"),
        ]
        strat = {"id": "balanced", "allocations": [dict(a) for a in allocs]}
        matrix = {("518880", "588200"): 0.05}
        out = enforce_max_correlation([strat], matrix)
        warnings = out[0].get("risk_metrics", {}).get("correlation_warnings", [])
        assert warnings == []