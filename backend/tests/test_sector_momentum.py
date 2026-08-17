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
        # 防污染：清空磁盘快照兜底，确保「缓存=None + 无快照」即空 []（否则会读到历史快照被误判非空）。
        monkeypatch.setattr(mh, "_load_latest_snapshot_sync", lambda kind: None)
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


# ── folded from test_round27_r46_momentum_source.py ──
"""round27 R46: 板块动量数据源修正（反假完成负向测试）。

根因（doc §15.1 R46 / Round 9 更正）：`_compute_industry_momentum` / `_compute_concept_momentum`
旧实现用 akshare `stock_board_industry_name_em`（硬编码 push2.eastmoney.com，被 EM 域名级
风控 ProxyError 阻断）→ live 源失败 → 首启无快照可写（R40 首启空窗）。

修复：改调项目自有 `fetch_em_industry_sectors` / `fetch_em_concept_sectors`
（EM_PUSH_HOST=push2delay，实测 496 行可用）。akshare 仅作防御性兜底（push2delay 也空时）。

验收（负向）：
① mock akshare 阻断（ProxyError）+ 注入 push2delay 496 行 → `compute_sector_momentum`
   非 []（禁再「akshare 阻断即返空」）；
② 证明主源是项目自有 push2delay fetcher（akshare 未被主路径调用）；
③ push2delay 也失败时回退 akshare，akshare 再失败 → 诚实返回 []（不崩溃、不伪造）。
"""
import asyncio
from unittest.mock import MagicMock

from app.services import market_trends
from app.services.market_trends import (
    compute_sector_momentum,
    _compute_industry_momentum,
    _compute_concept_momentum,
)


def _em_rows(n: int, prefix: str) -> list:
    """模拟 push2delay fetcher 返回的行（字段与 sector_fetcher.fetch_em_* 兼容）。"""
    rows = []
    for i in range(n):
        pct = 3.0 - 0.01 * i  # 递减涨跌幅，便于排序
        rows.append({
            "sector_code": f"BK{prefix}{i:04d}",
            "sector_name": f"{prefix}板块{i}",
            "change_pct": pct,
            "main_inflow": 1000.0 - i * 10,
            "up_count": 10,
            "down_count": 5,
            "total_market": 1e9,
            "lead_stock_name": "", "lead_stock_code": "", "lead_stock_chg": None,
        })
    return rows


def test_akshare_blocked_but_push2delay_works():
    """R46 负向①+②：akshare 阻断 + push2delay 返 496 行 → 动量非 []，且不依赖 akshare。"""
    proxy_err = ConnectionError("ProxyError: push2 blocked")

    em_ind = _em_rows(496, "IND")
    em_con = _em_rows(200, "CON")

    # akshare 一旦被调用就抛 ProxyError —— 若主路径仍走 akshare，会走兜底且失败
    with patch(
        "app.fetchers.sector_fetcher.fetch_em_industry_sectors",
        return_value=em_ind,
    ), patch(
        "app.fetchers.sector_fetcher.fetch_em_concept_sectors",
        return_value=em_con,
    ), patch("akshare.stock_board_industry_name_em", side_effect=proxy_err), patch(
        "akshare.stock_board_concept_name_em", side_effect=proxy_err,
    ):
        result = asyncio.run(compute_sector_momentum(10))

    assert isinstance(result, list) and len(result) > 0, (
        f"push2delay 有数据但 compute_sector_momentum 返空 → R46 回退 akshare 失败路径"
    )
    # 验证字段形状（as_of 诚实标注由上层处理；此处只验 live 源真的产出了数据）
    assert any(r.get("sector") and isinstance(r.get("change_pct"), float) for r in result), (
        "返回的板块行缺少 sector/change_pct 字段"
    )
    # 验证主源确为 push2delay（行业板块应有 push2delay 行名）
    names = {r["sector"] for r in result}
    assert "IND板块0" in names, "主源未使用 push2delay fetcher 数据"


def test_push2delay_fail_falls_back_to_akshare_then_graceful():
    """R46 ③：push2delay 失败（返回 None）→ 回退 akshare；akshare 也失败 → 诚实 []，不崩。"""
    proxy_err = ConnectionError("push2 & akshare both blocked")

    with patch(
        "app.fetchers.sector_fetcher.fetch_em_industry_sectors",
        return_value=None,
    ), patch(
        "app.fetchers.sector_fetcher.fetch_em_concept_sectors",
        return_value=None,
    ), patch("akshare.stock_board_industry_name_em", side_effect=proxy_err), patch(
        "akshare.stock_board_concept_name_em", side_effect=proxy_err,
    ):
        result = asyncio.run(compute_sector_momentum(10))

    # 双源全部失败 → 诚实返回空（不得抛异常、不得伪造假数据）
    assert result == [], f"双源失败应诚实返 []，实际 {result!r}"


def test_industry_momentum_uses_push2delay_primary():
    """R46 ②（单元级）：`_compute_industry_momentum` 主路径调用 push2delay fetcher。"""
    em_ind = _em_rows(15, "IND")
    with patch(
        "app.fetchers.sector_fetcher.fetch_em_industry_sectors",
        return_value=em_ind,
    ) as mocked, patch("akshare.stock_board_industry_name_em", side_effect=ConnectionError("blocked")):
        rows = asyncio.run(_compute_industry_momentum(15))

    mocked.assert_called_once()
    assert len(rows) == 15
    assert rows[0]["sector"] == "IND板块0"
    # 按 change_pct 降序排序
    assert all(
        rows[i]["change_pct"] >= rows[i + 1]["change_pct"] for i in range(len(rows) - 1)
    )