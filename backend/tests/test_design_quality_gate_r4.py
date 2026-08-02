"""
P1-1 (R4-15) / P1-2 (R4-14): 组合设计方案质量修复。

- M5 宽基语义补判：_is_wide_basis 对 industry 缺失/unknown 的 A100 类宽基
  按名称/指数语义识别（R4-15 验收4「卫星层无宽基」曾因 A100 562000
  industry=unknown 漏网而 FAIL）。
- 卫星 backup 补足不再混入 A100（名称语义兜底）。
- P1-2: 核心层跨方案重叠（剔除公共底仓 510300）≤1 的判定逻辑。

mock 引擎输入，无网络。
"""

from app.engine.allocation_engine import (
    _is_wide_basis,
    allocate,
)


class TestIsWideBasisSemantic:
    def test_industry_field_wins(self):
        """industry=宽基指数 直接判定。"""
        assert _is_wide_basis({"symbol": "510300", "name": "沪深300ETF",
                               "industry": "宽基指数"}) is True

    def test_a100_unknown_industry_semantic_detect(self):
        """R4-15: A100 562000 industry=unknown → 名称含 A100 → 判定为宽基。"""
        c = {"symbol": "562000", "name": "中证A100ETF", "industry": "unknown"}
        assert _is_wide_basis(c) is True

    def test_mid500_family_semantic(self):
        """名称含 中证500 → 宽基（即使 industry 缺失）。"""
        assert _is_wide_basis({"symbol": "510500", "name": "中证500ETF",
                               "industry": "unknown"}) is True
        assert _is_wide_basis({"symbol": "562330", "name": "中证500价值ETF",
                               "industry": "unknown"}) is True

    def test_theme_etf_not_wide(self):
        """主题/行业 ETF 不是宽基。"""
        assert _is_wide_basis({"symbol": "512480", "name": "半导体ETF",
                               "industry": "半导体"}) is False
        assert _is_wide_basis({"symbol": "159869", "name": "游戏ETF",
                               "industry": "unknown"}) is False
        assert _is_wide_basis({"symbol": "512890", "name": "红利低波ETF",
                               "industry": "红利低波"}) is False

    def test_hk_us_etf_not_wide(self):
        """跨境 ETF 非 A 股宽基（卫星层配置跨境合理）。"""
        assert _is_wide_basis({"symbol": "513010", "name": "恒生科技ETF",
                               "industry": "跨境"}) is False
        assert _is_wide_basis({"symbol": "513500", "name": "标普500ETF",
                               "industry": "跨境"}) is False


def _factor_matrix(candidates):
    """与 test_allocation_engine_fixes 相同的因子矩阵构造。"""
    return {
        c["symbol"]: {
            "technical": 0.5, "momentum": 0.5, "valuation": 0.3, "sentiment": 0.2,
        } for c in candidates
    }


class TestM5SatelliteBackupExcludesA100:
    def test_a100_unknown_industry_excluded_from_satellite(self):
        """P1-1: 卫星 backup 补足时 A100（industry=unknown）不得混入卫星层。"""
        candidates = [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "tracked_index": "沪深300", "industry": "宽基指数", "segment": "沪深300"},
            {"symbol": "560600", "name": "中证A500ETF", "layer": "core",
             "tracked_index": "中证A500", "industry": "宽基指数", "segment": "中证A500"},
            {"symbol": "562000", "name": "中证A100ETF", "layer": "core",
             "tracked_index": "中证A100", "industry": "unknown", "segment": "中证A100"},
            {"symbol": "512890", "name": "红利低波ETF", "layer": "core",
             "tracked_index": "红利低波", "industry": "红利低波", "segment": "红利低波"},
            # 卫星只有 1 只主题 ETF → 触发 backup 补足
            {"symbol": "589960", "name": "科创新能源ETF", "layer": "satellite",
             "tracked_index": "科创新能源", "segment": "科创"},
            {"symbol": "159869", "name": "游戏ETF", "layer": "satellite",
             "tracked_index": "游戏", "segment": "游戏"},
            {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
             "tracked_index": "黄金", "segment": "黄金"},
            {"symbol": "511090", "name": "国债ETF", "layer": "defense",
             "tracked_index": "国债", "segment": "国债"},
        ]
        fm = _factor_matrix(candidates)
        strategies = allocate(risk_profile="balanced", regime="range_bound",
                              factor_matrix=fm, candidates=candidates)
        for s in strategies:
            sats = [a for a in s["allocations"] if a.get("layer") == "satellite"]
            for a in sats:
                assert a["symbol"] != "562000", \
                    f"{s['id']} 卫星层混入 A100（562000）: {[x['symbol'] for x in sats]}"
