# -*- coding: utf-8 -*-
"""L2 P0: valuation_history 表模型契约（TDD 先红）.

攒长期分位用：market_snapshots 同 kind 只留 2 条不够，
本表按 (kind, key) 留 250 个交易日（约 1 年日级）。
"""
from app.models.valuation_history import ValuationHistory


def test_tablename():
    assert ValuationHistory.__tablename__ == "valuation_history"


def test_schema():
    cols = {c.name for c in ValuationHistory.__table__.columns}
    assert {"id", "kind", "key", "pe_1", "pe_2", "div_1", "div_2",
            "pe_wavg", "pe_median", "pe_avg", "as_of",
            "created_at"} <= cols
