"""
O24 (docs/round7-rediagnosis.md §7 P24): 入选理由与入选决策的因果链。

P24 问题: rationale 是描述型（行业 → 技术面 → 复合分 → 市场状态 → 层角色模板），
无「为什么选中它而非同类」的归因——因子分排名、层内竞争、预算约束均未进理由。
专业投资者看到「技术面综合评分 +4.638」无法判断该分在候选池的位次、是否因
动量/估值/技术哪个因子主导而入选。

修复: build_rationale 增加 rank_info（rank/total_candidates/dominant_factor）——
「同类候选池排名 N/M，主驱动因子 X」归因段。
"""

from app.engine.rationale import build_rationale
from app.engine.allocation_engine import _dominant_factor


class TestCausalChain:
    def test_rank_info_added(self):
        """rank_info 传入 → rationale 含「候选池排名 N/M」归因段。"""
        rationale = build_rationale(
            code="512480",
            layer="satellite",
            strategy="balanced",
            meta={"name": "半导体ETF"},
            factor_scores={"technical": 0.5, "momentum": 0.8, "valuation": 0.1, "sentiment": -0.2},
            regime="range_bound",
            industry="电子",
            rank_info={"rank": 1, "total_candidates": 12, "dominant_factor": "momentum"},
        )
        assert "候选池排名" in rationale, f"应含排名归因: {rationale}"
        assert "1/12" in rationale
        assert "动量" in rationale, f"应含主驱动因子（动量）: {rationale}"

    def test_no_rank_info_backward_compatible(self):
        """无 rank_info → 不输出归因段（向后兼容）。"""
        rationale = build_rationale(
            code="510300",
            layer="core",
            strategy="balanced",
            meta={"name": "沪深300ETF"},
            factor_scores={},
            regime="range_bound",
            industry="宽基指数",
        )
        assert "候选池排名" not in rationale

    def test_dominant_factor_momentum(self):
        """主因子计算：momentum 加权贡献最大 → 「动量」（中文标签）。"""
        fs = {"technical": 0.3, "momentum": 1.5, "valuation": 0.2, "sentiment": 0.1}
        pw = {"technical": 0.3, "momentum": 0.3, "valuation": 0.2, "sentiment": 0.2}
        assert _dominant_factor(fs, pw) == "动量"

    def test_dominant_factor_none_when_flat(self):
        """全 0 → None（无主因子标注）。"""
        assert _dominant_factor({}, {"technical": 0.3, "momentum": 0.3,
                                     "valuation": 0.2, "sentiment": 0.2}) is None
