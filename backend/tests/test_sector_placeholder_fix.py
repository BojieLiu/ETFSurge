"""F19 (round6 §16.7): placeholder 行不参与板块匹配 + 失败文案区分。

背景：概念表对缺失热门概念追加 sector_code="" 的 placeholder 行（有名无码）→
_normalize_sector_code 按名称命中 placeholder → 返回空代码 → 404「板块映射失败」。
修复：combined 匹配前过滤 placeholder；失败文案改「数据源暂无数据」。
"""
import pytest

from app.routers.analysis import _normalize_sector_code


def _row(code, name):
    return {"sector_code": code, "sector_name": name, "price": 1.0,
            "change_pct": 0.0, "amount": 1e8}


def test_normalize_skips_placeholder_rows():
    """placeholder 行（sector_code=''）被过滤后，名称匹配只命中真实行。"""
    tables = [
        _row("", "创新药"),  # placeholder（有名无码）
        _row("BK1141", "创新药板块"),
    ]
    # 过滤 placeholder 后名称精确匹配 → 真实代码
    filtered = [s for s in tables if s.get("sector_code")]
    normalized = _normalize_sector_code("创新药", filtered, [], name="创新药")
    assert normalized == "BK1141"


def test_normalize_placeholder_only_returns_code():
    """仅 placeholder 命中（过滤后无真实行）→ 返回原 code（调用方走数据源缺失提示）。"""
    tables = [_row("", "创新药")]
    filtered = [s for s in tables if s.get("sector_code")]
    # 过滤后无行 → 归一化无命中 → 返回原值
    normalized = _normalize_sector_code("创新药", filtered, [], name="创新药")
    assert normalized == "创新药"


@pytest.mark.asyncio
async def test_sector_analysis_missing_concept_reports_data_source(monkeypatch):
    """缺失概念（placeholder 仅）→ 404 文案为「数据源暂无数据」而非「板块映射失败」。"""
    from app.routers import analysis as an
    from app.services import market_data_hub as mdh
    from fastapi import HTTPException

    # 行业表只有 placeholder 行
    placeholder = [{"sector_code": "", "sector_name": "创新药", "price": 0.0,
                    "change_pct": 0.0, "amount": 0.0}]
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_industry", lambda limit: placeholder)
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_concept", lambda limit: [])
    monkeypatch.setattr(mdh.market_data_hub, "get_sector_stocks", lambda code: [])
    monkeypatch.setattr(mdh.market_data_hub, "get_news_headlines", lambda: [])
    monkeypatch.setattr(mdh.market_data_hub, "get_news_macro", lambda: [])

    req = an.SectorAnalysisRequest(
        sector_code="创新药", sector_type="industry", sector_name="创新药", market="A",
    )
    with pytest.raises(HTTPException) as exc_info:
        await an.sector_analysis_stream(req)
    assert exc_info.value.status_code == 404
    assert "数据源暂无数据" in str(exc_info.value.detail), exc_info.value.detail
    assert "板块映射失败" not in str(exc_info.value.detail)
