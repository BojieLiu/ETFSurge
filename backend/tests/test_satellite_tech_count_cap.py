"""
O17 (docs/round7-rediagnosis.md §7): 卫星层科创数量上限。

P19 问题: 所有方案卫星层均出现多个科创系标的（design 398: balanced 8 只卫星中
4 只科创，权重合计 14.6% < 配额 15% → 权重裁剪放行）——权重配额不防数量。

约束: 卫星层科创系（_is_tech_theme）标的数量 ≤ 2 只，与现有权重配额
（≤ budget×40%/50%）取更严：先权重裁剪，再数量裁剪（科创按 composite 降序
保留至 ≤2 只），被裁权重回补其余卫星；非科创候选不足时转 CASH。

纯函数测试，无 I/O。
"""

from app.engine.allocation_engine import _select_and_weight, _is_tech_theme


def _fm(cands, scores=None):
    s = scores or {}
    return {c["symbol"]: {
        "technical": s.get(c["symbol"], 0.5),
        "momentum": 0.5,
        "valuation": 0.5,
        "sentiment": 0.5,
    } for c in cands}


def _cand(symbol, name, layer="satellite", tracked_index=None, segment=None):
    return {"symbol": symbol, "name": name, "layer": layer,
            "tracked_index": tracked_index or name, "segment": segment or name}


def _satellites_8_with_4_tech():
    """8 只卫星：4 科创 + 4 非科创（权重 14.6% 场景模拟）。

    注意：4 只科创的 tracked_index 不以「科创」开头（真实指数名，如
    「上证科创板生物医药」），避免 B3 归一化到同一 segment 被提前去重——
    这正是 P19 实测 4 只科创同现的前提。
    """
    tech = [
        _cand("588068", "科创创新药ETF", "satellite", "上证科创板生物医药", "科创创新药"),
        _cand("588150", "科创新能源ETF", "satellite", "中证科创创业50", "科创新能源"),
        _cand("588220", "科创AIETF", "satellite", "上证科创板人工智能", "科创AI"),
        _cand("588200", "科创芯片设计ETF", "satellite", "中证全指半导体", "科创芯片"),
    ]
    non_tech = [
        _cand("515030", "新能源ETF", "satellite", "新能源", "新能源"),
        _cand("512010", "医药ETF", "satellite", "医药", "医药"),
        _cand("512880", "证券ETF", "satellite", "证券", "证券"),
        _cand("512690", "酒ETF", "satellite", "白酒", "白酒"),
    ]
    return tech + non_tech


class TestSatelliteTechCountCap:
    def test_count_capped_at_2_with_weight_reclaim(self):
        """① 8 只卫星含 4 科创（权重 < 配额）→ 数量裁剪至 ≤2、被裁权重回补非科创。"""
        cands = _satellites_8_with_4_tech()
        scores = {c["symbol"]: 1.0 for c in cands}  # 全部同分，4 科创均入选
        results = _select_and_weight(
            cands, _fm(cands, scores), budget=0.5, layer="satellite",
            regime="range_bound", strategy="balanced", max_count=8,
        )
        tech_selected = [r for r in results if _is_tech_theme(r["name"])]
        assert len(tech_selected) <= 2, f"卫星层科创 {len(tech_selected)} 只 > 2（数量裁剪失效）"
        # 权重回补：总权重仍 ≈ budget（不转 CASH，非科创候选充足）
        total_w = round(sum(r.get("weight", 0) for r in results), 4)
        assert total_w >= 0.45, f"裁剪后卫星总权重 {total_w} 偏低（回补失效）"
        # 被裁科创的权重应回补到非科创（非科创数量不变，权重增大）
        non_tech = [r for r in results if not _is_tech_theme(r["name"])]
        assert len(non_tech) == 4, f"非科创卫星 {len(non_tech)} 只（应为 4 原）"
        non_tech_w = sum(r.get("weight", 0) for r in non_tech)
        # 裁剪前 4 只非科创权重 = 4 × (0.5/8) = 0.25；回补后应 > 0.25
        assert non_tech_w > 0.25 + 1e-6, f"非科创权重合计 {non_tech_w}（回补应 > 0.25）"

    def test_weight_cap_still_applies(self):
        """② 数量达标但权重超配额 → 权重裁剪仍生效（取更严交叉用例）。"""
        # 2 只科创（数量 OK）+ 高分 + 仅 2 只低分非科创 → power-law 下科创权重超 50% 配额
        cands = [
            _cand("588220", "科创AIETF", "satellite", "上证科创板人工智能", "科创AI"),
            _cand("588200", "科创芯片ETF", "satellite", "中证全指半导体", "科创芯片"),
            _cand("515030", "新能源ETF", "satellite", "新能源", "新能源"),
            _cand("512010", "医药ETF", "satellite", "医药", "医药"),
        ]
        scores = {"588220": 2.0, "588200": 2.0, "515030": -2.0, "512010": -2.0}
        results = _select_and_weight(
            cands, _fm(cands, scores), budget=0.5, layer="satellite",
            regime="range_bound", strategy="balanced", max_count=8,
        )
        tech_selected = [r for r in results if _is_tech_theme(r["name"])]
        assert len(tech_selected) <= 2
        tech_weight = sum(r.get("weight", 0) for r in tech_selected)
        assert tech_weight <= 0.25 + 1e-9, f"科创权重 {tech_weight} 超配额 0.25（权重裁剪失效）"

    def test_cash_when_no_non_tech_to_reclaim(self):
        """③ 非科创候选不足时被裁权重转 CASH（卫星预算未用满）。"""
        # 4 只全科创（无任何非科创可回补）——tracked_index 各异避免 B3 去重
        tech = [
            _cand("588068", "科创创新药ETF", "satellite", "上证科创板生物医药", "科创创新药"),
            _cand("588150", "科创新能源ETF", "satellite", "中证科创创业50", "科创新能源"),
            _cand("588220", "科创AIETF", "satellite", "上证科创板人工智能", "科创AI"),
            _cand("588200", "科创芯片设计ETF", "satellite", "中证全指半导体", "科创芯片"),
        ]
        scores = {c["symbol"]: 1.0 for c in tech}
        results = _select_and_weight(
            tech, _fm(tech, scores), budget=0.5, layer="satellite",
            regime="range_bound", strategy="balanced", max_count=8,
        )
        tech_selected = [r for r in results if _is_tech_theme(r["name"])]
        assert len(tech_selected) <= 2, f"全科创候选仍选出 {len(tech_selected)} 只"
        total_w = round(sum(r.get("weight", 0) for r in results), 4)
        assert total_w < 0.5, f"无回补对象时权重 {total_w} 仍等于 budget（应转 CASH 收缩）"
        assert total_w > 0, f"全科创被裁后卫星层为空（应保留 ≤2 只）"
