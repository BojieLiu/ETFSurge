"""round27 R48 (R41-c): 近替代品合并留一——防御/平衡/进攻三型统一执行，进攻型不豁免。

问题（round27 R48 / R41-c 未实现）：R41-a/b 只告警不合并，方案仍双持同主题标的
（「芯片+半导体设备」「港股创新药+港股通创新药」）。用户决策：追求集中应优先重仓单只
而非分多个同主题标的，故进攻型不豁免。

修复：`allocation_engine._merge_substitute_family`（纯函数，无 I/O）在 `apply_near_substitute_warnings`
检测之后执行——同族 ≥2 只保留流动性更好/更宽基者、并入权重、移除其余、打 `merged_from`，
并把对应 near_substitute 告警升级为 `status="merged"`、`risk_metrics.merged_substitutes` 标注。
"""

import pytest

from app.engine.allocation_engine import (
    _merge_substitute_family,
    apply_near_substitute_warnings,
)


def _chip_pair():
    return [
        {"symbol": "588200", "name": "科创芯片ETF", "weight": 0.10, "market_cap": 200e9},
        {"symbol": "588170", "name": "科创半导体设备ETF", "weight": 0.08, "market_cap": 50e9},
        {"symbol": "510300", "name": "沪深300ETF", "weight": 0.5, "market_cap": 1500e9},
    ]


def _hk_pharma_pair():
    return [
        {"symbol": "513120", "name": "港股创新药ETF", "weight": 0.07},
        {"symbol": "159570", "name": "港股通创新药ETF", "weight": 0.06},
        {"symbol": "518880", "name": "黄金ETF", "weight": 0.3},
    ]


class TestMergeSubstituteFamily:
    """R48: 同族近替代品合并留一（保留流动性更好者）。"""

    def test_chip_family_keeps_one_and_merges_weight(self):
        """半导体族（588200+588170）只留其一，保留 market_cap 更大者，权重并入。"""
        allocs = _chip_pair()
        merges = _merge_substitute_family(allocs)
        fam = [a for a in allocs if a.get("symbol") in ("588200", "588170")]
        assert len(fam) == 1, "半导体族必须只留其一"
        kept = fam[0]
        assert kept["symbol"] == "588200", "保留流动性更好（market_cap 大）者"
        assert kept["weight"] == pytest.approx(0.18, abs=1e-6), "权重并入保留者"
        assert "588170" in kept["merged_from"]
        assert kept["merged"] is True
        assert len(merges) == 1
        assert merges[0]["family"] == "半导体"
        assert merges[0]["merged_symbols"] == ["588170"]
        assert "已合并留一" in merges[0]["note"]

    def test_hk_pharma_family_keeps_one(self):
        """医药生物族（513120+159570）只留其一。"""
        allocs = _hk_pharma_pair()
        merges = _merge_substitute_family(allocs)
        pharma = [a for a in allocs if a.get("symbol") in ("513120", "159570")]
        assert len(pharma) == 1
        assert len(merges) == 1
        assert merges[0]["family"] == "医药生物"

    def test_single_item_no_merge(self):
        """单只无同族 → 不合并。"""
        allocs = [{"symbol": "510300", "name": "沪深300ETF", "weight": 0.5}]
        merges = _merge_substitute_family(allocs)
        assert merges == []
        assert len(allocs) == 1

    def test_three_profiles_all_merge_no_aggressive_exemption(self):
        """三型均合并留一；负向：进攻型同族双持也必须合并（不豁免）。"""
        base = {
            "defensive": _hk_pharma_pair(),
            "balanced": _chip_pair(),
            "aggressive": [
                {"symbol": "513120", "name": "港股创新药ETF", "weight": 0.09},
                {"symbol": "159570", "name": "港股通创新药ETF", "weight": 0.08},
                {"symbol": "588000", "name": "科创50ETF", "weight": 0.2},
            ],
        }
        for p, allocs in base.items():
            _merge_substitute_family(allocs)
        for p, allocs in base.items():
            pharma = [a for a in allocs if a.get("symbol") in ("513120", "159570")]
            chip = [a for a in allocs if a.get("symbol") in ("588200", "588170")]
            if p == "balanced":
                # balanced 用芯片族：半导体族必须只留其一
                assert len(chip) == 1, f"{p} 半导体族必须只留其一（进攻型不豁免）"
                assert len(pharma) == 0, f"{p} 不含医药族"
            else:
                # defensive / aggressive 用医药族：必须合并留一（进攻型不豁免）
                assert len(pharma) == 1, f"{p} 医药族必须只留其一（进攻型不豁免）"


class TestApplyNearSubstituteWarningsMarksMerged:
    """R48: 告警从「仅提示」升级为「已合并」标注。"""

    def test_warning_upgraded_to_merged_and_risk_metrics(self):
        strategies = [{"id": "balanced", "allocations": _chip_pair()}]
        out = apply_near_substitute_warnings(strategies, {})
        rm = out[0]["risk_metrics"]
        merged = [w for w in rm["correlation_warnings"]
                  if "588200" in w["pair"] and "588170" in w["pair"]]
        assert merged, "近替代品告警必须存在"
        assert merged[0]["status"] == "merged", "告警升级为「已合并」"
        assert "已合并留一" in merged[0]["note"]
        assert rm.get("merged_substitutes"), "merged_substitutes 标注必须存在"
        assert rm["merged_substitutes"][0]["family"] == "半导体"
        # 保留方从 etfs 移除被合并标的
        symbols = {a["symbol"] for a in out[0]["allocations"]}
        assert "588170" not in symbols
        assert "588200" in symbols
