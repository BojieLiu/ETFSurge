# -*- coding: utf-8 -*-
"""L2 P0: valuation_fetcher 取数契约（TDD 先红，mock akshare，无网络）.

D1 实测列名（2026-09-17 探针，R75 哨兵：mock 对齐真实响应）：
- ak.stock_zh_index_value_csindex: 日期/指数代码/指数中文全称/指数中文简称/
  指数英文全称/指数英文简称/市盈率1/市盈率2/股息率1/股息率2（近 20 日，无 PB）
- ak.stock_industry_pe_ratio_cninfo: 变动日期/行业分类/行业层级/行业编码/
  行业名称/公司数量/纳入计算公司数量/总市值-静态/净利润-静态/
  静态市盈率-加权平均/静态市盈率-中位数/静态市盈率-算术平均（无 PB/ROE）
"""
from unittest.mock import patch

import pandas as pd

from app.fetchers import valuation_fetcher as vf


def _df(columns, rows):
    return pd.DataFrame(rows, columns=columns)


_INDEX_COLS = ["日期", "指数代码", "指数中文全称", "指数中文简称",
               "指数英文全称", "指数英文简称",
               "市盈率1", "市盈率2", "股息率1", "股息率2"]

_SECTOR_COLS = ["变动日期", "行业分类", "行业层级", "行业编码", "行业名称",
                "公司数量", "纳入计算公司数量", "总市值-静态", "净利润-静态",
                "静态市盈率-加权平均", "静态市盈率-中位数", "静态市盈率-算术平均"]


def test_index_history_normalized():
    """指数历史归一化：市盈率1/2+股息率1/2 原样透传（1/2 口径未定，不猜）。"""
    vf.sync_memory_cache.clear()
    fake = _df(_INDEX_COLS, [
        ["2026-09-16", 300, "沪深300指数", "沪深300",
         "CSI 300 Index", "CSI 300", 14.6, 16.82, 2.63, 2.34],
        ["2026-09-15", 300, "沪深300指数", "沪深300",
         "CSI 300 Index", "CSI 300", 14.5, 16.70, 2.61, 2.32],
    ])
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_index_value_csindex", return_value=fake):
        rows = vf.fetch_index_valuation_history("000300")
    assert len(rows) == 2
    assert rows[0] == {"date": "2026-09-16", "pe_1": 14.6, "pe_2": 16.82,
                       "div_1": 2.63, "div_2": 2.34}
    vf.sync_memory_cache.clear()


def test_index_empty_df_returns_empty():
    vf.sync_memory_cache.clear()
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_index_value_csindex",
               return_value=_df(_INDEX_COLS, [])):
        assert vf.fetch_index_valuation_history("000300") == []
    vf.sync_memory_cache.clear()


def test_index_failure_cached():
    """源异常 → [] + 失败缓存（二次调用不再触源，R4-26 模式）。"""
    vf.sync_memory_cache.clear()
    calls = {"n": 0}

    def _boom(**kw):
        calls["n"] += 1
        raise Exception("cninfo down")

    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_zh_index_value_csindex", side_effect=_boom):
        assert vf.fetch_index_valuation_history("000300") == []
        assert vf.fetch_index_valuation_history("000300") == []
    assert calls["n"] == 1, f"失败缓存应阻止重复触源，实际 {calls['n']} 次"
    vf.sync_memory_cache.clear()


def test_sector_snapshot_normalized():
    """板块快照归一化：静态 PE 三口径透传，无 PB/ROE 不编。"""
    vf.sync_memory_cache.clear()
    fake = _df(_SECTOR_COLS, [
        ["2026-09-16", "证监会行业", "大类", "C39",
         "计算机、通信和其他电子设备制造业", 100, 98,
         1e12, 5e10, 20.5, 35.2, 40.1],
    ])
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_industry_pe_ratio_cninfo", return_value=fake):
        rows = vf.fetch_sector_pe_snapshot(date="20260916")
    assert len(rows) == 1
    assert rows[0] == {"ind_code": "C39",
                       "ind_name": "计算机、通信和其他电子设备制造业",
                       "pe_wavg": 20.5, "pe_median": 35.2, "pe_avg": 40.1,
                       "as_of": "2026-09-16"}
    vf.sync_memory_cache.clear()


def test_sector_failure_returns_empty():
    vf.sync_memory_cache.clear()
    with patch.object(vf, "run_in_thread", lambda fn, timeout=8, executor="long": fn()), \
         patch("akshare.stock_industry_pe_ratio_cninfo",
               side_effect=Exception("cninfo down")):
        assert vf.fetch_sector_pe_snapshot(date="20260916") == []
    vf.sync_memory_cache.clear()
