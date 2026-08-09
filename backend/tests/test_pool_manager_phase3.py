"""
TDD: MarketDataHub Phase 3 - daily refresh audit + market data adapter.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestPoolAudit:
    """MarketDataHub 审计日志"""

    @pytest.fixture
    def audit(self):
        from app.services.pool_audit import PoolAudit
        return PoolAudit()

    def test_log_refresh(self, audit):
        """记录一次 refresh 事件"""
        diff = MagicMock()
        diff.version = 3
        diff.added = [{"symbol": "159995", "name": "芯片ETF"}]
        diff.removed = [{"symbol": "159999", "name": "僵尸ETF"}]
        diff.changed = []
        diff.timestamp = "2026-07-17T12:00:00"

        audit.log_refresh(diff)
        assert len(audit.get_history()) == 1

    def test_get_history_returns_sorted(self, audit):
        """历史记录应按时间倒序"""
        diff1 = MagicMock(version=1, added=[], removed=[], changed=[], timestamp="2026-07-16")
        diff2 = MagicMock(version=2, added=[], removed=[], changed=[], timestamp="2026-07-17")
        audit.log_refresh(diff1)
        audit.log_refresh(diff2)
        history = audit.get_history(limit=2)
        assert len(history) == 2
        assert history[0]["version"] == 2  # newest first

    def test_get_history_limit(self, audit):
        """限制返回条数"""
        for i in range(5):
            d = MagicMock(version=i, added=[], removed=[], changed=[], timestamp=f"2026-07-{16+i}")
            audit.log_refresh(d)
        assert len(audit.get_history(limit=3)) == 3

    def test_last_refresh(self, audit):
        """返回最近一次 refresh 记录"""
        assert audit.get_last_refresh() is None
        diff = MagicMock(version=5, added=[], removed=[], changed=[], timestamp="2026-07-17")
        audit.log_refresh(diff)
        last = audit.get_last_refresh()
        assert last is not None
        assert last["version"] == 5




class TestDailyRefresh:
    """MarketDataHub 日频刷新调度"""

    @pytest.mark.asyncio
    async def test_refresh_and_audit(self):
        """refresh() 后审计日志应有记录"""
        from app.services.market_data_hub import market_data_hub
        from app.services.pool_audit import pool_audit

        with patch.object(market_data_hub, 'scanner') as mock_scanner:
            mock_scanner.full_pipeline.return_value = {
                "core": [{"symbol": "510300", "name": "沪深300ETF", "amount": 10e8, "fund_scale": 50e8}],
                "satellite": [{"symbol": "512480", "name": "半导体ETF", "amount": 8e8, "fund_scale": 30e8}],
                "defense": [{"symbol": "518880", "name": "黄金ETF", "amount": 20e8, "fund_scale": 100e8}],
            }
            market_data_hub.classifier = MagicMock()
            market_data_hub.classifier.batch_classify.return_value = {
                "510300": {"industry": "宽基指数", "concepts": [], "confidence": 0.85},
                "512480": {"industry": "电子", "concepts": [], "confidence": 0.85},
                "518880": {"industry": "商品", "concepts": [], "confidence": 0.85},
            }

            diff = await market_data_hub.refresh()
            # 审计日志应有记录
            log_entry = pool_audit.get_last_refresh()
            assert log_entry is not None
            assert log_entry["version"] > 0
