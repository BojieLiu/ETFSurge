"""F16 (round6 §16.4): 港股热点 push2delay——market 参数 + 港股行业聚合。

规格（用户已决策：港股先做，美股降级提示）：
1. 三端点（hot-plates/sectors/heat/stock-hot-rank）加 market 参数（A/HK/US）；
2. 港股热点走 push2delay（fs=m:128 全量港股 + f100 中文行业字段）——
   按 f100 聚合涨跌幅/成交额 → 港股行业热点板块；按 f6（成交额）排序取前 N
   → 港股热门个股；
3. 美股按决策降级提示「该市场暂不支持热点排行」（不得返回 A 股数据）；
4. TDD：?market=HK 返回港股域板块/个股（f100 聚合结果非空，mock push2delay
   响应）或「暂不支持」结构化标记；?market=US 返回暂不支持提示。

mock 策略：纯函数级——新增 fetcher 模块 app/fetchers/hk_hot_fetcher.py，
暴露 parse 纯函数（不触网）+ 路由函数（依赖注入 response）。
"""
import pytest

from app.fetchers import hk_hot_fetcher as hk

# 东财 push2delay clist 港股行（m:128）响应样例（f100=中文行业）
_HK_ROWS = [
    {"f12": "09988", "f14": "阿里巴巴-W", "f2": 82.3, "f3": 1.2, "f6": 5.2e9, "f100": "专业服务"},
    {"f12": "00700", "f14": "腾讯控股", "f2": 380.0, "f3": -0.5, "f6": 4.1e9, "f100": "专业服务"},
    {"f12": "00941", "f14": "中国移动", "f2": 68.0, "f3": 0.3, "f6": 1.2e9, "f100": "电信服务"},
    {"f12": "01299", "f14": "友邦保险", "f2": 55.0, "f3": 0.8, "f6": 9.0e8, "f100": "保险"},
    {"f12": "00005", "f14": "汇丰控股", "f2": 65.0, "f3": 0.5, "f6": 8.0e8, "f100": "银行"},
]


class TestHkHotFetcher:
    def test_parse_hk_plates_aggregates_by_industry(self):
        """F16: 港股行业热点——按 f100 聚合涨跌幅/成交额。"""
        plates = hk.parse_hk_plates(_HK_ROWS)
        names = [p["name"] for p in plates]
        assert "专业服务" in names, f"应聚合出专业服务板块, got {names}"
        # 专业服务板块（阿里+腾讯）成交额 = 5.2e9 + 4.1e9
        pro = next(p for p in plates if p["name"] == "专业服务")
        assert pro["amount"] > 9e9, f"板块成交额应聚合: {pro['amount']}"
        assert pro["stock_count"] == 2
        # 排序：按成交额降序，专业服务第一
        assert plates[0]["name"] == "专业服务"

    def test_parse_hk_hot_stocks_sorted_by_amount(self):
        """F16: 港股热门个股——按 f6（成交额）降序取前 N。"""
        stocks = hk.parse_hk_hot_stocks(_HK_ROWS, top_n=3)
        assert len(stocks) == 3
        assert stocks[0]["symbol"] == "09988"
        assert stocks[1]["symbol"] == "00700"
        assert stocks[2]["symbol"] == "00941"

    def test_url_has_fltt2(self):
        """round9 §7: 东财 clist 不带 fltt=2 时 f2/f3 返回 ×100 整数（盈富基金
        f2=26160/f3=62 实为 26.16 港元/+0.62%）→ 港股涨跌幅曾全量 ×100。
        _URL 必须带 fltt=2&invt=2，防回归。"""
        assert "fltt=2" in hk._URL and "invt=2" in hk._URL

    def test_route_hk_returns_plates(self, monkeypatch):
        """F16: 路由 HK → 港股行业热点（mock 网络响应注入）。"""
        def _fake_fetch_rows():
            return _HK_ROWS
        monkeypatch.setattr(hk, "_fetch_hk_rows", _fake_fetch_rows)
        out = hk.get_hk_hot_plates(limit=5)
        assert out, "HK 热点板块非空"
        assert all("HK" in p.get("market", "") or p.get("market") == "HK" for p in out)

    def test_route_us_returns_unsupported(self):
        """F16: 美股 → 结构化「暂不支持」标记（不得返回 A 股数据）。"""
        out = hk.get_us_unsupported()
        assert out == {"support": False, "message": "该市场暂不支持热点排行"}


# ── F16 路由级契约（market 透传 + US 暂不支持）──────────────────────────
def test_route_hot_plates_market_hk(monkeypatch):
    """?market=HK → hub.get_hot_plates 收到 market=HK（mock 港股数据）。"""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import market_data_hub as hub_mod

    got = {}
    def _fake(limit=None, market="A"):
        got["market"] = market
        return [{"name": "专业服务", "change_pct": 0.3, "amount": 9.3e9,
                 "stock_count": 2, "market": "HK"}]
    monkeypatch.setattr(hub_mod.market_data_hub, "get_hot_plates", _fake)
    client = TestClient(app)
    resp = client.get("/api/v1/market/hot-plates?limit=5&market=HK")
    assert resp.status_code == 200
    assert got.get("market") == "HK"
    items = resp.json()
    assert items and items[0]["name"] == "专业服务"


def test_route_hot_plates_market_us_unsupported(monkeypatch):
    """?market=US → 返回空列表（暂不支持，不得返回 A 股数据）。"""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import market_data_hub as hub_mod

    def _fake(limit=None, market="A"):
        return []  # US 分支返回空
    monkeypatch.setattr(hub_mod.market_data_hub, "get_hot_plates", _fake)
    client = TestClient(app)
    resp = client.get("/api/v1/market/hot-plates?limit=5&market=US")
    assert resp.status_code == 200
    assert resp.json() == []
