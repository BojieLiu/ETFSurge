"""round27 R47: 降级态（coarse）结构化字段桶化——etfs[].weight / etfs[].factor_score
与 data_precision（coarse/bucket）保持一致；exact 态原值不变。

问题（round27 R47 / R36 残余）：`data_precision` 标注 `factor_score_display=bucket` /
`weight_display=coarse`，design_text LLM 表格已桶化，但结构化 API `etfs[].factor_score`
（-0.9855…）与 `etfs[].weight`（0.2067）仍精确小数，与元数据矛盾。

修复：`generate_enhanced_design` 在 `mode=coarse` 时把结构化字段桶化（纯函数
`_apply_precision_bucketing`），`target_amount` 随桶后 `weight` 重算保持内部一致。
"""

import asyncio

import pytest

from app.services import strategy_design as sd
from app.services.strategy_design import (
    _apply_precision_bucketing,
    _bucket_factor_score_label,
)


def _etfs():
    return [
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
         "weight": 0.2067, "factor_score": -0.9855288495104011},
        {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
         "weight": 0.1498, "factor_score": 3.0662},
        {"symbol": "CASH", "layer": "cash", "weight": 0.10},
    ]


class TestApplyPrecisionBucketing:
    """R47: coarse 态结构化字段桶化；exact 态原值不变（负向断言）。"""

    def test_coarse_buckets_weight_and_factor_score(self):
        """mode=coarse → 0.2067→0.20、负因子分→偏弱、3.07→偏强；CASH 不参与桶化。"""
        etfs = _etfs()
        _apply_precision_bucketing(etfs, {"mode": "coarse", "weight_step_pct": 5.0})
        core = next(e for e in etfs if e["symbol"] == "510300")
        assert core["weight"] == 0.20, "0.2067 → 5% 档 0.20"
        assert core["factor_score"] == "偏弱", "负因子分 → 偏弱（不得再含 -0.9855）"
        gov = next(e for e in etfs if e["symbol"] == "511090")
        assert gov["weight"] == 0.15
        assert gov["factor_score"] == "偏强"
        cash = next(e for e in etfs if e["symbol"] == "CASH")
        assert cash["weight"] == 0.10

    def test_coarse_has_no_exact_values(self):
        """负向：coarse 态 factor_score 不得为精确小数、weight 必须为 5% 档。"""
        etfs = _etfs()
        _apply_precision_bucketing(etfs, {"mode": "coarse", "weight_step_pct": 5.0})
        for e in etfs:
            if e["symbol"] == "CASH":
                continue
            assert not isinstance(e["factor_score"], float), "coarse 态 factor_score 不得为精确小数"
            # 浮点容差判定（0.15 % 0.05 因表示误差不恒为 0）
            assert abs((e["weight"] / 0.05) - round(e["weight"] / 0.05)) < 1e-9, (
                "coarse 态 weight 必须为 5% 档"
            )

    def test_exact_keeps_precise_values(self):
        """负向：exact / 非 coarse 态原值不变（不误桶化）。"""
        etfs = _etfs()
        _apply_precision_bucketing(etfs, {"mode": "exact"})
        core = next(e for e in etfs if e["symbol"] == "510300")
        assert core["weight"] == 0.2067, "exact 态 weight 原值不变"
        assert core["factor_score"] == -0.9855288495104011, "exact 态 factor_score 原值不变"
        etfs2 = _etfs()
        _apply_precision_bucketing(etfs2, {"mode": "full"})
        assert etfs2[0]["factor_score"] == -0.9855288495104011, "非 coarse 模式不桶化"

    def test_bucket_factor_score_label(self):
        assert _bucket_factor_score_label(0.6) == "偏强"
        assert _bucket_factor_score_label(-0.7) == "偏弱"
        assert _bucket_factor_score_label(0.1) == "中性"


class TestGenerateEnhancedDesignCoarseBuckets:
    """集成（接线验证）：generate_enhanced_design 在 coarse 态实际调用 _apply_precision_bucketing
    且传入 precision.mode=='coarse'；exact 态调用但不传入 coarse（负向断言）。

    字段内容的桶化（weight 5% 档 / factor_score 分档字符串 / CASH 不桶化）已由纯函数
    TestApplyPrecisionBucketing 覆盖。本类只验证「接线正确、未把 coarse 误当 exact」——
    用 spy 记录真实调用参数，避免依赖编排层在 mock 外部数据下是否产出真实非 CASH 持仓
    （环境性坍缩为 CASH-only 不影响本断言，因为 _apply_precision_bucketing 始终被调用，
    只是对 CASH 提前 return）。
    """

    def _fake_hub(self):
        """复用 test_design_integration 的生产等价候选池 + 因子矩阵，确保引擎能产出真实
        非 CASH 持仓（否则桶化断言会因只有 CASH 而真空通过 / 失败）。"""
        from tests.test_design_integration import (
            _REALISTIC_CANDIDATES, _make_factor_matrix,
        )

        cands = _REALISTIC_CANDIDATES
        fmatrix = _make_factor_matrix(cands)
        by_layer = {"core": [], "satellite": [], "defense": []}
        for c in cands:
            by_layer.setdefault(c.get("layer"), []).append(c)

        class _Hub:
            def __init__(self):
                self._by_code = {}

            async def refresh(self):
                pass

            def get_pool(self, layer=None):
                return by_layer.get(layer, []) if layer else list(cands)

            def get_factor_matrix(self):
                return fmatrix

            def get_market_regime(self):
                return "range_bound"

            def get_market_sentiment(self):
                return {"sentiment_index": 50, "sentiment_label": "中性"}

            def get_index_realtime(self):
                return []

            async def get_global_indices(self):
                return {}

            def get_sector_momentum(self):
                return []

            def get_sector_stocks(self, code):
                return []

            def get_by_code(self, code):
                for it in cands:
                    if it["symbol"] == code:
                        return it
                return None

        return _Hub()

    def _run_with_precision(self, monkeypatch, precision_report):
        """用可读 hub + 隔离风险控制的 mock 跑一遍设计，spy 记录 _apply_precision_bucketing
        的真实调用参数（同时保留真实行为），返回 spy 收集到的 precision 调用序列。"""
        import app.services.market_data_hub as mh_mod

        hub = self._fake_hub()
        monkeypatch.setattr(mh_mod, "market_data_hub", hub)
        # 隔离风险控制在测试之外（阈值对合成因子矩阵敏感，会清空持仓）；本类只验接线
        monkeypatch.setattr(sd, "apply_risk_controls", lambda strat_list, fm, regime=None: strat_list)
        monkeypatch.setattr(sd, "_correlation_matrix_for", lambda allocs, cands: {})
        monkeypatch.setattr(sd, "_correlation_medians_for", lambda allocs, cands: {})
        monkeypatch.setattr(sd, "_factor_data_quality_report",
                            lambda db_sample_counts=None: {"valid_rate": 0.0, "degraded": True})
        monkeypatch.setattr(sd, "_data_precision_report", lambda fq: precision_report)
        # hermetic：直接注入受控 data_precision，避免全量套件中其它测试污染
        # _data_precision_report / market_data_hub 全局导致 exact 态误判 coarse
        # （market_context 仅被用于读取 data_precision["mode"] 做桶化决策）
        async def _fake_bmc(hub):
            return {"data_precision": precision_report}
        monkeypatch.setattr(sd, "_build_market_context", _fake_bmc)
        # spy：记录真实调用参数并保留真实行为
        real_fn = sd._apply_precision_bucketing
        spy_calls: list[dict] = []
        def _spy(etfs, precision):
            spy_calls.append({"precision": precision})
            return real_fn(etfs, precision)
        monkeypatch.setattr(sd, "_apply_precision_bucketing", _spy)
        asyncio.run(sd.generate_enhanced_design(capital=500000))
        return spy_calls

    def test_coarse_invokes_bucketing_with_coarse_mode(self, monkeypatch):
        """coarse 态：_apply_precision_bucketing 必须被调用且至少一次传入 mode=='coarse'。"""
        calls = self._run_with_precision(
            monkeypatch,
            {"mode": "coarse", "weight_step_pct": 5.0, "factor_score_display": "bucket"},
        )
        assert calls, "_apply_precision_bucketing 必须在 coarse 态被调用"
        assert any(c["precision"].get("mode") == "coarse" for c in calls), (
            "coarse 态必须向 _apply_precision_bucketing 传入 mode=='coarse'（否则 R47 桶化不触发）"
        )

    def test_exact_invokes_bucketing_without_coarse_mode(self, monkeypatch):
        """负向：exact 态：_apply_precision_bucketing 任何一次都不得传入 coarse
        （实现上 exact 态直接跳过桶化调用，calls 为空；无论是否被调用，核心保证是
        没有 coarse 桶化发生——exact 精确小数不得被误桶化）。"""
        calls = self._run_with_precision(
            monkeypatch,
            {"mode": "exact", "weight_step_pct": None, "factor_score_display": "exact"},
        )
        assert not any(c["precision"].get("mode") == "coarse" for c in calls), (
            "exact 态不得把 precision 当 coarse 传入（否则会误桶化精确小数）"
        )
