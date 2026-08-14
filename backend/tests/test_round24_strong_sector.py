"""round24 R1: 强板块动量注入候选池（SECTOR_ETF_MAP + _strong_sector_etfs）。

R1 缺口：design 570 实证 strong_sector_pool_coverage=[]、候选池=0，强板块未进候选池，
方案与市场热点脱节。修复：板块动量 TopN 经 SECTOR_ETF_MAP 映射代表 ETF 注入 flat。

本测试固化纯函数 _strong_sector_etfs 的映射/去重/排序/降级行为（无 I/O）。
"""

from app.services.market_data_hub import _strong_sector_etfs, SECTOR_ETF_MAP


def _sector(name, change_pct, type_="industry"):
    return {"sector": name, "sector_code": f"BK_{name}", "type": type_,
            "change_pct": change_pct, "rank_current": 1}


def test_top_sector_maps_to_etf():
    """涨幅最高的「半导体」→ 512480，且带 hot_sector 标记与保底 composite_score。"""
    momentum = [_sector("银行", 1.0), _sector("半导体", 3.5), _sector("煤炭", 0.5)]
    out = _strong_sector_etfs(momentum, top_n=8)
    syms = {e["symbol"] for e in out}
    assert "512480" in syms
    item = next(e for e in out if e["symbol"] == "512480")
    assert item["hot_sector"] is True
    assert item["composite_score"] == 0.6
    assert item["layer"] == "satellite"


def test_unmapped_sector_skipped():
    """未建映射的板块（如「XX概念」）被跳过，不报错。"""
    momentum = [_sector("未知板块XYZ", 5.0)]
    out = _strong_sector_etfs(momentum, top_n=8)
    assert out == []


def test_existing_symbol_skipped():
    """已存在于候选池的强板块 ETF 不重复注入。"""
    momentum = [_sector("半导体", 3.5)]
    out = _strong_sector_etfs(momentum, existing_symbols={"512480"}, top_n=8)
    assert out == []


def test_empty_momentum_returns_empty():
    """熔断/无板块动量（[]）→ 返回 []，不注入。"""
    assert _strong_sector_etfs([], top_n=8) == []
    assert _strong_sector_etfs(None, top_n=8) == []


def test_sorted_by_change_pct_desc():
    """注入顺序按 change_pct 降序（最强板块优先）。"""
    momentum = [_sector("煤炭", 0.5), _sector("半导体", 3.5), _sector("证券", 2.0)]
    out = _strong_sector_etfs(momentum, top_n=8)
    syms = [e["symbol"] for e in out]
    assert syms[0] == "512480"   # 半导体 3.5 最高
    assert "512880" in syms      # 证券 2.0


def test_top_n_limit():
    """top_n 限制注入数量（去重后）。"""
    momentum = [_sector(n, 1.0 + i) for i, n in enumerate(
        ["半导体", "证券", "军工", "煤炭", "医药", "光伏", "银行", "通信", "游戏", "白酒"])]
    out = _strong_sector_etfs(momentum, top_n=3)
    assert len(out) == 3


def test_map_covers_core_indices():
    """宽基（沪深300/中证500/创业板/科创50/恒生）映射为 core 层。"""
    for name, layer in [("沪深300", "core"), ("中证500", "core"),
                        ("创业板", "core"), ("科创50", "core"), ("恒生科技", "satellite")]:
        assert name in SECTOR_ETF_MAP, f"{name} 缺映射"
        assert SECTOR_ETF_MAP[name]["layer"] == layer
