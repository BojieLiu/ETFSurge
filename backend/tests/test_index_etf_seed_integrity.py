"""R54 (round27): 指数种子表混入 ETF + 彭博代码重复的修复验证。

问题（round27 §15.1）：`sync_indices_meta._STATIC_EXTRA_INDICES` 美股段混入 3 条 ETF
（SPY=SPDR标普500ETF、SOXX=iShares半导体ETF、XLB=SPDR材料指数ETF，均 `index_type=price`
冒充指数）+ 3 条重复（^GSPC/^DJI/^IXIC 与 SPX/DJI/IXIC 重复，仅「彭博代码」后缀）；而
SOXX/XLB 不在 `market_service.HKUS_ETF_MAP`（美股 ETF 基座仅 SPY/QQQ/IVV/...）→ 个股/ETF
tab 搜 SOXX/XLB 反而搜不到（双向错位）。

修复：
① `_STATIC_EXTRA_INDICES` 删 SPY/SOXX/XLB 三条 ETF 行 + ^GSPC/^DJI/^IXIC 三条重复行
   （保留 SPX/DJI/IXIC）；
② `HKUS_ETF_MAP` 补 SOXX/XLB（个股/ETF tab 正确命中）；
③ `indices_meta` 同步后指数搜索不含 `type=etf` 条目。

负向断言（抓假）：
- 美股指数搜索「标普」只出 SPX 一条（不含 SPY/^GSPC）；
- 个股/ETF 搜索 SOXX/XLB 命中（type=etf）；
- `_STATIC_EXTRA_INDICES` 无 `index_type` 伪装的 ETF 条目、无 ^GSPC/^DJI/^IXIC 重复。
"""

import pytest
from unittest.mock import patch

from app.routers import market as market_router
from app.services import market_service as ms


# ── 1. 种子表结构断言（负向） ────────────────────────────────────────────────

def test_static_indices_no_etf_disguised_as_index():
    """种子表不得用 index_type=price 把 ETF 伪装成指数（SPY/SOXX/XLB）。"""
    from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES

    etf_symbols = {"SPY", "SOXX", "XLB"}
    for s in _STATIC_EXTRA_INDICES:
        assert s["symbol"] not in etf_symbols, (
            f"ETF {s['symbol']}（{s['name']}）不应在指数种子表，应移入 HKUS_ETF_MAP"
        )


def test_static_indices_no_bloomberg_code_duplicates():
    """种子表不得含 ^GSPC/^DJI/^IXIC 彭博代码重复行。"""
    from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES

    dup = {"^GSPC", "^DJI", "^IXIC"}
    syms = {s["symbol"] for s in _STATIC_EXTRA_INDICES}
    overlap = dup & syms
    assert not overlap, f"种子表不应含彭博代码重复行: {overlap}"


def test_static_indices_us_core_present():
    """美股核心指数（SPX/DJI/IXIC）仍入种子表（P0-22 搜索依赖）。"""
    from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES

    us = [s for s in _STATIC_EXTRA_INDICES if s.get("market") == "US"]
    assert any(s["symbol"] == "SPX" for s in us)
    assert any(s["symbol"] == "DJI" for s in us)
    assert any(s["symbol"] == "IXIC" for s in us)


# ── 2. 美股 ETF 基座断言（负向/正向） ─────────────────────────────────────────

def test_hkus_etf_map_contains_soxx_xlb():
    """SOXX/XLB 必须入 HKUS_ETF_MAP（个股/ETF tab 命中）。"""
    syms = {e["symbol"] for e in ms.HKUS_ETF_MAP}
    assert "SOXX" in syms, "R54: SOXX 必须入 HKUS_ETF_MAP"
    assert "XLB" in syms, "R54: XLB 必须入 HKUS_ETF_MAP"


def test_hkus_etf_map_soxx_xlb_us_market():
    """SOXX/XLB 在基座中 market=US，且被识别为 ETF（type=etf）。"""
    for sym in ("SOXX", "XLB"):
        entry = next(e for e in ms.HKUS_ETF_MAP if e["symbol"] == sym)
        assert entry["market"] == "US"
        assert sym in ms._HKUS_ETF_SYMBOLS, "ETF 符号集合应包含 SOXX/XLB（type=etf 判定）"


# ── 3. 搜索行为断言（mock 种子表后断言） ─────────────────────────────────────

class _Idx:
    """模拟 indices_meta 行（sync 后写入）。"""

    def __init__(self, symbol, name, market):
        self.symbol = symbol
        self.name = name
        self.market = market
        self.pinyin = ""
        self.first_letter = ""
        self.is_active = True


class _IdxSession:
    """按 symbol/name ilike + market where 过滤的 fake async session。"""

    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        compiled = stmt.compile()
        params = compiled.params
        kw = None
        for v in params.values():
            if isinstance(v, str) and "%" in v:
                kw = v.strip("%")
                break
        market = None
        for v in params.values():
            if v in ("US", "HK", "A"):
                market = v
                break
        out = []
        for r in self._rows:
            if market is not None and r.market != market:
                continue
            if kw and kw.lower() not in r.symbol.lower() and kw.lower() not in r.name.lower():
                continue
            out.append(r)
        return _IdxResult(out)


class _IdxResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _us_index_rows_from_static():
    """从 _STATIC_EXTRA_INDICES 派生 US 指数行（等价于 sync 后 indices_meta 内容）。"""
    from app.fetchers.sync_indices_meta import _STATIC_EXTRA_INDICES

    return [_Idx(s["symbol"], s["name"], s["market"])
            for s in _STATIC_EXTRA_INDICES if s.get("market") == "US"]


@pytest.mark.asyncio
async def test_us_index_search_biaopu_only_spx(monkeypatch):
    """美股指数搜索「标普」只出 SPX（负向：混入 SPY/^GSPC → FAIL）。"""
    rows = _us_index_rows_from_static()
    monkeypatch.setattr(market_router, "async_session", lambda: _IdxSession(rows))
    # 阻断 akshare 兜底（保证断言仅由表数据决定）
    monkeypatch.setattr(
        market_router, "_search_indices_akshare_fallback",
        lambda kw, m: (_ for _ in ()).throw(AssertionError("本地命中不应触网")),
    )
    result = await market_router._search_indices("标普", market="US")
    syms = [r["symbol"] for r in result]
    assert syms == ["SPX"], (
        f"美股指数搜「标普」应只返回 SPX，实得 {syms}（含 ETF/彭博重复即失败）"
    )


@pytest.mark.asyncio
async def test_us_index_search_no_etf_type(monkeypatch):
    """indices_meta 同步后，美股指数搜索不得返回 type=etf 的 ETF 条目。"""
    rows = _us_index_rows_from_static()
    monkeypatch.setattr(market_router, "async_session", lambda: _IdxSession(rows))
    monkeypatch.setattr(
        market_router, "_search_indices_akshare_fallback",
        lambda kw, m: (_ for _ in ()).throw(AssertionError("本地命中不应触网")),
    )
    result = await market_router._search_indices("", market="US")
    assert not any(r["type"] == "etf" for r in result), (
        f"指数搜索不得含 type=etf 条目: {result}"
    )


@pytest.mark.asyncio
async def test_etf_tab_search_soxx_xlb_hit(monkeypatch):
    """个股/ETF tab 搜 SOXX/XLB 命中且 type=etf（无需网络，纯静态基座）。"""
    from app.services.market_service import search_hk_us

    # search_hk_us 静态基座恒有；include_stocks=False + enrich=False 不触网
    for kw in ("SOXX", "XLB"):
        res = await search_hk_us(kw, include_stocks=False, enrich=False, market="US")
        hit = [r for r in res if r["symbol"] == kw]
        assert hit, f"ETF tab 搜 {kw} 应命中"
        assert hit[0]["type"] == "etf", f"{kw} 应为 type=etf，实得 {hit[0]}"
        assert hit[0]["market"] == "US"
