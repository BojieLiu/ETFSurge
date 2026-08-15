"""round24 R22 (P2): /factors/active 与 /factors/model 的 summary.avg_ic 口径统一。

背景 (docs/round24-reverification-and-fixes.md §5.2/§12.3 R22):
同屏两个「平均 |IC|」不一致——/factors/active 实测 0.2134 vs /factors/model 0.3221。
根因: 两处聚合口径不同:
- /active: status != static 因子的 ic_value 绝对值均值（market-level 因子经 status=static 过滤）
- /model (_build_health_summary): 非 static 非 market-level 的 _last_ic_batch 值绝对值均值

修复: 新增共享 helper `_global_avg_ic(ic_batch, exclude_static=True, exclude_market=True)`，
两端点统一调用 → 同一时刻返回同一值。
口径: 非 static 非 market-level 且当前 _last_ic_batch 有 ic_value 的因子，取绝对值均值（F26）。
"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers import factors as factors_router
from app.factors.factor_registry import registry

# ── 合成注册表状态: 混合普通 / static / market-level / batch-only 因子 ──────
# 注意 technical.rsi.rsi_14 只存在于 _last_ic_batch（不在 _computers）——
# 验证口径以「当前有 ic_value 的因子」为准（两端点都必须纳入）。
FAKE_BATCH = {
    "technical.ma.sma_5": 0.1,           # 普通因子 → 纳入
    "style.size.ln_mcap": -0.2,          # 普通因子（负值）→ 纳入（取绝对值）
    "technical.rsi.rsi_14": 0.3,         # 仅存于 _last_ic_batch → 纳入
    "china.policy.five_year_plan": 0.9,  # static → 排除
    "sentiment.panic_greed_diff": 0.5,   # market-level → 排除
}
EXPECTED_AVG_IC = round((0.1 + 0.2 + 0.3) / 3, 4)  # 0.2

FAKE_COMPUTERS = {
    code: (lambda x: 0.0)
    for code in ("technical.ma.sma_5", "style.size.ln_mcap",
                 "china.policy.five_year_plan", "sentiment.panic_greed_diff")
}


def _make_fake_definition(code, category, standardization="zscore",
                          ic_threshold=0.02, name="F"):
    from app.factors.factor_registry import FactorDefinition
    return FactorDefinition(
        code=code, name=name, category=category, subcategory="",
        standardization=standardization, ic_threshold=ic_threshold,
    )


def _decode_body(body):
    """JSONResponse → dict（兼容 .body bytes）。"""
    data = body.body if hasattr(body, "body") else body
    if isinstance(data, bytes):
        data = json.loads(data)
    return data


class TestGlobalAvgIcHelper:
    """_global_avg_ic 单元级: 口径 = 非 static 非 market-level 且有 ic_value，绝对值均值。"""

    def test_excludes_static_and_market_level(self):
        assert factors_router._global_avg_ic(FAKE_BATCH) == EXPECTED_AVG_IC

    def test_exclude_static_flag(self):
        # exclude_static=False → static 因子 (0.9) 纳入
        assert factors_router._global_avg_ic(
            FAKE_BATCH, exclude_static=False) == round((0.1 + 0.2 + 0.3 + 0.9) / 4, 4)

    def test_exclude_market_flag(self):
        # exclude_market=False → market-level 因子 (0.5) 纳入
        assert factors_router._global_avg_ic(
            FAKE_BATCH, exclude_market=False) == round((0.1 + 0.2 + 0.3 + 0.5) / 4, 4)

    def test_empty_or_none_batch_returns_none(self):
        assert factors_router._global_avg_ic({}) is None
        assert factors_router._global_avg_ic(None) is None

    def test_all_excluded_returns_none(self):
        batch = {"china.policy.five_year_plan": 0.9,
                 "sentiment.panic_greed_diff": 0.5}
        assert factors_router._global_avg_ic(batch) is None


class TestEndpointAvgIcConsistency:
    """端点级: /factors/active 与 /factors/model 同一时刻 summary.avg_ic 必须一致。"""

    @pytest.fixture(autouse=True)
    def _isolate(self):
        """清响应缓存 + stub DB 序列统计，避免跨测试串扰（同 test_z03 模式）。"""
        factors_router._CACHE.clear()
        factors_router._db_ic_sample_counts = AsyncMock(return_value={})
        factors_router._db_ic_series_stats = AsyncMock(return_value={})
        yield
        factors_router._CACHE.clear()

    @pytest.mark.asyncio
    async def test_both_endpoints_report_same_avg_ic(self):
        fake_factors = {
            c: _make_fake_definition(c, c.split(".")[0]) for c in FAKE_COMPUTERS
        }
        with patch.object(registry, "_computers", FAKE_COMPUTERS), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", FAKE_BATCH), \
             patch.object(registry, "_sample_counts", {}), \
             patch.object(registry, "_last_computed_at", "2026-08-15T10:00:00Z"):
            active = await factors_router.get_active_factors(db=MagicMock())
            model = await factors_router.get_factor_model(db=MagicMock())

        active_summary = _decode_body(active)["summary"]
        model_summary = _decode_body(model)["summary"]

        # R22: 两端点同一时刻 avg_ic 一致，且等于「非 static 非 market-level 且有 ic_value」的绝对值均值
        assert active_summary["avg_ic"] == model_summary["avg_ic"], \
            f"/active {active_summary['avg_ic']} != /model {model_summary['avg_ic']}（口径未统一）"
        assert active_summary["avg_ic"] == EXPECTED_AVG_IC, \
            f"/active avg_ic={active_summary['avg_ic']} 期望 {EXPECTED_AVG_IC}"
        assert model_summary["avg_ic"] == EXPECTED_AVG_IC

    @pytest.mark.asyncio
    async def test_model_summary_still_has_all_aggregate_fields(self):
        """R22 不破坏 /model summary 既有字段（valid/warn/no_data/static/min_samples 等）。"""
        fake_factors = {
            c: _make_fake_definition(c, c.split(".")[0]) for c in FAKE_COMPUTERS
        }
        with patch.object(registry, "_computers", FAKE_COMPUTERS), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", FAKE_BATCH):
            model = await factors_router.get_factor_model(db=MagicMock())

        s = _decode_body(model)["summary"]
        for key in ("valid", "warn", "no_data", "static", "avg_ic",
                    "min_samples", "observable_days", "significant", "observable"):
            assert key in s, f"/model summary 缺 {key}"

    @pytest.mark.asyncio
    async def test_active_global_avg_uses_same_caliber_as_per_category(self):
        """/active 全局 avg_ic 走 _global_avg_ic，per-category avg_ic 保持原逻辑不变。"""
        fake_factors = {
            c: _make_fake_definition(c, c.split(".")[0]) for c in FAKE_COMPUTERS
        }
        with patch.object(registry, "_computers", FAKE_COMPUTERS), \
             patch.object(registry, "_factors", fake_factors), \
             patch.object(registry, "_last_ic_batch", FAKE_BATCH):
            active = await factors_router.get_active_factors(db=MagicMock())

        data = _decode_body(active)
        # per-category: technical 分类下 sma_5=0.1（ln_mcap 在 style 分类）→ avg = 0.1
        tech_cat = next(c for c in data["categories"] if c["name"] == "technical")
        assert tech_cat["avg_ic"] == 0.1
        # 全局 ≠ 某分类值（全局含 ln_mcap 0.2 与 batch-only rsi_14 0.3）——口径明确为全因子池
        assert data["summary"]["avg_ic"] == EXPECTED_AVG_IC
