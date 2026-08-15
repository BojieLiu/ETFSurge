from __future__ import annotations
"""
F15/F20 (docs/archived/round23-system-audit-optimization.md §3.3/§2.3): 数据完整性修复。

F15: 孤立 avg_cost（有成本无份额）落库拦截——add_etf / update_etf / import_portfolio
     三条路径统一：shares_held 缺失/≤0 时 avg_cost 强制 None（不落脏数据）。
F20: /market/sentiment 的 up_ratio 实为「涨停封板率」非「上涨占比」——后端重命名
     透明化为 limit_up_seal_rate（保留 up_ratio 兼容）。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestF15OrphanAvgCost:
    """F15 (round23 §3.3): 孤立 avg_cost 拦截。"""

    @pytest.mark.asyncio
    async def test_add_etf_avg_cost_cleared_when_no_shares(self):
        """add_etf 传 avg_cost 但 shares_held 缺失/0 → avg_cost=None（不落孤立成本）。"""
        from app.services.portfolio_service import add_etf

        db = AsyncMock()
        db.refresh = AsyncMock()
        data = MagicMock()
        data.symbol = "510300"
        data.name = "沪深300ETF"
        data.short_name = None
        data.asset_type = "HK"  # 避开 _resolve_tracked_index 网络依赖
        data.target_weight = 0.1
        data.portfolio_type = "on_exchange"
        data.tracked_index = None
        data.avg_cost = 4.62
        data.shares_held = None  # 有成本无份额
        data.first_buy_date = None
        data.last_trade_date = None

        etf = await add_etf(db, data)
        assert etf.avg_cost is None, f"无份额时应清 avg_cost，实得 {etf.avg_cost}"
        assert etf.shares_held == 0

    @pytest.mark.asyncio
    async def test_add_etf_avg_cost_kept_when_shares_positive(self):
        """add_etf 有成本且有份额 → 正常落库（回归保护）。"""
        from app.services.portfolio_service import add_etf

        db = AsyncMock()
        db.refresh = AsyncMock()
        data = MagicMock()
        data.symbol = "510300"
        data.name = "沪深300ETF"
        data.short_name = None
        data.asset_type = "HK"
        data.target_weight = 0.1
        data.portfolio_type = "on_exchange"
        data.tracked_index = None
        data.avg_cost = 4.62
        data.shares_held = 5000
        data.first_buy_date = None
        data.last_trade_date = None

        etf = await add_etf(db, data)
        assert etf.avg_cost == 4.62
        assert etf.shares_held == 5000

    @pytest.mark.asyncio
    async def test_update_etf_clears_avg_cost_when_shares_zero(self):
        """update_etf 份额清零 → avg_cost 同步清空（防孤立）。"""
        from app.services.portfolio_service import update_etf

        class FakeEtf:
            avg_cost = 4.5
            shares_held = 1000
            name = "沪深300ETF"
            target_weight = 0.1
            is_active = True
            portfolio_type = "on_exchange"
            short_name = None
            tracked_index = None
            first_buy_date = None
            last_trade_date = None

        etf_obj = FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf_obj))
        db.refresh = AsyncMock()

        data = MagicMock()
        data.name = None
        data.target_weight = None
        data.is_active = None
        data.portfolio_type = None
        data.short_name = None
        data.tracked_index = None
        data.avg_cost = None
        data.shares_held = 0  # 份额清零
        data.first_buy_date = None
        data.last_trade_date = None
        data.delta_shares = None

        await update_etf(db, "510300", data)
        assert etf_obj.shares_held == 0
        assert etf_obj.avg_cost is None, "份额清零应同步清 avg_cost"

    @pytest.mark.asyncio
    async def test_update_etf_rejects_avg_cost_without_shares(self):
        """update_etf 传 avg_cost 但当前份额 0 且未传 shares → 不落孤立成本。"""
        from app.services.portfolio_service import update_etf

        class FakeEtf:
            avg_cost = None
            shares_held = 0
            name = "沪深300ETF"
            target_weight = 0.1
            is_active = True
            portfolio_type = "on_exchange"
            short_name = None
            tracked_index = None
            first_buy_date = None
            last_trade_date = None

        etf_obj = FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf_obj))
        db.refresh = AsyncMock()

        data = MagicMock()
        data.name = None
        data.target_weight = None
        data.is_active = None
        data.portfolio_type = None
        data.short_name = None
        data.tracked_index = None
        data.avg_cost = 4.5  # 无份额传成本
        data.shares_held = None
        data.first_buy_date = None
        data.last_trade_date = None
        data.delta_shares = None

        await update_etf(db, "510300", data)
        assert etf_obj.avg_cost is None, "有成本无份额不应落库"

    @pytest.mark.asyncio
    async def test_import_portfolio_clears_orphan_avg_cost(self):
        """import_portfolio CSV 有 avg_cost 无 shares_held → 落库 avg_cost=None。"""
        from app.services.portfolio_service import import_portfolio

        class FakeDb:
            added = []

            def add(self, obj):
                self.added.append(obj)

            async def flush(self):
                pass

            async def commit(self):
                pass

        # 空库（list_etfs 返回 []）
        async def _fake_list_etfs(db, pt):
            return []

        with patch("app.services.portfolio_service.list_etfs", new=_fake_list_etfs):
            db = FakeDb()
            csv_content = (
                "symbol,name,asset_type,portfolio_type,target_weight,avg_cost,shares_held\n"
                "510300,沪深300ETF,ETF,on_exchange,0.1,4.62,\n"  # 有成本无份额
            )
            result = await import_portfolio(db, csv_content)
        assert result["errors"] == [], f"导入应无错误，实际 {result['errors']}"
        assert result["imported"] == 1
        added = [e for e in db.added if getattr(e, "symbol", None) == "510300"]
        assert added, "应新增 510300"
        assert added[0].avg_cost is None, f"孤立 avg_cost 不应落库，实得 {added[0].avg_cost}"


class TestF20UpRatioRename:
    """F20 (round23 §2.3): up_ratio → limit_up_seal_rate 透明化。"""

    def test_fetch_market_emotion_adds_limit_up_seal_rate(self):
        from app.fetchers import levistock_fetcher as lf

        fake_raw = {
            "up_ratio": "65.00%",
            "up_ratio_num": "37",
            "up_open_num": "20",
            "up_down_dis": {"rise_num": 1444, "fall_num": 3977},
        }
        with patch.object(lf, "lv") as mock_lv, \
             patch.object(lf, "cached", side_effect=lambda key, fn, **kw: fn()):
            mock_lv.market_emotion_cls = lambda: fake_raw
            data = lf.fetch_market_emotion()
        assert data["limit_up_seal_rate"] == "65.00%"
        assert data["up_ratio"] == "65.00%"  # 兼容保留
        assert "封板率" in data.get("limit_up_seal_rate_note", "")

    def test_fetch_market_emotion_empty_data(self):
        """数据源失败（空 dict）→ 不崩、无新增字段。"""
        from app.fetchers import levistock_fetcher as lf

        with patch.object(lf, "lv") as mock_lv, \
             patch.object(lf, "cached", side_effect=lambda key, fn, **kw: fn()):
            mock_lv.market_emotion_cls = lambda: {}
            data = lf.fetch_market_emotion()
        assert data == {}


# ===== folded from test_round19_batch1.py =====
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException
class TestPortfolioEtfPersistCost:
    """round19 P3-①: add_etf / update_etf 落库 avg_cost/shares_held（负向：丢弃 → FAIL）。"""

    @pytest.mark.asyncio
    async def test_add_etf_persists_avg_cost_and_shares(self):
        """add_etf 传 avg_cost/shares_held → 构造对象落库一致值（此前静默丢弃）。"""
        from app.services.portfolio_service import add_etf

        db = AsyncMock()
        db.refresh = AsyncMock()
        data = MagicMock()
        data.symbol = "510300"
        data.name = "沪深300ETF"
        data.short_name = None
        data.asset_type = "HK"  # 非 A 分支，避免 _resolve_tracked_index 网络依赖
        data.target_weight = 0.1
        data.portfolio_type = "on_exchange"
        data.tracked_index = None
        data.avg_cost = 4.62
        data.shares_held = 5000
        data.first_buy_date = None
        data.last_trade_date = None

        etf = await add_etf(db, data)
        assert etf.avg_cost == 4.62, f"avg_cost 应落库，实得 {etf.avg_cost}"
        assert etf.shares_held == 5000, f"shares_held 应落库，实得 {etf.shares_held}"

    @pytest.mark.asyncio
    async def test_update_etf_persists_avg_cost_and_shares(self):
        """update_etf 传 avg_cost/shares_held → 对象更新一致值（此前传了不生效）。"""
        from app.services.portfolio_service import update_etf

        class FakeEtf:
            avg_cost = None
            shares_held = None
            name = "沪深300ETF"
            target_weight = 0.1
            is_active = True
            portfolio_type = "on_exchange"
            short_name = None
            tracked_index = None
            first_buy_date = None
            last_trade_date = None

        etf_obj = FakeEtf()
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=etf_obj))
        db.refresh = AsyncMock()

        data = MagicMock()
        data.name = None
        data.target_weight = None
        data.is_active = None
        data.portfolio_type = None
        data.short_name = None
        data.tracked_index = None
        data.avg_cost = 4.5
        data.shares_held = 1000
        data.first_buy_date = None
        data.last_trade_date = None
        data.delta_shares = None  # round19 P3-③: adjust 语义未启用（MagicMock 属性默认非 None）
        data.price = None

        result = await update_etf(db, "510300", data)
        assert result is not None
        assert result.avg_cost == 4.5, f"avg_cost 应更新，实得 {result.avg_cost}"
        assert result.shares_held == 1000, f"shares_held 应更新，实得 {result.shares_held}"
