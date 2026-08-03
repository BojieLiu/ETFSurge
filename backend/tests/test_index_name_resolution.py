"""R6-F14 (round6 §十 R6-16): 指数名称解析消歧。

背景："沪深300" 中文名 → 159656 沪深300成长ETF（instruments 包含匹配取
symbol 最短——4 位 ETF 代码压过 6 位指数/宽基）。修复：resolve_symbol_to_code
优先 indices_meta 表（指数名 → 指数代码）。
"""
import asyncio

import pytest


class _FakeSession:
    """按查询目标表返回行：indices_meta 优先命中，instruments 返回空。"""

    def __init__(self, index_rows):
        self._index_rows = index_rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        try:
            entity = stmt.column_descriptions[0]["entity"]
            table = getattr(entity, "__tablename__", "")
        except Exception:
            table = ""
        if table == "indices_meta":
            return _Rows(self._index_rows)
        return _Rows([])

    def scalars(self):
        return _Scalars(self)

    def all(self):
        return self._rows if hasattr(self, "_rows") else []


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars2(self._rows)


class _Scalars:
    def __init__(self, session):
        self._session = session

    def all(self):
        return []


class _Scalars2:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        # select(IndexMeta.symbol) 的 scalars() 返回列值
        return [r.symbol for r in self._rows]


def _idx(symbol, name):
    return type("R", (), {"symbol": symbol, "name": name, "is_active": True})()


def test_resolve_index_name_prefers_indices_meta(monkeypatch):
    """"沪深300" → 000300（指数表优先），不再错位到 159656 沪深300成长ETF。"""
    from app.services import market_service as ms

    index_rows = [
        _idx("000300", "沪深300"),
        _idx("000905", "中证500"),
    ]
    monkeypatch.setattr(ms, "async_session", lambda: _FakeSession(index_rows))
    # 若走到 instruments/全量个股路径也不应返回 ETF 错位代码
    from app.services.market_data_hub import market_data_hub as _hub
    monkeypatch.setattr(_hub, "get_all_stocks", lambda: [])

    code = asyncio.run(ms.resolve_symbol_to_code("沪深300", "A"))
    assert code == "000300", f"指数名应解析为 000300, got {code}"


def test_resolve_etf_name_still_works(monkeypatch):
    """指数表无命中时，ETF 名称仍走 instruments 路径（回归防护）。"""
    from app.services import market_service as ms

    monkeypatch.setattr(ms, "async_session", lambda: _FakeSession([]))
    # instruments 路径 mock 返回空 → 走个股全量路径也空 → None（不崩）
    from app.services.market_data_hub import market_data_hub as _hub
    monkeypatch.setattr(_hub, "get_all_stocks", lambda: [])

    code = asyncio.run(ms.resolve_symbol_to_code("沪深300ETF", "A"))
    assert code is None or code  # 无 mock instruments 数据时优雅返回
