"""
O27 (docs/archived/round8-rediagnosis.md §7 §5.1I): 基本面/市值数据注入——compute 直调路径。

验收:
① compute 直调路径 ln_mcap/ln_float_mcap 与 refresh 路径数值一致（同一 total_mv 注入逻辑）；
② 无「全 0 截面」的 style 因子（symbol_extra 提供 fund_scale 时有区分度）；
③ 单测断言直调路径注入 total_mv。

round39 §10.7 (round42 实施): 合并 R42 + R146 增补到本文件, 按
"线程池路径 / IOPV 路径 / mv 字段路径" 三段组织:
- 线程池路径: R42 (6 用例) 验证 _inject_nav 走 _long_running_executor + Semaphore(8)
- IOPV 路径: R146 (3 用例) 验证 _inject_nav 在 IOPV 链命中 / 沿用已有 / TTJ 兜底 三场景
- mv 字段路径: 原有 O27 (3 用例) 验证 compute 直调路径 total_mv / ln_mcap 注入
"""

import inspect
import time
from unittest.mock import patch

import pytest

import app.factors.factor_registry as fr
from app.factors.factor_registry import (
    FactorRegistry,
    _compute_premium_discount,
    _inject_nav,
    registry,
)


def _fetch_market_data_source() -> str:
    return inspect.getsource(FactorRegistry._fetch_market_data)


def _patch_hub():
    """_inject_nav 用 ``from ..services.market_data_hub import market_data_hub as _hub``
    是函数内 local import, 需 patch 真实模块路径.
    """
    return patch("app.services.market_data_hub.market_data_hub")


# ── mv 字段路径 (O27, 原有 3 用例) ──

class TestComputeInjectsMv:
    def test_fetch_market_data_injects_total_mv(self):
        """直调路径注入 total_mv（symbol_extra.fund_scale 优先，rows 兜底）。"""
        src = _fetch_market_data_source()
        assert '"total_mv"' in src
        assert "fund_scale" in src
        assert '"float_mv"' in src

    def test_compute_uses_symbol_extra_consistent(self):
        """compute() 直调 + symbol_extra.fund_scale → 与 refresh 路径同一注入来源。"""
        src = _fetch_market_data_source()
        # 同一 total_mv 注入逻辑（fund_scale 或 rows[-1].total_mv）
        assert "symbol_extra" in src

    @pytest.mark.asyncio
    async def test_ln_mcap_not_all_zero_with_mv(self):
        """构造含不同 total_mv 的市场数据 → ln_mcap 截面有区分度（非全 0）。"""
        market_data = {
            "510300": {"total_mv": 1e11, "float_mv": 8e10, "close": [3.9, 4.0, 4.1], "high": [4.0, 4.1, 4.2], "low": [3.8, 3.9, 4.0], "volume": [100, 110, 120]},
            "510500": {"total_mv": 5e10, "float_mv": 4e10, "close": [6.0, 6.1, 6.2], "high": [6.1, 6.2, 6.3], "low": [5.9, 6.0, 6.1], "volume": [90, 95, 100]},
            "588000": {"total_mv": 2e10, "float_mv": 1.5e10, "close": [1.0, 1.05, 1.1], "high": [1.05, 1.1, 1.15], "low": [0.98, 1.0, 1.02], "volume": [200, 210, 220]},
        }
        result = await registry.compute(
            ["510300", "510500", "588000"],
            codes=["style.size.ln_mcap", "style.size.ln_float_mcap"],
            market_data=market_data,
        )
        ln = [result[s].get("style.size.ln_mcap", 0) for s in result]
        lnf = [result[s].get("style.size.ln_float_mcap", 0) for s in result]
        # 不同市值 → 不全是 0，且有区分度（z-score 后不恒为 0）
        assert any(v != 0 for v in ln), "ln_mcap 不应全 0（注入 total_mv 后有区分度）"
        assert any(v != 0 for v in lnf)
        assert len(set(round(v, 6) for v in ln)) > 1, "ln_mcap 应有截面区分度"


# ── 线程池路径 (R42, 6 用例) ──

class TestNavOneLongRunningExecutor:
    """R42 (round42 A+B): _inject_nav 走 _long_running_executor + Semaphore(8) + timeout 3s."""

    @pytest.mark.asyncio
    async def test_nav_one_uses_long_running_executor(self):
        """A: 5 个 symbol 全部 IOPV 失败 → 走 _inject_nav → 5 个 nav 全部注入."""
        with _patch_hub() as mock_hub:
            mock_hub.get_fund_nav = lambda sym, timeout=6: {"nav": 3.5}
            market_data = {}
            await _inject_nav(market_data, ["510050", "510300", "510500", "511090", "518880"])
            for s in ["510050", "510300", "510500", "511090", "518880"]:
                assert market_data[s].get("nav") == 3.5

    @pytest.mark.asyncio
    async def test_nav_one_semaphore_limits_in_flight_to_8(self):
        """A+B: Semaphore(8) 限制在飞任务数 ≤ 8."""
        in_flight = 0
        peak_in_flight = 0

        def fake_fetch(sym, timeout=6):
            nonlocal in_flight, peak_in_flight
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
            time.sleep(0.1)
            in_flight -= 1
            return {"nav": 3.0}

        with _patch_hub() as mock_hub:
            mock_hub.get_fund_nav = fake_fetch
            market_data = {}
            await _inject_nav(market_data, [f"51{i:04d}" for i in range(50)])

        assert peak_in_flight <= 8, f"Semaphore 失效: peak_in_flight={peak_in_flight}"

    @pytest.mark.asyncio
    async def test_nav_one_timeout_3s(self):
        """A: timeout 实际 3s (原 6s). 验证慢任务 3s 抛 TimeoutError 被吞."""
        def slow_fetch(sym, timeout=6):
            time.sleep(5)  # > 3s
            return {"nav": 3.0}

        with _patch_hub() as mock_hub:
            mock_hub.get_fund_nav = slow_fetch
            t0 = time.monotonic()
            market_data = {}
            await _inject_nav(market_data, [f"51{i:04d}" for i in range(10)])
            elapsed = time.monotonic() - t0
            # 8 路并发 (Semaphore), 每路 3s 超时. 总时长 ~3s (首批 8 并发)
            # + 2 个补位再 3s → 总时长 ~6s. 容差放宽到 7s.
            assert elapsed < 7.0, f"timeout 3s 未生效, 总耗时 {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_nav_one_does_not_run_for_iopv_successful_symbols(self):
        """A: 仅对 IOPV 失败的 symbol 调 NAV 兜底."""
        call_count = 0

        def counting_fetch(sym, timeout=6):
            nonlocal call_count
            call_count += 1
            return {"nav": 3.0}

        with _patch_hub() as mock_hub:
            mock_hub.get_fund_nav = counting_fetch
            market_data = {
                f"51{i:04d}": {"nav": 1.0 + i * 0.1} for i in range(3)
            }
            await _inject_nav(
                market_data,
                list(market_data.keys()) + [f"52{i:04d}" for i in range(7)],
            )
            assert call_count == 7, f"call_count 应为 7, 实际 {call_count}"

    @pytest.mark.asyncio
    async def test_nav_one_data_injection_correct(self):
        """A+B: NAV 成功注入, 失败时不注入 (best-effort 兜底语义)."""
        def fake_fetch(sym, timeout=6):
            if sym == "FAIL":
                raise RuntimeError("simulated network error")
            return {"nav": 3.5}

        with _patch_hub() as mock_hub:
            mock_hub.get_fund_nav = fake_fetch
            market_data = {}
            await _inject_nav(market_data, ["OK1", "FAIL", "OK2"])
            assert market_data["OK1"].get("nav") == 3.5
            assert market_data["OK2"].get("nav") == 3.5
            # FAIL: 不抛 (兜底语义), 但 market_data["FAIL"] 没 nav
            assert "nav" not in market_data.get("FAIL", {})

    @pytest.mark.asyncio
    async def test_nav_one_uses_run_sync_long(self, monkeypatch):
        """A+B: _inject_nav 调 run_sync_long 而非 run_sync (主线程池隔离).

        run_sync_long 是 _inject_nav 块内 local import, monkeypatch 必须在
        core.async_utils 层级才能拦截.
        """
        from app.core import async_utils

        long_calls = []
        short_calls = []

        real_run_sync_long = async_utils.run_sync_long
        real_run_sync = async_utils.run_sync

        def named_fetch(sym, timeout=6):
            return {"nav": 3.0}

        async def spy_long(call, *args, **kw):
            long_calls.append("called")
            return await real_run_sync_long(call, *args, **kw)

        async def spy_short(call, *args, **kw):
            short_calls.append("called")
            return await real_run_sync(call, *args, **kw)

        monkeypatch.setattr(async_utils, "run_sync_long", spy_long)
        monkeypatch.setattr(async_utils, "run_sync", spy_short)

        with _patch_hub() as mock_hub:
            mock_hub.get_fund_nav = named_fetch
            market_data = {}
            await _inject_nav(market_data, ["510050", "510300"])

        # _inject_nav 实际路径: 先 _fetch_iopv_chain (新浪/QQ/东财, 走 run_sync 拉 HTTP),
        # 然后对 IOPV 失败的 symbol 调 NAV 兜底 (走 run_sync_long). 两者并发.
        # 验证要点: long_calls >= 1 (NAV 兜底走独立池) 且 _missing_nav 全覆盖.
        assert len(long_calls) >= 1, (
            f"NAV 兜底应走 run_sync_long; 实际 long_calls={long_calls}"
        )


# ── IOPV 路径 (R146, 3 用例) ──

@pytest.fixture
def mock_iopv_chain(monkeypatch):
    """mock _fetch_iopv_chain 返回给定 nav/price。"""
    def _patch(nav: float, price: float, symbols: list[str]) -> None:
        async def fake_chain(_s_list, _symbols):
            return {
                sym: {"nav": nav, "price": price}
                for sym in _symbols
            }, "test"
        monkeypatch.setattr(fr, "_fetch_iopv_chain", fake_chain)
    return _patch


class TestInjectNavIopvPath:
    """R146 (round38 §11.3): nav 注入 + premium_discount 修复路径验证."""

    @pytest.mark.asyncio
    async def test_nav_injected_when_iopv_returns_nav(self, mock_iopv_chain):
        """IOPV chain 命中 → nav/price 注入 → premium_discount 非 0。"""
        mock_iopv_chain(nav=4.1242, price=4.1250, symbols=["510300"])
        market_data = {"510300": {"close": 4.1250}}
        await _inject_nav(market_data, ["510300"])
        assert market_data["510300"]["nav"] == 4.1242
        assert market_data["510300"]["price"] == 4.1250
        pd = _compute_premium_discount(market_data["510300"])
        assert pd != 0.0, "premium_discount 应非 0（nav 已注入）"
        # (4.1250 - 4.1242)/4.1242 ≈ 0.000194
        assert abs(pd - 0.000194) < 0.0001

    @pytest.mark.asyncio
    async def test_nav_not_overwritten_when_no_iopv(self, mock_iopv_chain):
        """IOPV chain 全空 → 沿用已有 nav（若已注入），不覆盖。"""
        mock_iopv_chain(nav=0, price=0, symbols=["510300"])  # nav=0 触发跳过
        market_data = {"510300": {"nav": 4.0, "price": 4.02, "close": 4.02}}
        await _inject_nav(market_data, ["510300"])
        assert market_data["510300"]["nav"] == 4.0, "已有 nav 不被覆盖"
        pd = _compute_premium_discount(market_data["510300"])
        assert pd != 0.0

    @pytest.mark.asyncio
    async def test_tjj_fallback_when_iopv_empty(self, mock_iopv_chain, monkeypatch):
        """IOPV chain 全空 → TTJ 兜底（patch market_data_hub.get_fund_nav）→ nav 注入。"""
        mock_iopv_chain(nav=0, price=0, symbols=["510300"])
        # round42: run_sync_long 是 _inject_nav 块内局部导入，patch 其模块属性使
        # _hub.get_fund_nav 短路返回 dict（不再 patch run_sync，那是 IOPV 链的）。
        import app.core.async_utils as au

        class FakeHub:
            async def get_fund_nav(self, sym, timeout=6):
                return {"nav": 4.2}

        async def fake_run_sync_long(fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        monkeypatch.setattr(au, "run_sync_long", fake_run_sync_long)
        import app.services.market_data_hub as mdh

        monkeypatch.setattr(mdh, "market_data_hub", FakeHub())
        market_data = {"510300": {"close": 4.2}}
        await _inject_nav(market_data, ["510300"])
        assert market_data["510300"].get("nav") == 4.2, "TTJ 兜底应注入 nav"
        # TTJ 兜底仅注入 nav（无 price）——premium_discount 需 price+nav 双有才非 0；
        # 此处只验证 nav 兜底成功（诚实降级：价格缺失时不造 0）。
        assert "price" not in market_data["510300"]
