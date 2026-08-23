# -*- coding: utf-8 -*-
"""round34 R105: M7/P1-1 强制核心锚未落地防御型方案（降级态被后置工序剥除）。

根因（round34 §4.3 两段式缺陷）：
- 段一（池层静默丢弃）：扫描源降级时 `etf_scanner` 成交额/规模门禁把真锚当
  「幽灵锚」剔除，`ensure_mandatory` 的 found=None 分支**静默跳过、无任何 WARNING**
  （pool_balancing.py 旧实现）→ 锚从未进入候选池。
- 段二（设计层后置剥除）：allocate() 强制注入的锚在警告计算后被剥除——头号嫌疑
  `remove_stale_candidates`（factor_matrix 缺 price/return 即逐标的剔除，周末降级态
  触发）；备选 P1-5 gate（三源拿不到涨跌 → 核心权重清零）。

修复：A'-1/A'-2 对 MANDATORY_CODES 豁免删除/清零（WARNING 标注 degraded，
对齐 MANDATORY_FLOOR「强制锚永不被削减」哲学）；B' ensure_mandatory 静默分支改
WARNING + 静态元数据兜底注入；C' etf_scanner 门禁对核心锚白名单豁免。

无网络：纯函数断言 + monkeypatch（scanner 实时补查 mock 离线）。
"""
import logging

import pytest

from app.engine.pool_balancing import ensure_mandatory
from app.engine.risk_controls import remove_stale_candidates


class TestR105RemoveStaleKeepsAnchors:
    """A'-1: remove_stale_candidates 对强制锚豁免删除。"""

    def _strategies(self):
        return [{
            "profile": "defensive",
            "allocations": [
                {"symbol": "159338", "name": "中证A500ETF", "weight": 0.20, "layer": "core"},
                {"symbol": "512800", "name": "银行ETF", "weight": 0.10, "layer": "core"},
                {"symbol": "159915", "name": "创业板ETF", "weight": 0.15, "layer": "core"},
            ],
        }]

    def test_anchor_without_data_kept_normal_stale_removed(self, caplog):
        """缺数据的锚保留（degraded WARNING）；普通缺数据标的仍被剔除（负向防豁免扩大化）。"""
        # 降级态：仅 159915 有行情——all_stale 守卫不触发（有存活标的），逐标的判定生效
        factor_matrix = {"159915": {"price": 3.5}}
        with caplog.at_level(logging.WARNING, logger="app.engine.risk_controls"):
            result = remove_stale_candidates(self._strategies(), factor_matrix)

        syms = [a["symbol"] for a in result[0]["allocations"]]
        assert "159338" in syms, f"强制锚缺数据必须保留（degraded），实际 {syms}"
        assert "512800" not in syms, f"普通缺数据标的应照常剔除（防豁免扩大化），实际 {syms}"
        assert "159915" in syms
        anchor_warnings = [r for r in caplog.records if "mandatory anchor" in r.getMessage()]
        assert any("159338" in r.getMessage() for r in anchor_warnings), (
            f"锚保留必须带 degraded WARNING，实际 {[r.getMessage() for r in caplog.records]}"
        )

    def test_anchor_with_data_unaffected(self):
        """正路回归：锚有数据时不触发豁免分支（无 WARNING、原样保留）。"""
        factor_matrix = {
            "159338": {"price": 1.02},
            "512800": {"price": 0.98},
            "159915": {"price": 3.5},
        }
        result = remove_stale_candidates(self._strategies(), factor_matrix)
        syms = [a["symbol"] for a in result[0]["allocations"]]
        assert set(syms) == {"159338", "512800", "159915"}

    def test_all_stale_guard_still_wins(self):
        """负向：全部标的缺数据时 R77 全删保护仍优先（整段跳过，锚与普通标的一并保留）。"""
        result = remove_stale_candidates(self._strategies(), {})
        syms = [a["symbol"] for a in result[0]["allocations"]]
        assert set(syms) == {"159338", "512800", "159915"}


class TestR105EnsureMandatoryStaticInjection:
    """B': ensure_mandatory 在扫描 flat 缺锚时不再静默跳过——WARNING + 静态条目注入。"""

    def test_missing_anchor_injected_statically(self, caplog):
        pool = {"core": [], "satellite": [], "defense": []}
        flat = [{"symbol": "159915", "name": "创业板ETF"}]  # 扫描结果不含任何锚

        with caplog.at_level(logging.WARNING, logger="app.engine.pool_balancing"):
            ensure_mandatory(pool, flat)

        core_syms = {e["symbol"] for e in pool["core"]}
        assert {"510300", "159338"} <= core_syms, (
            f"flat 缺锚时应静态注入核心双锚，实际 core={sorted(core_syms)}"
        )
        meta_300 = next(e for e in pool["core"] if e["symbol"] == "510300")
        assert meta_300.get("tracked_index") == "沪深300"
        assert meta_300.get("layer") == "core"
        injected_logs = [r for r in caplog.records if "injecting static entry" in r.getMessage()]
        assert any("510300" in r.getMessage() for r in injected_logs), (
            f"静态注入必须带 WARNING（段一缺陷=静默跳过），实际 "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_anchor_present_in_flat_uses_scan_entry_not_static(self):
        """flat 有锚时行为不变：注入的是扫描条目（含实时字段），非静态兜底。"""
        pool = {"core": [], "satellite": [], "defense": []}
        flat = [{"symbol": "510300", "name": "沪深300ETF", "amount": 2.5e9,
                 "fund_scale": 900.0}]
        ensure_mandatory(pool, flat)
        entry = next(e for e in pool["core"] if e["symbol"] == "510300")
        assert entry.get("amount") == 2.5e9, "flat 命中时应保留扫描条目的实时字段"

    def test_defense_anchor_without_meta_warns_only(self, caplog):
        """防御锚（无静态元数据）缺锚时只 WARNING 不注入（不硬凑假条目）。"""
        pool = {"core": [], "satellite": [], "defense": []}
        flat = [{"symbol": "159915", "name": "创业板ETF"}]
        with caplog.at_level(logging.WARNING, logger="app.engine.pool_balancing"):
            ensure_mandatory(pool, flat)
        defense_syms = [e["symbol"] for e in pool["defense"]]
        assert "518880" not in defense_syms, "无元数据锚不得伪造注入"
        warns = [r for r in caplog.records if "518880" in r.getMessage()]
        assert warns, "缺失的防御锚必须有 WARNING 可观测"


class TestR105ScannerAnchorWhitelist:
    """C': etf_scanner 成交额/规模门禁对核心锚白名单豁免。"""

    @pytest.fixture(autouse=True)
    def _offline_recheck(self, monkeypatch):
        """存疑成交额实时补查 mock 为离线（返回空 map → 全部过滤）——
        保证「普通低成交标的被剔」断言确定性且测试零网络。"""
        import app.fetchers.etf_scanner as scanner

        monkeypatch.setattr(scanner, "_real_amount_override",
                            lambda codes: {})

    def _raw_rows(self):
        return [
            {"代码": "159338", "名称": "中证A500ETF", "成交额": 500_000,
             "流通市值": 55.0},   # 低成交额真锚
            {"代码": "510300", "名称": "沪深300ETF", "成交额": 2_000_000_000,
             "流通市值": 0.5},    # 成交额正常但规模门禁命中（降级态快照缺规模）
            {"代码": "512800", "名称": "银行ETF", "成交额": 500_000,
             "流通市值": 30.0},   # 普通低成交标的
            {"代码": "511090", "名称": "30年国债ETF", "成交额": 400_000,
             "流通市值": 20.0},   # 非白名单防御锚——照常走存疑补查（离线→被剔）
        ]

    def test_anchor_passes_amount_and_scale_gates(self):
        out = filter_etfs_wrapper(self._raw_rows())
        syms = [e["symbol"] for e in out]
        assert "159338" in syms, "低成交额真锚应经白名单放行（幽灵锚防线不得误杀）"
        assert "510300" in syms, "规模门禁对核心锚同样豁免"

    def test_non_anchor_low_amount_still_filtered(self):
        out = filter_etfs_wrapper(self._raw_rows())
        syms = [e["symbol"] for e in out]
        assert "512800" not in syms, "普通低成交标的必须照常过滤（防白名单扩大化）"
        assert "511090" not in syms, "非白名单成员不受豁免保护"


class TestR105MergeSubstituteKeepsAnchors:
    """R105 实施轮发现（剥除洋葱第三层）：_merge_substitute_family（R48 同族合并）
    曾把 {510300, 159338, 510050}（大盘宽基族）合并留一、保留最高权重者并将双锚
    从 allocs **移除** → 防御型核心缺锚（M7 defensive FAIL 真凶）。修复：锚豁免
    合并移除；全锚同族整组豁免；非锚冗余合并行为不变。"""

    def test_wide_basis_merge_keeps_both_anchors(self):
        from app.engine.allocation_engine import _merge_substitute_family

        allocs = [
            {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300",
             "layer": "core", "weight": 0.05},
            {"symbol": "159338", "name": "中证A500ETF", "tracked_index": "中证A500",
             "layer": "core", "weight": 0.05},
            {"symbol": "510050", "name": "上证50ETF", "tracked_index": "上证50",
             "layer": "core", "weight": 0.2075},
            {"symbol": "512890", "name": "红利低波ETF", "tracked_index": "红利",
             "layer": "core", "weight": 0.15},
        ]
        merges = _merge_substitute_family(allocs)
        syms = [a["symbol"] for a in allocs]
        assert {"510300", "159338"} <= set(syms), (
            f"强制锚不得被同族合并移除，实际 {syms}（merges={merges}）"
        )

    def test_non_anchor_redundancy_still_merged(self):
        """负向防豁免扩大化：无锚同族冗余照常合并留一。"""
        from app.engine.allocation_engine import _merge_substitute_family

        allocs = [
            {"symbol": "588200", "name": "科创芯片ETF", "tracked_index": "科创芯片",
             "layer": "satellite", "weight": 0.08},
            {"symbol": "588170", "name": "科创半导体设备ETF", "tracked_index": "科创半导体设备",
             "layer": "satellite", "weight": 0.05},
        ]
        merges = _merge_substitute_family(allocs)
        syms = [a["symbol"] for a in allocs]
        assert len(syms) == 1 and merges, f"同族无锚冗余应合并留一，实际 {syms}"
        kept = next(a for a in allocs)
        assert kept.get("weight") == pytest.approx(0.13), (
            f"被移除方权重应并入保留方，实际 {kept.get('weight')}"
        )


class TestR105EndToEndPipelineGuard:
    """round34 实施轮收口守卫：强制锚必须在 generate_enhanced_design **全管线**存活。

    动机：剥除器分布在 allocate 之后的管线各处（remove_stale/P1-5 gate/
    _merge_substitute_family 同族合并），只测 allocate 层抓不到后置剥除——本轮
    三层洋葱实证。本用例用离线 FakeHub 走完整设计管线（周末降级态形态），
    断言 M7/P1-1 门禁语义在最终 etfs 上成立。
    """

    def _build(self, monkeypatch):
        import asyncio

        from app.services import strategy_design as sd

        # 周末降级态形态：核心层含双锚（无任何行情）+ 有数据标的 +
        # 无数据非锚（P1-5 应清零它而非锚——负向防豁免扩大化）
        def _core(sym, name, tidx):
            return {"symbol": sym, "name": name, "tracked_index": tidx,
                    "layer": "core", "industry": "宽基指数"}

        pool = {
            "core": [
                _core("510300", "沪深300ETF", "沪深300"),
                _core("159338", "中证A500ETF", "中证A500"),
                _core("510050", "上证50ETF", "上证50"),
                _core("512890", "红利低波ETF", "红利低波"),
                _core("510500", "中证500ETF", "中证500"),
                _core("512010", "医药ETF", "医药"),
            ],
            "satellite": [{"symbol": "588200", "name": "科创芯片ETF",
                           "tracked_index": "科创芯片", "layer": "satellite"}],
            "defense": [{"symbol": "518880", "name": "黄金ETF",
                         "tracked_index": "黄金", "layer": "defense"}],
        }
        anchors = {"510300", "159338"}
        zero_target = "512010"   # 有 price/return（活过 remove_stale）但无涨跌数据
        fm = {}
        for layer in pool.values():
            for it in layer:
                sym = it["symbol"]
                if sym in anchors:
                    fm[sym] = {}
                elif sym == zero_target:
                    # 高技术分保证入选核心层；无涨跌数据 → P1-5 应清零它（非锚不豁免）
                    fm[sym] = {
                        "price": 1.0, "etf.price": 1.0,
                        "return_1m": 0.01, "etf.return_1m": 0.01,
                        "technical.rsi.rsi_14": 3.0, "momentum.return_20d": 2.0,
                    }
                else:
                    fm[sym] = {
                        "price": 1.0, "etf.price": 1.0,
                        "return_1m": 0.01, "etf.return_1m": 0.01,
                        "technical.rsi.rsi_14": 0.4,
                    }

        class _FakeHub:
            _degraded = False

            def _is_market_hours(self):
                return False

            async def refresh(self):
                return None

            def get_pool(self, layer=None):
                return pool if layer is None else pool.get(layer, [])

            def get_factor_matrix(self):
                return fm

            def get_market_regime(self):
                return "range_bound"

            def get_market_sentiment(self):
                return {"sentiment_index": 50}

            def get_index_realtime(self):
                return []

            async def get_global_indices(self):
                return {}

            def get_sector_momentum(self):
                return []

            def get_sector_stocks(self, code):
                return []

            def get_by_code(self, code):
                # 无涨跌数据标的拿不到涨跌/价格（触发 A'-2 与 P1-5 分支）
                if code in anchors or code == zero_target:
                    return {}
                return {"change_pct": 1.0, "price": 1.0}

            async def get_asset_realtime(self, code, market):
                if code in anchors or code == zero_target:
                    return None
                return {"price": 1.0}

        monkey_targets = {
            "market_data_hub": _FakeHub(),
            "market_session": lambda dt=None: "after_hours",
            "_compute_fund_flow": None,      # 下面替换为 async stub
            "_kline_change_pct": lambda hub, code: None,
            "_snapshot_change_pct": lambda code: None,
            "_correlation_medians_for": lambda allocs, cands: {},
            "_correlation_matrix_for": lambda allocs, cands: {},
        }
        for attr, val in monkey_targets.items():
            if attr == "_compute_fund_flow":
                async def _ff(hub):
                    return {}
                monkeypatch.setattr(sd, attr, _ff, raising=False)
            else:
                monkeypatch.setattr(sd, attr, val, raising=False)
        # 函数内懒加载 `from ..services.market_data_hub import market_data_hub`
        # 拿的是真实单例——两处命名空间都要替换（r69 先例）
        import app.services.market_data_hub as mh_mod
        monkeypatch.setattr(mh_mod, "market_data_hub", _FakeHub(), raising=False)

        async def _run():
            return await sd.generate_enhanced_design(capital=100000)

        return asyncio.run(_run())

    def test_anchors_survive_full_pipeline_all_profiles(self, monkeypatch):
        out = self._build(monkeypatch)
        strategies = out.get("strategies") or []
        assert len(strategies) == 3
        a500_seen = False
        for s in strategies:
            prof = s.get("id") or s.get("profile")
            core = [e for e in (s.get("etfs") or []) if e.get("layer") == "core"]
            syms = {e.get("symbol") for e in core}
            assert syms & {"510300", "159338"}, (
                f"{prof} 核心层缺宽基锚（管线内被剥除），实际 {sorted(syms)}"
            )
            if "159338" in syms:
                a500_seen = True
            # 数量下限语义（M7）：核心层条目数 ∈ [3,5]
            assert 3 <= len(core) <= 5, f"{prof} 核心层数 {len(core)} ∉ [3,5]"
            # 合并标记不得落在锚上
            for e in core:
                if e.get("symbol") in ("510300", "159338"):
                    assert not e.get("merged"), f"锚被打上 merged（同族合并未豁免）"
        assert a500_seen, "P1-1：至少一方案核心层须含中证A500(159338)"

    # 注：P1-5「清零非锚」的负向防扩大化由 TestR105RemoveStaleKeepsAnchors 与
    # scanner 用例覆盖；管线层无法复现该场景——双锚无数据时核心命中率必 <50%，
    # gate 整体关闭（产品行为：降级态跳过清零，锚与非锚一并保留）。


def filter_etfs_wrapper(raw):
    from app.fetchers.etf_scanner import filter_etfs

    return filter_etfs([dict(r) for r in raw])
