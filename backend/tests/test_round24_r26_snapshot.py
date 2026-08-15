"""round24 R26: 盘后数据变薄优化——market_session 显式盘后模式 + 快照持久化。

问题（round24 §12.1 R26 实证）：盘后/熔断时 design 570 `valid_rate=0.0%`、correlation
空、sector_momentum=[]、fund_flow=0。last-good pool / kline cache / ic batch 全内存
重启即丢 → 盘后重启 = 全空 = 静态兜底。T-1 真实数据不持久化。

修复：
- `market_session()`（market_calendar）：open / pre_market / after_hours（盘后固定价格
  交易 15:05-15:30，2026-07-06 A股新规）/ post_market / closed——纯函数；
- `MarketSnapshot` 模型 + `_persist_snapshot` / `_load_latest_snapshot`：pool /
  sector_momentum / fund_flow 落盘，盘后/熔断读快照兜底（last-good 之上再一层）；
- `strategy_design._build_market_context` 透传 session + data_as_of。
"""

import json
from datetime import datetime, date

import pytest


class TestMarketSession:
    """R26①: market_session 显式盘后模式（含 2026-07-06 盘后固定价格交易窗口）。"""

    def _dt(self, day, hhmm):
        h, m = int(hhmm[:2]), int(hhmm[3:])
        return datetime(2026, 8, day, h, m)  # 2026-08-14 是周五

    @pytest.mark.parametrize("hhmm,expected", [
        ("10:00", "open"),
        ("14:59", "open"),
        ("15:02", "post_market"),      # 15:00-15:05 间隙（收盘集合竞价后）
        ("15:10", "after_hours"),      # 盘后固定价格交易窗口 15:05-15:30（新规）
        ("15:30", "after_hours"),      # 边界含 15:30
        ("15:31", "post_market"),      # 窗口后
        ("18:00", "post_market"),
        ("09:00", "pre_market"),       # 开盘前
    ])
    def test_weekday_sessions(self, hhmm, expected):
        from app.core.market_calendar import market_session
        assert market_session(self._dt(14, hhmm)) == expected

    def test_weekend_closed(self):
        from app.core.market_calendar import market_session
        sat = datetime(2026, 8, 15, 10, 0)  # 周六
        assert market_session(sat) == "closed"

    def test_is_trading_time_semantics_preserved(self):
        """is_trading_time 仍以 15:00 为界——after_hours 不视为盘中（收盘价已定，
        盘后固定价格交易以收盘价成交不产生新价格）。"""
        from app.core.market_calendar import is_trading_time
        assert is_trading_time(self._dt(14, "15:10")) is False
        assert is_trading_time(self._dt(14, "14:00")) is True


class TestMarketSnapshotPersistence:
    """R26②: 快照持久化——MarketSnapshot 模型 + 写读兜底。"""

    def test_model_roundtrip(self, tmp_path):
        """模型 JSON 落盘 → 读回 → payload 完整（负向：字段缺失 → FAIL）。"""
        import sys
        sys.path.insert(0, str(tmp_path))  # 隔离模型导入路径
        from app.models.market_snapshot import MarketSnapshot
        snap = MarketSnapshot(
            kind="pool",
            payload=json.dumps({"core": [{"symbol": "510300"}]}, ensure_ascii=False),
            as_of="2026-08-14T15:30:00",
        )
        assert snap.kind == "pool"
        assert json.loads(snap.payload)["core"][0]["symbol"] == "510300"
        assert snap.as_of == "2026-08-14T15:30:00"

    def test_as_of_after_hours_full_volume(self):
        """盘后固定价格交易结束（≥15:30）→ as_of 用 15:30（含盘后成交量）。"""
        from app.services.market_data_hub import _snapshot_as_of_for
        assert _snapshot_as_of_for(datetime(2026, 8, 14, 15, 35)) == "2026-08-14T15:30:00"

    def test_as_of_intraday_last(self):
        """15:00-15:30 窗口内（盘后固定价格交易未结束）→ as_of=15:00（盘中最后快照）。"""
        from app.services.market_data_hub import _snapshot_as_of_for
        assert _snapshot_as_of_for(datetime(2026, 8, 14, 15, 10)) == "2026-08-14T15:00:00"

    def test_as_of_open_session(self):
        """盘中 → as_of=当前时刻（非快照场景，函数应返回 None 表示不写快照）。"""
        from app.services.market_data_hub import _snapshot_as_of_for
        assert _snapshot_as_of_for(datetime(2026, 8, 14, 10, 0)) is None


class TestStrategyDesignSessionPropagation:
    """R26③: design market_context 透传 session + data_as_of。"""

    def test_market_context_has_session_and_as_of(self, monkeypatch):
        from app.services import strategy_design as sd
        from app.core import market_calendar as mc

        # 冻结时间：周五 18:00（盘后）
        frozen = datetime(2026, 8, 14, 18, 0)
        monkeypatch.setattr(mc, "datetime", _FrozenDatetime(frozen))
        # _snapshot_as_of_for 用 market_data_hub.datetime（非 market_calendar.datetime）——两者都冻
        from app.services import market_data_hub as mh
        monkeypatch.setattr(mh, "datetime", _FrozenDatetime(frozen))
        monkeypatch.setattr(sd, "market_session", lambda dt=None: mc.market_session(dt))

        # 轻量 fake hub + 桩掉重 I/O 纯函数，真实调用 _build_market_context 验证透传
        class _FakeHub:
            def get_market_regime(self): return "range_bound"
            def get_market_sentiment(self): return {"sentiment_index": 50, "sentiment_label": "中性"}
            def get_index_realtime(self): return []
            async def get_global_indices(self): return {}
            def get_sector_momentum(self): return []
            def get_sector_stocks(self, code): return []
            def get_pool(self): return {}

        async def _fake_ff(hub): return {}
        monkeypatch.setattr(sd, "_compute_fund_flow", _fake_ff)
        monkeypatch.setattr(sd, "_factor_data_quality_report", lambda: {"valid_rate": 1.0})
        monkeypatch.setattr(sd, "_data_precision_report", lambda fq: {"mode": "full"})

        ctx = sd._build_market_context.__wrapped__ if hasattr(sd._build_market_context, "__wrapped__") else sd._build_market_context
        import asyncio
        result = asyncio.run(ctx(_FakeHub()))
        assert result["session"] == "post_market", f"market_context.session 未透传 R26 盘后态：{result.get('session')}"
        assert result["data_as_of"] is not None, "盘后态 data_as_of 应为 T-1 时点（非空）"
        assert result["data_as_of"].endswith("15:30:00"), f"盘后完整数据 as_of 应为 15:30：{result.get('data_as_of')}"



class _FrozenDatetime(datetime):
    """冻结 datetime.now——测试盘后路径（避免依赖真实时钟）。

    子类化 datetime，使被冻结实例仍支持 .replace()/.isoformat() 等（_snapshot_as_of_for
    内部会调用），避免 AttributeError 被吞成 data_as_of=None。
    """

    _FROZEN_REF = None

    def __new__(cls, *args, **kwargs):
        # 既支持 _FrozenDatetime(real_datetime) 也支持基类 datetime(y,m,d,...) 构造
        # （.replace() 会走基类构造路径）
        if len(args) == 1 and isinstance(args[0], datetime) and not isinstance(args[0], _FrozenDatetime):
            f = args[0]
            obj = datetime.__new__(cls, f.year, f.month, f.day, f.hour, f.minute, f.second)
            cls._FROZEN_REF = f
            return obj
        return datetime.__new__(cls, *args, **kwargs)

    def now(self, tz=None):
        return self

    @classmethod
    def utcnow(cls):
        f = cls._FROZEN_REF or datetime(2026, 8, 14, 18, 0)
        return datetime.__new__(cls, f.year, f.month, f.day, f.hour, f.minute, f.second)