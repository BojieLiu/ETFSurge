"""round27 R46: 板块动量数据源修正（反假完成负向测试）。

根因（doc §15.1 R46 / Round 9 更正）：`_compute_industry_momentum` / `_compute_concept_momentum`
旧实现用 akshare `stock_board_industry_name_em`（硬编码 push2.eastmoney.com，被 EM 域名级
风控 ProxyError 阻断）→ live 源失败 → 首启无快照可写（R40 首启空窗）。

修复：改调项目自有 `fetch_em_industry_sectors` / `fetch_em_concept_sectors`
（EM_PUSH_HOST=push2delay，实测 496 行可用）。akshare 仅作防御性兜底（push2delay 也空时）。

验收（负向）：
① mock akshare 阻断（ProxyError）+ 注入 push2delay 496 行 → `compute_sector_momentum`
   非 []（禁再「akshare 阻断即返空」）；
② 证明主源是项目自有 push2delay fetcher（akshare 未被主路径调用）；
③ push2delay 也失败时回退 akshare，akshare 再失败 → 诚实返回 []（不崩溃、不伪造）。
"""
import asyncio
from unittest.mock import patch, MagicMock

import pytest

from app.services import market_trends
from app.services.market_trends import (
    compute_sector_momentum,
    _compute_industry_momentum,
    _compute_concept_momentum,
)


def _em_rows(n: int, prefix: str) -> list[dict]:
    """模拟 push2delay fetcher 返回的行（字段与 sector_fetcher.fetch_em_* 兼容）。"""
    rows = []
    for i in range(n):
        pct = 3.0 - 0.01 * i  # 递减涨跌幅，便于排序
        rows.append({
            "sector_code": f"BK{prefix}{i:04d}",
            "sector_name": f"{prefix}板块{i}",
            "change_pct": pct,
            "main_inflow": 1000.0 - i * 10,
            "up_count": 10,
            "down_count": 5,
            "total_market": 1e9,
            "lead_stock_name": "", "lead_stock_code": "", "lead_stock_chg": None,
        })
    return rows


def test_akshare_blocked_but_push2delay_works():
    """R46 负向①+②：akshare 阻断 + push2delay 返 496 行 → 动量非 []，且不依赖 akshare。"""
    proxy_err = ConnectionError("ProxyError: push2 blocked")

    em_ind = _em_rows(496, "IND")
    em_con = _em_rows(200, "CON")

    # akshare 一旦被调用就抛 ProxyError —— 若主路径仍走 akshare，会走兜底且失败
    with patch(
        "app.fetchers.sector_fetcher.fetch_em_industry_sectors",
        return_value=em_ind,
    ), patch(
        "app.fetchers.sector_fetcher.fetch_em_concept_sectors",
        return_value=em_con,
    ), patch("akshare.stock_board_industry_name_em", side_effect=proxy_err), patch(
        "akshare.stock_board_concept_name_em", side_effect=proxy_err,
    ):
        result = asyncio.run(compute_sector_momentum(10))

    assert isinstance(result, list) and len(result) > 0, (
        f"push2delay 有数据但 compute_sector_momentum 返空 → R46 回退 akshare 失败路径"
    )
    # 验证字段形状（as_of 诚实标注由上层处理；此处只验 live 源真的产出了数据）
    assert any(r.get("sector") and isinstance(r.get("change_pct"), float) for r in result), (
        "返回的板块行缺少 sector/change_pct 字段"
    )
    # 验证主源确为 push2delay（行业板块应有 push2delay 行名）
    names = {r["sector"] for r in result}
    assert "IND板块0" in names, "主源未使用 push2delay fetcher 数据"


def test_push2delay_fail_falls_back_to_akshare_then_graceful():
    """R46 ③：push2delay 失败（返回 None）→ 回退 akshare；akshare 也失败 → 诚实 []，不崩。"""
    proxy_err = ConnectionError("push2 & akshare both blocked")

    with patch(
        "app.fetchers.sector_fetcher.fetch_em_industry_sectors",
        return_value=None,
    ), patch(
        "app.fetchers.sector_fetcher.fetch_em_concept_sectors",
        return_value=None,
    ), patch("akshare.stock_board_industry_name_em", side_effect=proxy_err), patch(
        "akshare.stock_board_concept_name_em", side_effect=proxy_err,
    ):
        result = asyncio.run(compute_sector_momentum(10))

    # 双源全部失败 → 诚实返回空（不得抛异常、不得伪造假数据）
    assert result == [], f"双源失败应诚实返 []，实际 {result!r}"


def test_industry_momentum_uses_push2delay_primary():
    """R46 ②（单元级）：`_compute_industry_momentum` 主路径调用 push2delay fetcher。"""
    em_ind = _em_rows(15, "IND")
    with patch(
        "app.fetchers.sector_fetcher.fetch_em_industry_sectors",
        return_value=em_ind,
    ) as mocked, patch("akshare.stock_board_industry_name_em", side_effect=ConnectionError("blocked")):
        rows = asyncio.run(_compute_industry_momentum(15))

    mocked.assert_called_once()
    assert len(rows) == 15
    assert rows[0]["sector"] == "IND板块0"
    # 按 change_pct 降序排序
    assert all(
        rows[i]["change_pct"] >= rows[i + 1]["change_pct"] for i in range(len(rows) - 1)
    )
