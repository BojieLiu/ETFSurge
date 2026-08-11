"""round14 P0-A（apply-design 前后端断裂）+ P0-C（因子 IC 最小样本保护）测试。

对应 docs/round14-container-acceptance-diagnosis.md §2.2/§2.4/§5 P0-A/P0-C：
- P0-A: 后端 apply-design 对空 symbols/weights 返回 400（修复前 200 空操作）；
  前端等效 payload（{portfolio_type, symbols, weights} 契约形态）应用后 applied 非空
- P0-C: 样本数 < MIN_IC_SAMPLES(30) 时 IC 视为未累积（no_data），不产生
  「样本数 0 却有 |IC|≥0.02」的伪负向下架（warn）
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.routers import factors as factors_router
from app.routers.portfolio import apply_design
from app.services.portfolio_service import apply_portfolio_design

client = TestClient(app)


class TestApplyDesignBackend:
    """P0-A 后端加固：空 payload → 400；契约 payload → applied 非空。"""

    def test_empty_symbols_rejected_400(self):
        """修复前：空 symbols 返回 200 空操作（前端假成功）；修复后 400。"""
        with patch("app.routers.portfolio.apply_portfolio_design", new_callable=AsyncMock) as m:
            resp = client.post("/api/v1/portfolio/apply-design", json={"portfolio_type": "on_exchange", "symbols": [], "weights": {}})
        assert resp.status_code == 400
        m.assert_not_awaited()

    def test_missing_weights_rejected_400(self):
        resp = client.post("/api/v1/portfolio/apply-design", json={"portfolio_type": "on_exchange", "symbols": ["510300"]})
        assert resp.status_code == 400

    def test_contract_payload_applied_matches_symbols(self):
        """基线 D 首个用例（前端真实消费形态）：契约 payload → applied 与 symbols 一致。"""
        fake_result = {
            "symbols": [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3, "portfolio_type": "on_exchange"}],
            "applied": [{"symbol": "510300", "name": "沪深300ETF", "target_weight": 0.3, "portfolio_type": "on_exchange", "action": "updated"}],
        }
        with patch("app.routers.portfolio.apply_portfolio_design", new_callable=AsyncMock, return_value=fake_result):
            payload = {
                "portfolio_type": "on_exchange",
                "symbols": ["510300", "159338"],
                "weights": {"510300": 0.3, "159338": 0.2},
            }
            resp = client.post("/api/v1/portfolio/apply-design", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("applied"), "applied 必须非空（防前端假成功）"
        assert body["applied"][0]["symbol"] in payload["symbols"]

    def test_service_layer_empty_symbols_returns_empty_not_crash(self):
        """服务层仍兼容直接调用（不抛异常），路由层负责 400 拦截。"""
        with patch("app.services.portfolio_service.list_etfs", new_callable=AsyncMock, return_value=[]):
            result = asyncio_run(apply_portfolio_design(MagicMock(), {"symbols": [], "weights": {}}))
        assert result.get("symbols") == []


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


class TestFactorMinSampleProtection:
    """P0-C: 最小样本保护——样本不足不产生 warn 下架。"""

    def test_low_samples_no_downlisting(self):
        """样本 0 但 |IC|=0.45 → no_data「未累积」，不是 warn「负向预测已下架」。"""
        with patch.object(factors_router.registry, "_last_ic_batch", {"technical.ma.sma_5": -0.45}):
            with patch.object(factors_router.registry, "_sample_counts", {"technical.ma.sma_5": 0}):
                status, reason = factors_router._status_of("technical.ma.sma_5", -0.45, 0.02)
        assert status == "no_data", f"样本不足应 no_data（实际 {status}）"
        assert "未累积" in reason

    def test_enough_samples_normal_evaluation(self):
        """样本 ≥30 时正常评估：|IC|≥阈值 → valid/warn。"""
        with patch.object(factors_router.registry, "_sample_counts", {"technical.ma.sma_5": 120}):
            status_neg, _ = factors_router._status_of("technical.ma.sma_5", -0.45, 0.02)
            status_pos, _ = factors_router._status_of("technical.ma.sma_5", 0.45, 0.02)
        assert status_neg == "warn"  # 负向且 |IC|≥阈值 → 淘汰警示（样本足够时成立）
        assert status_pos == "valid"

    def test_min_ic_samples_constant(self):
        assert factors_router.MIN_IC_SAMPLES == 30
