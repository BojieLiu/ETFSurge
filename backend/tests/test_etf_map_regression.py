# -*- coding: utf-8 -*-
"""ETF 映射回归:sess-1ef0 实证幻觉锁定.

- 银行→512800(华宝),515220 是煤炭(国泰),不许当银行;
- 煤炭→515220,159766 是旅游ETF富国,不许当煤炭.
真相源: app.services.hub._common.SECTOR_ETF_MAP (+instruments 表复核).
"""
from app.services.hub._common import SECTOR_ETF_MAP


def test_bank_maps_to_512800_not_coal_code():
    assert SECTOR_ETF_MAP["银行"]["symbol"] == "512800"
    assert SECTOR_ETF_MAP["煤炭"]["symbol"] == "515220"
    assert SECTOR_ETF_MAP["银行"]["symbol"] != SECTOR_ETF_MAP["煤炭"]["symbol"]


def test_159766_is_not_coal():
    symbols = {v["symbol"] for v in SECTOR_ETF_MAP.values()}
    assert "159766" not in symbols  # 旅游ETF,不在板块映射表内


def test_coal_and_bank_names():
    assert "银行" in SECTOR_ETF_MAP["银行"]["name"]
    assert "煤炭" in SECTOR_ETF_MAP["煤炭"]["name"]
