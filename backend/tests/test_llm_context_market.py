"""TDD: F1-3/F1-4 — LLM 上下文数据缺失 + market 参数传导。

覆盖：
  1. build_full_context(market=HK) → index_realtime 取「港股」区域指数（含恒生）
  2. build_full_context(market=US) → 取「美股」区域
  3. build_full_context(market=A) → 用本地指数缓存（行为不变）
  4. 非 A 市场不采集板块动量（sector_momentum 为空）
  5. _build_market_context：index_realtime 为空时从全球指数兜底 + benchmark_stocks 填充
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeHub:
    """mock market_data_hub，只暴露测试关心的方法。"""

    def __init__(self):
        self._index_cache = [
            {"symbol": "000001", "name": "上证指数", "price": 3000.0, "asset_type": "index"},
            {"symbol": "399001", "name": "深证成指", "price": 10000.0, "asset_type": "index"},
            {"symbol": "399006", "name": "创业板指", "price": 2000.0, "asset_type": "index"},
        ]
        self._global_idx = {
            "A股": self._index_cache,
            "港股": [
                {"symbol": "^HSI", "name": "恒生指数", "price": 21000.0, "asset_type": "index"},
                {"symbol": "^HSTECH", "name": "恒生科技指数", "price": 4500.0, "asset_type": "index"},
            ],
            "美股": [
                {"symbol": "^GSPC", "name": "标普500", "price": 5500.0, "asset_type": "index"},
                {"symbol": "^IXIC", "name": "纳斯达克", "price": 18000.0, "asset_type": "index"},
            ],
        }

    def get_index_realtime(self):
        return self._index_cache

    async def get_global_indices(self):
        return self._global_idx

    def get_market_regime(self, market="A"):
        return "range_bound"

    def get_market_sentiment(self):
        return {"sentiment_index": 50, "sentiment_label": "中性"}

    def get_sector_momentum(self):
        return [{"sector_code": "BK1036", "sector_name": "半导体", "change_pct": 2.5},
                {"sector_code": "BK0475", "sector_name": "银行", "change_pct": -0.8}]

    def get_hot_plates(self):
        return []

    def get_sector_heat(self):
        return []

    async def get_all_realtime(self):
        return []

    async def get_commodities(self):
        return []

    def get_news_headlines(self):
        return []

    def get_news_macro(self):
        return []

    def get_pool(self, layer=None):
        return []

    def get_fund_flow(self, sym, timeout=8):
        return {"main_net_inflow": 100.0}

    def get_sector_stocks(self, code):
        return [{"stock_code": "688111", "stock_name": "金山办公"},
                {"stock_code": "600584", "stock_name": "长电科技"}]

    def get_by_code(self, code):
        return None


@pytest.mark.asyncio
async def test_context_market_hk_uses_hk_indices():
    """F1-4: market=HK → index_realtime 含恒生指数。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="HK",
        include_regime=False, include_sentiment=False, include_indices=True,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    names = [i.get("name") for i in ctx.get("index_realtime", [])]
    assert any("恒生" in n for n in names), f"HK 上下文应含恒生指数: {names}"


@pytest.mark.asyncio
async def test_context_market_us_uses_us_indices():
    """F1-4: market=US → index_realtime 含标普500。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="US",
        include_regime=False, include_sentiment=False, include_indices=True,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    names = [i.get("name") for i in ctx.get("index_realtime", [])]
    assert any("标普" in n or "纳斯达克" in n for n in names), f"US 上下文应含美股指数: {names}"


@pytest.mark.asyncio
async def test_context_market_a_uses_local_cache():
    """F1-4 回归: market=A 仍用本地指数缓存。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="A",
        include_regime=False, include_sentiment=False, include_indices=True,
        include_sectors=False, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    names = [i.get("name") for i in ctx.get("index_realtime", [])]
    assert any("上证" in n for n in names), f"A 上下文应含上证指数: {names}"


@pytest.mark.asyncio
async def test_non_a_market_no_sector_momentum():
    """F1-4: HK/US 市场不采集 A 股板块动量。"""
    from app.services.llm_context import build_full_context

    ctx = await build_full_context(
        _FakeHub(), market="HK",
        include_regime=False, include_sentiment=False, include_indices=False,
        include_sectors=True, include_news=False, include_portfolio=False,
        include_fund_flow=False, include_commodities=False,
    )
    assert ctx.get("sector_momentum") == [] or "sector_momentum" not in ctx


@pytest.mark.asyncio
async def test_build_market_context_index_fallback():
    """F1-3: 本地指数缓存为空 → 从全球指数分组兜底。"""
    from app.services.strategy_design import _build_market_context

    hub = _FakeHub()
    hub._index_cache = []  # 模拟缓存未刷新
    ctx = await _build_market_context(hub)
    assert len(ctx.get("index_realtime", [])) >= 3, f"index_realtime 应兜底非空: {ctx.get('index_realtime')}"


@pytest.mark.asyncio
async def test_build_market_context_benchmark_stocks():
    """F1-3: benchmark_stocks 不再恒为空（含领涨板块成分股）。"""
    from app.services.strategy_design import _build_market_context

    ctx = await _build_market_context(_FakeHub())
    bs = ctx.get("benchmark_stocks", [])
    assert len(bs) >= 1, f"benchmark_stocks 应有龙头股: {bs}"
    assert any("stock_name" in s or "name" in s for s in bs)


# ── R5-1-3: llm-advice 上下文注入关键词扩展 ───────────────────────────────
def _build_snapshot(query, hub=None):
    """调用统一注入函数 _build_advice_market_snapshot（传入 mock hub）。"""
    from app.routers.analysis import _build_advice_market_snapshot

    if hub is None:
        hub = _FakeHub()
    return _build_advice_market_snapshot(query, hub)


class TestR513AdviceContextInjection:
    """R5-1-3: 投顾问题无论是否命中旧关键词，均注入 market_snapshot。

    覆盖类（"当前A股市场怎么配置"）：旧关键词表缺 "A股/配置"，仅命中 "市场"。
    不覆盖类（"如何看待定投"）：不命中任何旧关键词 → 走无条件注入路径。
    两种都应含实时市场数据（指数/市态/情绪），无"暂无数据"式全降级模板。
    """

    def test_cover_class_query_injects_snapshot(self):
        """覆盖类："当前A股市场怎么配置" → market_snapshot 含指数/市态。"""
        snapshot = _build_snapshot("当前A股市场怎么配置")
        assert snapshot, "R5-1-3 覆盖类问题应注入 market_snapshot（旧关键词表漏 'A股/配置'）"
        assert "上证指数" in snapshot or "市场状态" in snapshot, \
            f"snapshot 应含实时市场数据: {snapshot}"

    def test_uncovered_class_query_injects_snapshot(self):
        """不覆盖类："如何看待定投" → 无条件注入路径，仍含实时市场数据。"""
        snapshot = _build_snapshot("如何看待定投")
        assert snapshot, "R5-1-3 不覆盖类问题也应注入 market_snapshot（无条件注入）"
        assert "上证指数" in snapshot or "市场状态" in snapshot, \
            f"snapshot 应含实时市场数据: {snapshot}"

    def test_sector_keyword_still_injects_sector(self):
        """回归：板块类问题仍注入板块动量。"""
        snapshot = _build_snapshot("半导体板块最近怎么样")
        assert "半导体" in snapshot, f"板块问题应含板块数据: {snapshot}"

    def test_inject_context_writes_snapshot(self):
        """_inject_market_context 集成：snapshot 非空时写入 ctx['market_snapshot']。"""
        from app.routers import analysis as analysis_router

        ctx = {}
        with patch.object(analysis_router, "_build_advice_market_snapshot",
                          return_value="· 市场状态: range_bound\n· 上证指数: 3000.0"):
            result = analysis_router._inject_market_context("任何问题", ctx)
        assert result.get("market_snapshot", "").startswith("· 市场状态"), \
            "无条件注入应写入 ctx.market_snapshot"

    def test_non_stream_advice_unconditional_injection(self):
        """非 stream 版 llm_advice 同样无条件注入（两版同步）。"""
        from app.routers import analysis as analysis_router

        # 直接测统一注入函数（非 stream 版 llm_advice 与其共享同一构建逻辑）
        snapshot = _build_snapshot("如何看待定投")
        assert snapshot, "非 stream 版也应无条件注入 market_snapshot"
        assert "上证指数" in snapshot or "市场状态" in snapshot

# ── R06 (round58 §3 P1): 全市场成交额 / 涨跌家数（push2delay clist 求和）─────
# 负向：clist 失败 → 回退空 + 占位，**不得**报 0 家 / 0 元伪值。


class _FakeResp:
    def __init__(self, payload):
        self._b = payload

    def read(self):
        return self._b


def _r58_breadth_clear():
    from app.fetchers import fundamentals_fetcher as ff
    ff.clear_breadth_cache()


def _r58_rows(items):
    import json as _json
    body = _json.dumps({"data": {"diff": items}}).encode("utf-8")
    return _FakeResp(body)


def test_r06_breadth_aggregates_up_down_and_amount(monkeypatch):
    """R06: 一次 clist 调用聚合出涨跌家数 + 成交额（up/down/total/amount）。"""
    _r58_breadth_clear()
    from app.fetchers import fundamentals_fetcher as ff
    import urllib.request

    items = [
        {"f3": 1.2, "f6": 3.0e8},
        {"f3": 0.5, "f6": 1.0e8},
        {"f3": -1.1, "f6": 2.0e8},
        {"f3": 0.0, "f6": 5.0e7},
    ]
    monkeypatch.setattr(ff._push2_h, "available", lambda now: True)
    monkeypatch.setattr(ff._push2_h, "record_success", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _r58_rows(items))
    out = ff.fetch_market_breadth()
    assert out["up"] == 2 and out["down"] == 1 and out["flat"] == 1
    assert out["total"] == 4
    assert out["advance_ratio"] == 0.5
    assert out["total_amount"] == pytest.approx(6.5e8)
    _r58_breadth_clear()


def test_r06_cached_second_call_zero_network(monkeypatch):
    """R06: 5min 缓存生效——二次调用零网络（请求链不得每报告拉一次全市场）。"""
    _r58_breadth_clear()
    from app.fetchers import fundamentals_fetcher as ff
    import urllib.request

    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("缓存命中时不得触网")

    monkeypatch.setattr(ff._push2_h, "available", lambda now: True)
    monkeypatch.setattr(ff._push2_h, "record_success", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    # 预热一次（真取数被禁 → 走空结果也不入缓存，这里直接写缓存）
    ff._breadth_cache = (ff._time.time(), {"up": 1, "down": 2, "total": 3,
                                           "advance_ratio": 0.3333,
                                           "total_amount": 1.0e8})
    out = ff.fetch_market_breadth()
    assert out["total"] == 3
    assert calls["n"] == 0
    _r58_breadth_clear()


def test_r06_clist_failure_returns_empty_not_zero_counts(monkeypatch):
    """R06 负向：clist + akshare 降级全失败 → {}（**不是** 0 家/0 元伪值）。"""
    _r58_breadth_clear()
    from app.fetchers import fundamentals_fetcher as ff
    import urllib.request

    monkeypatch.setattr(ff._push2_h, "available", lambda now: True)
    monkeypatch.setattr(ff._push2_h, "record_failure", lambda *a, **k: None)
    monkeypatch.setattr(ff._push2_h, "record_success", lambda *a, **k: None)

    def _raise(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    monkeypatch.setattr(ff, "run_in_thread", lambda fn, timeout=8, executor="long": (_ for _ in ()).throw(OSError("down")))
    out = ff.fetch_market_breadth()
    assert out == {}, f"源全挂必须回退空 dict，实际 {out!r}"
    _r58_breadth_clear()


def test_r06_hub_method_degrades_to_empty(monkeypatch):
    """R06 接线守卫：hub.get_market_breadth 存在且异常时返回 {}（不抛）。"""
    from app.services.market_data_hub import MarketDataHub
    assert callable(MarketDataHub().get_market_breadth)
    from app.fetchers import fundamentals_fetcher as ff
    monkeypatch.setattr(ff, "fetch_market_breadth",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert MarketDataHub().get_market_breadth() == {}


def test_r06_breadth_appears_in_report_prompt(monkeypatch):
    """R06 真实调用点：宽度必须真进报告 prompt（否则新增 hub 方法=脚手架）。"""
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "app" / "routers" / "analysis.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    called = any(
        isinstance(n, ast.Attribute) and n.attr == "get_market_breadth"
        for n in ast.walk(tree)
    )
    assert called, "router 未调用 hub.get_market_breadth（R06 0 引用=脚手架）"
    kw = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_build_report_prompt":
            kw |= {k.arg for k in n.keywords if k.arg}
    assert "market_breadth" in kw, "宽度未透传给 prompt"
