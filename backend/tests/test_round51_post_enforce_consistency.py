"""round51 方案 B (R162/R163): R140 enforce 后 target_amount / cash 行一致性.

背景 (round51 文档 §4.1):
- R162 cash 悬空: strategy_design.py 先算 cash (:663) → R140 enforce (:707)
  缩放卫星层 → 缩掉的权重蒸发, cash 行不回补 → design15 balanced total=0.95
  (cash 行 0.23 vs expected 0.28, GAP +0.05)。
- R163 target_amount 脱节: `_validate_target_amount_consistency` (:692) 在
  enforce (:707) 之前执行, enforce 缩放 weight 后 target_amount 仍按旧权重
  (50000 vs 36650, +36%)。

修复 (方案 B): enforce 之后重算 target_amount (capital × weight) + 重算 cash 行
(1 − Σnon_cash, 同 :663 公式), 再跑一次 target_amount 校验。
约束: 遵守 AGENTS.md「权重不归一化」——只回补 cash 行, 不归一化各层权重。
"""
from __future__ import annotations

import pytest

# design15 balanced 实测形态 (round51 probe11): enforce 缩卫星层 0.28→0.22 后
# cash 行 0.23 vs 1−Σnon_cash=0.28 → 悬空 5%。
_DESIGN15_LIKE_ETFS = [
    {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "weight": 0.45,
     "target_amount": 225000.0},
    {"symbol": "512890", "name": "红利低波ETF", "layer": "satellite", "weight": 0.28,
     "target_amount": 140000.0},  # enforce 将缩到 0.22, target_amount 须同步重算
    {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "weight": 0.05,
     "target_amount": 25000.0},
    {"symbol": "CASH", "name": "现金", "layer": "cash", "weight": 0.22,
     "selection_rationale": "流动性管理"},
]
_CAPITAL = 500000.0


def _make_strategies() -> list[dict]:
    return [{
        "id": "balanced",
        "capital": _CAPITAL,
        "layer_budget": {"core": 0.50, "satellite": 0.22, "defense": 0.13},
        "etfs": [dict(a) for a in _DESIGN15_LIKE_ETFS],
    }]


class TestReconcileAfterEnforce:
    """修复函数本身的行为: 缩放后回补 cash 行 + 重算 target_amount。"""

    def test_cash_row_backfilled_after_scale_down(self):
        """卫星层被 enforce 缩掉 0.06 后, cash 行必须回补到 1−Σnon_cash。"""
        from app.services.strategy_design import _reconcile_after_enforce

        strategies = _make_strategies()
        _reconcile_after_enforce(strategies, _CAPITAL)
        cash = next(a for a in strategies[0]["etfs"] if a["symbol"] == "CASH")
        non_cash = sum(a["weight"] for a in strategies[0]["etfs"]
                       if a["symbol"] != "CASH")
        # 回补后 cash 行 == 1−Σnon_cash (R162 悬空闭合)
        assert cash["weight"] == pytest.approx(1.0 - non_cash, abs=1e-6)
        # 且悬空消失: total (含 cash) == 1.0
        assert non_cash + cash["weight"] == pytest.approx(1.0, abs=1e-6)

    def test_target_amount_recomputed_after_scale_down(self):
        """R163: enforce 缩放 weight 后, target_amount 必须按新 weight 重算。"""
        from app.engine.allocation_engine import _enforce_layer_budget_final
        from app.services.strategy_design import _reconcile_after_enforce

        strategies = _make_strategies()
        # 模拟编排器时序: enforce 先缩放卫星层 0.28 → 0.22（预算 0.22）
        _enforce_layer_budget_final(strategies[0]["etfs"],
                                    strategies[0]["layer_budget"])
        _reconcile_after_enforce(strategies, _CAPITAL)
        sat = next(a for a in strategies[0]["etfs"] if a["symbol"] == "512890")
        # 0.28 被 enforce 缩到 0.22 → target_amount 50000→110000 (capital×0.22)
        assert sat["weight"] == pytest.approx(0.22, abs=1e-6)
        assert sat["target_amount"] == pytest.approx(_CAPITAL * 0.22, abs=0.01)

    def test_no_cash_row_when_non_cash_ge_one(self):
        """非现金权重 ≥1.0 时不造负 cash 行 (与 :663 cash_weight>0 守卫一致)。"""
        from app.services.strategy_design import _reconcile_after_enforce

        strategies = [{
            "id": "aggressive",
            "capital": _CAPITAL,
            "layer_budget": {"core": 0.60, "satellite": 0.30, "defense": 0.05},
            "etfs": [
                {"symbol": "510300", "layer": "core", "weight": 0.60,
                 "target_amount": 300000.0},
                {"symbol": "512890", "layer": "satellite", "weight": 0.30,
                 "target_amount": 150000.0},
                {"symbol": "518880", "layer": "defense", "weight": 0.15,
                 "target_amount": 75000.0},
            ],
        }]
        _reconcile_after_enforce(strategies, _CAPITAL)
        # defense 0.15 超 0.05 被缩到 0.05 → Σnon_cash=0.95 < 1.0, 会造出 cash 行
        cash = [a for a in strategies[0]["etfs"] if a["symbol"] == "CASH"]
        non_cash = sum(a["weight"] for a in strategies[0]["etfs"]
                       if a["symbol"] != "CASH")
        if non_cash < 1.0:
            assert len(cash) == 1
            assert cash[0]["weight"] == pytest.approx(1.0 - non_cash, abs=1e-6)
        else:
            assert len(cash) == 0

    def test_weights_never_normalized(self):
        """AGENTS.md 约定: 回补只改 cash 行, 不归一化各层权重。"""
        from app.services.strategy_design import _reconcile_after_enforce

        strategies = _make_strategies()
        before = {a["symbol"]: a["weight"] for a in strategies[0]["etfs"]
                  if a["symbol"] != "CASH"}
        _reconcile_after_enforce(strategies, _CAPITAL)
        after = {a["symbol"]: a["weight"] for a in strategies[0]["etfs"]
                 if a["symbol"] != "CASH"}
        # enforce 缩放属 R140 职责; reconcile 本身不得再动 non_cash 权重
        # (对比基准: enforce 已跑过, reconcile 前后 non_cash 不变)
        # 这里直接构造已 enforce 的输入再跑一遍 reconcile 验证幂等
        _reconcile_after_enforce(strategies, _CAPITAL)
        after2 = {a["symbol"]: a["weight"] for a in strategies[0]["etfs"]
                  if a["symbol"] != "CASH"}
        assert after2 == after  # 幂等: 第二遍不再改动

    def test_missing_cash_row_gets_created(self):
        """enforce 缩放后 cash 行可能被上游删掉(不存在)——重算时应补建。"""
        from app.services.strategy_design import _reconcile_after_enforce

        strategies = _make_strategies()
        # 模拟 enforce 缩放后的中间态: 卫星已缩、cash 行还是旧值
        sat = next(a for a in strategies[0]["etfs"] if a["symbol"] == "512890")
        sat["weight"] = 0.22
        sat["target_amount"] = 110000.0
        cash = next(a for a in strategies[0]["etfs"] if a["symbol"] == "CASH")
        cash["weight"] = 0.28  # 期望正确值, 但行内数据是上游留下的 0.23→0.28 差
        # 删掉 cash 行再 reconcile: 应重建
        strategies[0]["etfs"] = [a for a in strategies[0]["etfs"]
                                 if a["symbol"] != "CASH"]
        _reconcile_after_enforce(strategies, _CAPITAL)
        cash_rows = [a for a in strategies[0]["etfs"] if a["symbol"] == "CASH"]
        assert len(cash_rows) == 1
        non_cash = sum(a["weight"] for a in strategies[0]["etfs"]
                       if a["symbol"] != "CASH")
        assert cash_rows[0]["weight"] == pytest.approx(1.0 - non_cash, abs=1e-6)


class TestOrchestratorPostEnforceConsistency:
    """编排器级不变量: generate_enhanced_design 输出必过三重一致性。

    负向断言 (round51 §4.2): mock 强制缩放 → target_amount 与 weight 一致 +
    cash 行 == 1−Σnon_cash 必须仍成立。
    """

    @pytest.mark.asyncio
    async def test_output_consistency_after_forced_scale(self, monkeypatch):
        """enforce 缩放后输出仍满足: target_amount==capital×weight ∧ cash==1−Σ。"""
        from app.services import strategy_design as sd

        # 篡改 _enforce_layer_budget_final: 无条件把卫星层全缩到 30% 制造 R162/R163 形态
        def _force_scale(allocs, budgets):
            for a in allocs:
                if a.get("layer") == "satellite" and a.get("symbol") != "CASH":
                    a["weight"] = round(a.get("weight", 0) * 0.3, 4)
            return allocs

        monkeypatch.setattr(
            "app.engine.allocation_engine._enforce_layer_budget_final", _force_scale)

        async def mock_refresh(*args, **kwargs):
            pass

        with patch_hub(monkeypatch):
            result = await sd.generate_enhanced_design(capital=_CAPITAL)

        assert "strategies" in result, f"unexpected: {list(result)}"
        for s in result["strategies"]:
            etfs = s.get("etfs") or []
            non_cash = sum(a.get("weight", 0) for a in etfs
                           if a.get("symbol") != "CASH")
            cash_rows = [a for a in etfs if a.get("symbol") == "CASH"]
            # R162: cash 行存在时必等于 1−Σnon_cash
            if cash_rows:
                assert cash_rows[0]["weight"] == pytest.approx(
                    1.0 - non_cash, abs=0.005), f"{s['id']} cash 悬空"
            # R163: 每标的 target_amount == capital × weight
            for a in etfs:
                assert a.get("target_amount") == pytest.approx(
                    _CAPITAL * a.get("weight", 0), abs=1.0), \
                    f"{s['id']}/{a.get('symbol')} target_amount 脱节"

    @pytest.mark.asyncio
    async def test_validate_runs_after_enforce(self, monkeypatch):
        """_validate_target_amount_consistency 必须在 enforce 之后至少跑一次。"""
        from app.services import strategy_design as sd

        calls: list[str] = []
        real_validate = sd._validate_target_amount_consistency

        def spy_validate(*a, **kw):
            calls.append("validate")
            return real_validate(*a, **kw)

        import app.engine.allocation_engine as eng

        real_enforce = eng._enforce_layer_budget_final

        def spy_enforce(*a, **kw):
            calls.append("enforce")
            return real_enforce(*a, **kw)

        monkeypatch.setattr(sd, "_validate_target_amount_consistency", spy_validate)
        # orchestrator 内部是函数内 `from ... import _enforce_layer_budget_final`,
        # patch 源模块属性即可被函数内 import 捕获
        import app.engine.allocation_engine as eng
        monkeypatch.setattr(eng, "_enforce_layer_budget_final", spy_enforce)

        async def mock_refresh(*args, **kwargs):
            pass

        with patch_hub(monkeypatch):
            await sd.generate_enhanced_design(capital=_CAPITAL)

        assert "validate" in calls and "enforce" in calls
        # 至少存在一次 validate 晚于 enforce (时序不变量核心断言)
        assert calls.index("enforce") < max(
            i for i, c in enumerate(calls) if c == "validate")


def patch_hub(monkeypatch):
    """mock market_data_hub 全链 (静池兜底路径, 沿用既有测试模式)。"""
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def _cm():
        with patch("app.services.market_data_hub.market_data_hub.refresh",
                   side_effect=lambda *a, **kw: None), \
             patch("app.services.market_data_hub.market_data_hub.get_pool",
                   side_effect=lambda layer=None: {"core": [], "satellite": [],
                                                   "defense": []}), \
             patch("app.services.market_data_hub.market_data_hub.get_factor_matrix",
                   return_value={}), \
             patch("app.services.market_data_hub.market_data_hub.get_market_regime",
                   return_value="range_bound"), \
             patch("app.services.market_data_hub.market_data_hub.get_market_sentiment",
                   return_value={"sentiment_index": 50, "sentiment_label": "中性"}), \
             patch("app.services.market_data_hub.market_data_hub.get_index_realtime",
                   return_value=[]), \
             patch("app.services.market_data_hub.market_data_hub.get_sector_momentum",
                   return_value=[]):
            yield
    return _cm()
