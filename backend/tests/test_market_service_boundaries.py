# -*- coding: utf-8 -*-
"""P2-3 后半（docs/redundant-review.md §3 D7）: market_service 函数级归属审计。

冗余评审判定 D7: market_service.py 2096 行「嫌疑，未定级」——本次审计做函数级
归属核对，判定「编排层职责合理、无错误归属需搬移」，结论固化为测试防回归。

审计方法（rg 全库调用方核对，2026-09 实施批实测）:
- 消费方: hub/_realtime.py（12 个委托方法）、routers/market.py、
  market_data_hub.py、routers/analysis.py、fetchers/sync_indices.py、main.py——
  「行情编排」单一职责成立；
- 边界核对: hub/_realtime 全部为薄委托（无业务逻辑重复）；market_data_hub 只引
  get_global_indices（指数缓存域）；与 hub 的「数据管道」边界清晰
  （market_service=多源编排/降级链，hub=池/因子/K 线管道）；
- 唯一跨层引用: fetchers/sync_indices 引 _GLOBAL_INDEX_DEFS（常量，可接受）。

本测试锁定 4 条结构断言（防未来无序膨胀回退）。
"""
from __future__ import annotations

import inspect

import app.services.market_service as ms


class TestMarketServiceBoundaries:
    def test_module_size_bounded(self):
        """行数上界: market_service ≤2200 行（现 2096）——防止继续膨胀为上帝模块。"""
        import io
        n = len(io.open(inspect.getfile(ms), encoding="utf-8").read().splitlines())
        assert n <= 2200, f"market_service.py {n} 行超上界 2200（D7 防回退），需先拆分再增函数"

    def test_no_hub_business_logic_leak(self):
        """边界: market_service 不得引入 hub 管道域内部符号（get_pool/_kline_cache/
        refresh_kline 等）——编排层消费 hub 的公开方法，不摸内部状态。"""
        src = inspect.getsource(ms)
        for forbidden in ("get_pool()", "_kline_cache", "refresh_kline(",
                          "get_factor_matrix("):
            assert forbidden not in src, (
                f"market_service 不应引用 hub 管道域内部符号 {forbidden}（D7 边界）"
            )

    def test_public_api_is_orchestration_surface(self):
        """公开 API 均为编排/降级语义（行情/搜索/历史/基本面），无私有管道泄漏。"""
        public = [n for n, v in vars(ms).items()
                  if not n.startswith("_") and inspect.iscoroutinefunction(v)]
        expected_core = {"get_all_realtime", "get_history", "search_etf",
                         "get_asset_realtime", "get_portfolio_realtime"}
        assert expected_core <= set(public), f"核心编排 API 缺失: {expected_core - set(public)}"

    def test_hub_realtime_delegation_is_thin(self):
        """hub/_realtime 委托层保持薄（每个方法 ≤6 行）——反向防止业务逻辑搬进委托层。"""
        import io
        from app.services import hub as hub_pkg
        path = hub_pkg.__path__[0] + "/_realtime.py"
        src = io.open(path, encoding="utf-8").read().splitlines()
        bad = []
        i = 0
        while i < len(src):
            line = src[i]
            if line.strip().startswith("async def ") and i + 1 < len(src):
                # 找到下一个同级/更小缩进 def 或结尾
                j = i + 1
                body_len = 0
                base_indent = len(line) - len(line.lstrip())
                while j < len(src):
                    l2 = src[j]
                    if l2.strip() and (len(l2) - len(l2.lstrip())) <= base_indent and not l2.strip().startswith(("'", '"', "#", ")", "}")):
                        break
                    body_len += 1
                    j += 1
                name = line.strip().split("(")[0].replace("async def ", "")
                if body_len > 8 and "委托" not in "\n".join(src[i:i + 4]):
                    bad.append((name, body_len))
                i = j
            else:
                i += 1
        assert not bad, f"委托层出现非薄方法: {bad}（D7 边界守卫）"
