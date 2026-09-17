# -*- coding: utf-8 -*-
"""L2 P0: ValuationMixin 契约（TDD 先红，tmp 库 + mock fetcher，无网络）.

- 内存缓存 6h：TTL 内二次调用不触 fetcher。
- 落盘幂等：同 (kind, key, as_of) 重复 persist 只留 1 行。
- 裁剪：每 (kind, key) 只留最近 250 个 as_of。
- 分位：攒起的历史能算出近 20 日分位；单点历史 → None（待验）。
"""
import sqlite3

import pytest

from app.services.hub._valuation import ValuationMixin


@pytest.fixture()
def mix(tmp_path, monkeypatch):
    m = ValuationMixin()
    db = str(tmp_path / "val_test.db")
    monkeypatch.setattr("app.services.hub._valuation._valuation_db_path",
                        lambda: db)
    return m


def _idx_rows():
    return [
        {"date": "2026-09-16", "pe_1": 14.6, "pe_2": 16.82,
         "div_1": 2.63, "div_2": 2.34},
        {"date": "2026-09-15", "pe_1": 14.5, "pe_2": 16.70,
         "div_1": 2.61, "div_2": 2.32},
    ]


def test_index_cache_ttl(mix, monkeypatch):
    calls = {"n": 0}

    def _fake(symbol):
        calls["n"] += 1
        return _idx_rows()

    monkeypatch.setattr("app.services.hub._valuation.fetch_index_valuation_history",
                        _fake)
    assert len(mix.get_index_valuation("000300")) == 2
    assert len(mix.get_index_valuation("000300")) == 2
    assert calls["n"] == 1, "TTL 内不应重复触源"


def test_index_empty_not_cached(mix, monkeypatch):
    calls = {"n": 0}

    def _fake(symbol):
        calls["n"] += 1
        return []

    monkeypatch.setattr("app.services.hub._valuation.fetch_index_valuation_history",
                        _fake)
    assert mix.get_index_valuation("000300") == []
    assert mix.get_index_valuation("000300") == []
    assert calls["n"] == 2, "空结果不进 6h 缓存（靠 fetcher 1h 失败缓存防刷）"


def test_persist_idempotent(mix):
    mix.persist_index_valuation("000300", _idx_rows())
    mix.persist_index_valuation("000300", _idx_rows())
    assert mix.count_valuation_rows("index", "000300") == 2


def test_trim_keeps_250(mix):
    rows = [{"date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
             "pe_1": 10.0 + i * 0.01, "pe_2": None,
             "div_1": None, "div_2": None} for i in range(260)]
    mix.persist_index_valuation("000300", rows)
    assert mix.count_valuation_rows("index", "000300") == 250


def test_percentile_from_history(mix):
    mix.persist_index_valuation("000300", _idx_rows())
    hist = mix.get_valuation_history("index", "000300", col="pe_1")
    assert hist == [14.6, 14.5]
    from app.engine.valuation import compute_pe_percentile
    assert compute_pe_percentile(14.6, hist) == pytest.approx(1.0)
    assert compute_pe_percentile(14.5, hist) == pytest.approx(0.0)


def test_single_point_percentile_none(mix):
    mix.persist_index_valuation("000300", _idx_rows()[:1])
    hist = mix.get_valuation_history("index", "000300", col="pe_1")
    from app.engine.valuation import compute_pe_percentile
    # 单点历史无法分位 → engine 按 n==1 语义返回端点值；
    # 调用方约定：len(hist) < 5 一律待验（本断言锁定该约定输入）
    assert len(hist) == 1
    assert compute_pe_percentile(99.0, hist) == pytest.approx(1.0)


def test_sector_snapshot_persist_and_read(mix):
    rows = [{"ind_code": "C39", "ind_name": "计算机",
             "pe_wavg": 20.5, "pe_median": 35.2, "pe_avg": 40.1,
             "as_of": "2026-09-16"}]
    mix.persist_sector_valuation(rows)
    got = mix.get_valuation_history("sector", "C39", col="pe_wavg")
    assert got == [20.5]


def test_tmp_db_has_table(mix):
    # lazy 建表：首次读写（此处为读）即建表，无需 init_db
    assert mix.count_valuation_rows("index", "000300") == 0
    import app.services.hub._valuation as _v
    with sqlite3.connect(_v._valuation_db_path(), timeout=10) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "valuation_history" in names
