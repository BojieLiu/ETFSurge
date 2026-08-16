"""round25 R40: 盘后无动量注入——收盘快照「写了不读」+ 首启空窗。

问题（round25 §2.3 实证）：get_sector_momentum() 只返内存缓存（120s TTL）或 []，
从不读已落盘的 `sector_momentum` 快照（写入侧 _persist_snapshot_after_refresh 盘后
已落盘）→ 盘后缓存超时 + live 源失败时动量静默变 []；pool 有读取路径而 sector_momentum
无（「写了不读」）。且快照只在成功刷新时写，收盘后首启时 live 源失败则写空壳/缺失。

修复（round25 R40-a/b）：
- R40-a: 缓存过期/空 且 post_market/after_hours → _load_latest_snapshot_sync("sector_momentum")
  回退（注入收盘动量）；盘中缓存失效不回退快照（避免昨日收盘冒充盘中实时）；
- R40-b: _persist_snapshot_after_refresh 放宽——sector_momentum 非空即落盘（盘中/收盘
  任一成功刷新都留 last-good 快照，封堵首启空窗）；空 [] 不写防空壳。
"""

import time
from unittest.mock import patch

import pytest

from app.services import market_data_hub as mh


class TestGetSectorMomentumSnapshotFallback:
    """R40-a: 读取侧快照兜底。"""

    def test_fresh_cache_no_snapshot_read(self, monkeypatch):
        """缓存新鲜（<120s）→ 直接返缓存，不读快照（负向：读了 → FAIL）。"""
        hub = mh.MarketDataHub()
        hub._sector_momentum_cache = [{"name": "半导体", "change_pct": 2.1}]
        hub._sector_momentum_cache_ts = time.time()
        monkeypatch.setattr(mh, "_load_latest_snapshot_sync",
                            lambda kind: (_ for _ in ()).throw(AssertionError("不应读快照")))
        out = hub.get_sector_momentum()
        assert len(out) == 1

    def test_post_market_cold_cache_reads_snapshot(self, monkeypatch):
        """盘后 + 缓存空 + 快照有数据 → 返回快照（非空）。"""
        hub = mh.MarketDataHub()
        hub._sector_momentum_cache = None
        hub._sector_momentum_cache_ts = 0
        snap = [{"name": "半导体", "change_pct": 2.1},
                {"name": "券商", "change_pct": 1.4}]
        monkeypatch.setattr(mh, "market_session", lambda dt=None: "post_market")
        monkeypatch.setattr(mh, "_load_latest_snapshot_sync", lambda kind: snap)
        out = hub.get_sector_momentum()
        assert len(out) == 2, "盘后快照兜底必须返回非空（R40-a）"
        assert out[0]["name"] == "半导体"
        # 兜底后缓存已填充（后续调用不重复读盘）
        assert hub._sector_momentum_cache == snap

    def test_intraday_cold_cache_returns_empty(self, monkeypatch):
        """盘中 + 缓存失效 → 返 []（负向：昨日快照冒充盘中实时 → FAIL）。"""
        hub = mh.MarketDataHub()
        hub._sector_momentum_cache = None
        hub._sector_momentum_cache_ts = 0
        snap = [{"name": "半导体", "change_pct": 2.1}]
        monkeypatch.setattr(mh, "market_session", lambda dt=None: "open")
        monkeypatch.setattr(mh, "_load_latest_snapshot_sync", lambda kind: snap)
        out = hub.get_sector_momentum()
        assert out == [], "盘中缓存失效不得回退快照（避免昨日收盘冒充实时）"

    def test_snapshot_empty_stays_empty(self, monkeypatch):
        """盘后但快照为空/缺失 → 保持 []（诚实，不编造）。"""
        hub = mh.MarketDataHub()
        hub._sector_momentum_cache = None
        hub._sector_momentum_cache_ts = 0
        monkeypatch.setattr(mh, "market_session", lambda dt=None: "post_market")
        monkeypatch.setattr(mh, "_load_latest_snapshot_sync", lambda kind: None)
        out = hub.get_sector_momentum()
        assert out == []


class TestPersistSnapshotAfterRefresh:
    """R40-b: 写入侧放宽——sector_momentum 非空即落盘；空 [] 不写。"""

    @pytest.mark.asyncio
    async def test_intraday_nonempty_sector_persisted(self, monkeypatch):
        """盘中刷新成功且 sector_momentum 非空 → 落盘（R40-b 放宽，封堵首启空窗）。"""
        hub = mh.MarketDataHub()
        hub._sector_momentum_cache = [{"name": "半导体", "change_pct": 2.1}]
        hub._sector_momentum_cache_ts = time.time()
        calls = []
        monkeypatch.setattr(mh, "market_session", lambda dt=None: "open")
        monkeypatch.setattr(mh, "_snapshot_as_of_for", lambda dt=None: "2026-08-14T15:30:00")
        def _fake_persist(kind, payload, as_of):
            calls.append((kind, payload, as_of))
        monkeypatch.setattr(mh, "_persist_snapshot_sync", _fake_persist)
        await hub._persist_snapshot_after_refresh({})
        kinds = [c[0] for c in calls]
        assert "sector_momentum" in kinds, "盘中非空 sector_momentum 也应落盘（R40-b）"
        assert "pool" not in kinds, "pool 快照保持盘后语义（盘中不写）"

    @pytest.mark.asyncio
    async def test_empty_sector_not_persisted(self, monkeypatch):
        """sector_momentum 空 [] → 不落盘（防空壳污染兜底）。"""
        hub = mh.MarketDataHub()
        hub._sector_momentum_cache = None
        hub._sector_momentum_cache_ts = 0
        calls = []
        monkeypatch.setattr(mh, "market_session", lambda dt=None: "post_market")
        monkeypatch.setattr(mh, "_snapshot_as_of_for", lambda dt=None: "2026-08-14T15:30:00")
        def _fake_persist(kind, payload, as_of):
            calls.append(kind)
        monkeypatch.setattr(mh, "_persist_snapshot_sync", _fake_persist)
        await hub._persist_snapshot_after_refresh({})
        assert "sector_momentum" not in calls, "空 [] 不写快照（防空壳）"

    @pytest.mark.asyncio
    async def test_post_market_pool_and_sector_both_persisted(self, monkeypatch):
        """盘后 pool + sector_momentum 均落盘（既有行为保持）。"""
        hub = mh.MarketDataHub()
        hub._sector_momentum_cache = [{"name": "半导体", "change_pct": 2.1}]
        hub._sector_momentum_cache_ts = time.time()
        calls = []
        monkeypatch.setattr(mh, "market_session", lambda dt=None: "post_market")
        monkeypatch.setattr(mh, "_snapshot_as_of_for", lambda dt=None: "2026-08-14T15:30:00")
        def _fake_persist(kind, payload, as_of):
            calls.append(kind)
        monkeypatch.setattr(mh, "_persist_snapshot_sync", _fake_persist)
        await hub._persist_snapshot_after_refresh({"core": [{"symbol": "510300"}]})
        assert set(calls) == {"pool", "sector_momentum"}