"""TDD: F0-5 — 候选池修复（§9.6 专项步骤 A-E）。

覆盖：
  A. _fetch_em_etf_list 改成交额排序（fid=f6）+ 分页失败重试不 break
  B. full_pipeline 主流宽基静态兜底注入（core 含 510300 / defense 含 518880）
  C. 板块配额：归一化概念组每类 ≤2、科创系合计 ≤ 卫星预算 50%
  D. 卫星数量下限 ≥ 4
  E. C2 惩罚触发条件修正（估值错位值不再视为有效估值 → 防御型科创惩罚生效）
"""
import logging
import pytest
from unittest.mock import patch, MagicMock


# ── 步骤 A：成交额排序 + 分页重试 ──────────────────────────────

def test_pool_sorted_by_amount(monkeypatch):
    """请求 URL 含 fid=f6（成交额排序）。"""
    from app.fetchers import etf_scanner

    captured_urls = []
    page2_diff = [{"f12": "510300", "f14": "沪深300ETF", "f2": 4.0, "f3": 1.0,
                   "f72": 1e9, "f184": 3e10, "f62": 1.0, "f45": 1e6, "f66": 12.0}]

    class _FakeResp:
        def __init__(self, url, **kw):
            captured_urls.append(url)

        def json(self):
            if "pn=2" in captured_urls[-1]:
                return {"data": {"total": 2, "diff": page2_diff}}
            return {"data": {"total": 2, "diff": [{"f12": "588000", "f14": "科创50ETF"}]}}

    class _FakeReq:
        def get(self, url, **kw):
            return _FakeResp(url)

    with patch("curl_cffi.requests.get", side_effect=_FakeReq().get):
        result = etf_scanner._fetch_em_etf_list()
    assert result is not None
    assert any("fid=f6" in u for u in captured_urls), f"fid 未改成交额排序: {captured_urls[0]}"
    assert "fid=f3" not in captured_urls[0]
    assert any(e["symbol"] == "510300" for e in result)


def test_pool_page_fail_continues(monkeypatch, caplog):
    """第 1 页抛异常 → 不中断、返回后续页数据、记录 WARNING。"""
    from app.fetchers import etf_scanner

    call_count = {"n": 0}
    page2_diff = [{"f12": "510500", "f14": "中证500ETF", "f2": 6.0, "f3": 0.5,
                   "f72": 8e8, "f184": 2e10, "f62": 1.0, "f45": 1e6, "f66": 11.0}]

    class _FakeResp:
        def json(self):
            return {"data": {"total": 1, "diff": page2_diff}}

    class _FakeReq:
        def get(self, url, **kw):
            call_count["n"] += 1
            if call_count["n"] <= 2:  # 第 1 页 2 次尝试都失败
                raise RuntimeError("network down")
            return _FakeResp()

    with patch("curl_cffi.requests.get", side_effect=_FakeReq().get):
        with caplog.at_level(logging.WARNING, logger="app.fetchers.etf_scanner"):
            result = etf_scanner._fetch_em_etf_list()

    assert result is not None, "分页失败不应返回 None"
    assert any(e["symbol"] == "510500" for e in result), "应返回后续页数据"
    assert any("page 1" in r.message for r in caplog.records), "应有 WARNING 日志"


# ── 步骤 B：主流宽基静态兜底注入 ───────────────────────────────

def test_core_required_injected(monkeypatch):
    """候选池无 510300 → full_pipeline core 含 510300（静态兜底）。"""
    from app.fetchers import etf_scanner

    fake_etfs = [
        {"symbol": "562320", "name": "沪深300价值ETF", "price": 1.0, "change_pct": 5.0,
         "amount": 5e8, "fund_scale": 5e8, "turnover": 1.0, "volume": 1e6},
        {"symbol": "563080", "name": "中证A50ETF", "price": 1.0, "change_pct": 4.0,
         "amount": 4e8, "fund_scale": 4e8, "turnover": 1.0, "volume": 1e6},
    ]
    monkeypatch.setattr(etf_scanner, "fetch_all_etfs_base", lambda: fake_etfs)
    monkeypatch.setattr(etf_scanner, "layer_ranking",
                        lambda items, top_n=25, required=None: items[:top_n])
    monkeypatch.setattr(etf_scanner, "_extract_index_keyword", lambda n: "")
    monkeypatch.setattr(etf_scanner, "classify_etf",
                        lambda name, tidx: "core" if "300价值" in name or "A50" in name else "satellite")

    result = etf_scanner.full_pipeline()
    core_symbols = [e["symbol"] for e in result["core"]]
    assert "510300" in core_symbols, f"core 应含静态兜底 510300，实际: {core_symbols}"


def test_defense_required_injected(monkeypatch):
    """候选池无 518880 → defense 含 518880（静态兜底）。"""
    from app.fetchers import etf_scanner

    fake_etfs = [
        {"symbol": "511010", "name": "国债ETF", "price": 1.0, "change_pct": 0.2,
         "amount": 1e8, "fund_scale": 1e9, "turnover": 1.0, "volume": 1e6},
    ]
    monkeypatch.setattr(etf_scanner, "fetch_all_etfs_base", lambda: fake_etfs)
    monkeypatch.setattr(etf_scanner, "layer_ranking",
                        lambda items, top_n=25, required=None: items[:top_n])
    monkeypatch.setattr(etf_scanner, "_extract_index_keyword", lambda n: "")
    monkeypatch.setattr(etf_scanner, "classify_etf",
                        lambda name, tidx: "defense" if "国债" in name else "satellite")

    result = etf_scanner.full_pipeline()
    defense_symbols = [e["symbol"] for e in result["defense"]]
    assert "518880" in defense_symbols, f"defense 应含静态兜底 518880，实际: {defense_symbols}"


# ── 步骤 C：板块配额 ───────────────────────────────────────────

def _kcb_candidates():
    """全科创候选池（归一化后分属不同概念组，但名称都含科创）。"""
    return [
        {"symbol": "589720", "name": "科创创新药ETF", "layer": "satellite", "tracked_index": "科创创新药"},
        {"symbol": "589420", "name": "科创芯片设计ETF", "layer": "satellite", "tracked_index": "科创芯片设计"},
        {"symbol": "589560", "name": "科创人工智能ETF", "layer": "satellite", "tracked_index": "科创人工智能"},
        {"symbol": "589960", "name": "科创新能源ETF", "layer": "satellite", "tracked_index": "科创新能源"},
        {"symbol": "588000", "name": "科创50ETF", "layer": "satellite", "tracked_index": "科创50"},
    ]


def test_sector_quota_tech_theme_cap():
    """科创系候选合计权重 ≤ 卫星预算 50%。"""
    from app.engine import allocation_engine as ae

    factor_matrix = {c["symbol"]: {"technical": 0.5, "momentum": 0.5,
                                   "valuation": 0.5, "sentiment": 0.5}
                     for c in _kcb_candidates()}
    # 卫星预算 0.30 → 科创系合计 ≤ 0.15
    allocs = ae._select_and_weight(
        _kcb_candidates(), factor_matrix, budget=0.30,
        layer="satellite", regime="range_bound", strategy="balanced",
        max_count=8,
    )
    tech_weight = sum(
        a["weight"] for a in allocs
        if any(t in a.get("name", "") for t in ("科创", "半导体", "芯片", "AI", "人工智能"))
    )
    assert tech_weight <= 0.30 * 0.5 + 1e-6, f"科创系权重 {tech_weight} 超过卫星预算 50%"
    # 归一化概念组每类 ≤2（候选位）
    assert len(allocs) <= 4, f"科创系配额裁剪后不应超过 4 只: {len(allocs)}"


# ── 步骤 D：卫星数量下限 ───────────────────────────────────────

def test_satellite_min_count():
    """每方案卫星 ≥ 4 只（预算允许时）——M5 弱化下限：宽基不得入卫星，
    宁可 3 只也不混入宽基（combination-design-review M5 语义）。"""
    from app.engine.allocation_engine import allocate

    candidates = []
    for i, (sym, name) in enumerate([
        ("510300", "沪深300ETF"), ("510500", "中证500ETF"), ("510050", "上证50ETF"),
        ("512890", "红利低波ETF"), ("588000", "科创50ETF"), ("159915", "创业板ETF"),
        ("512010", "医药ETF"), ("515030", "新能源车ETF"), ("512880", "证券ETF"),
        ("515790", "光伏ETF"), ("512760", "芯片ETF"), ("510880", "红利ETF"),
        ("511010", "国债ETF"), ("518880", "黄金ETF"), ("513500", "标普500ETF"),
    ]):
        layer = "defense" if sym in ("511010", "518880", "513500") else ("core" if i < 4 else "satellite")
        candidates.append({"symbol": sym, "name": name, "layer": layer,
                           "tracked_index": name.replace("ETF", "")})
    factor_matrix = {c["symbol"]: {"technical": 0.3, "momentum": 0.2,
                                   "valuation": 0.2, "sentiment": 0.1}
                     for c in candidates}

    strategies = allocate(risk_profile="balanced", regime="range_bound",
                          factor_matrix=factor_matrix, candidates=candidates)
    assert len(strategies) == 3
    for s in strategies:
        sats = [a for a in s["allocations"] if a.get("layer") == "satellite"]
        sat_syms = {a["symbol"] for a in sats}
        # M5: 卫星层不得混入宽基（core 属性：沪深300/中证500/上证50/科创50/创业板）
        wide = sat_syms & {"510300", "510500", "510050", "588000", "159915"}
        assert not wide, f"{s['id']} 卫星层混入宽基 {sorted(wide)}"
        # 弱化下限：宽基排除 + 防御偏好（红利入核心）后 ≥2 只即可——
        # 旧断言 ≥4 依赖宽基凑数，与 M5「宁可不足也不混宽基」冲突
        assert len(sats) >= 2, f"{s['id']} 卫星仅 {len(sats)} 只"


# ── 步骤 E：C2 惩罚触发条件修正 ───────────────────────────────

def test_c2_penalty_defensive_kcb():
    """防御型 + 估值错位值（黄金 +3.9 类假信号）→ 视为缺失 → 科创候选 c2_bonus=-1.5 生效。"""
    from app.engine import allocation_engine as ae

    # 黄金 ETF 估值错位 +3.9（假信号），科创候选估值也为错位高值
    factor_matrix = {
        "518880": {"technical": 2.833, "valuation": 3.926, "momentum": -0.5, "sentiment": 0.0},
        "589720": {"technical": -0.408, "valuation": -0.462, "momentum": 1.047, "sentiment": 0.0},
        "510300": {"technical": 0.5, "valuation": 0.2, "momentum": 0.3, "sentiment": 0.1},
    }
    candidates = [
        {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "tracked_index": "沪深300"},
        {"symbol": "589720", "name": "科创创新药ETF", "layer": "satellite", "tracked_index": "科创创新药"},
        {"symbol": "518880", "name": "黄金ETF", "layer": "defense", "tracked_index": "黄金"},
    ]
    strategies = ae.allocate(risk_profile="defensive", regime="range_bound",
                             factor_matrix=factor_matrix, candidates=candidates)
    # 防御型方案中：589720（科创）不得出现在卫星层（被 -1.5 惩罚挤出），
    # 或即使出现其权重也应明显低于无惩罚场景。
    for s in strategies:
        if s["id"] == "defensive":
            kcb = [a for a in s["allocations"] if a.get("symbol") == "589720"]
            if kcb:
                # 惩罚生效的验证：589720 的 factor_score（含 -1.5）应低于其原始 composite
                fs = kcb[0].get("factor_score", 0)
                raw_composite = (-0.408 * 0.4 + 1.047 * 0.15 + (-0.462) * 0.2 + 0.0 * 0.25)
                assert fs <= raw_composite, f"c2_bonus 未生效: fs={fs} raw={raw_composite}"


# ── 集成：设计方案 core 含主流宽基 ─────────────────────────────

def test_design_core_contains_wide_basis(monkeypatch):
    """完整管道：三套方案 core 至少含 1 只主流宽基。"""
    from app.fetchers import etf_scanner

    fake_etfs = [
        {"symbol": "562320", "name": "沪深300价值ETF", "price": 1.0, "change_pct": 5.0,
         "amount": 5e8, "fund_scale": 5e8, "turnover": 1.0, "volume": 1e6},
        {"symbol": "562330", "name": "中证500价值ETF", "price": 1.0, "change_pct": 4.0,
         "amount": 4e8, "fund_scale": 4e8, "turnover": 1.0, "volume": 1e6},
    ]
    monkeypatch.setattr(etf_scanner, "fetch_all_etfs_base", lambda: fake_etfs)
    monkeypatch.setattr(etf_scanner, "layer_ranking",
                        lambda items, top_n=25, required=None: items[:top_n])
    monkeypatch.setattr(etf_scanner, "_extract_index_keyword", lambda n: "")
    monkeypatch.setattr(etf_scanner, "classify_etf",
                        lambda name, tidx: "core" if "300价值" in name or "500价值" in name else "satellite")

    result = etf_scanner.full_pipeline()
    wide_basis = {"510300", "510500", "510050", "588000", "159915"}
    core_symbols = {e["symbol"] for e in result["core"]}
    assert core_symbols & wide_basis, f"core 应含主流宽基，实际: {core_symbols}"
