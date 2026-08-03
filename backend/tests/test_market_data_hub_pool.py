"""
R5-0-1: 候选池强制标的二次校验（docs/round5-diagnosis-and-optimization-plan.md §十 P0）。

背景：`_ensure_mandatory` 在 MAX_PER_LAYER 截断前执行，截断（含行业均衡挤出）后
强制标的（560600 等）可能被挤出候选池 → P1-1 A500 缺失真实链路复验 FAIL。
修复：①截断时保护强制标的（截断前剔除 MANDATORY_CODES，截断后再补回）；
     ②截断后二次校验（MANDATORY_CODES ∪ CORE_REQUIRED 缺失时从 flat 找回注入 + WARNING）。

纯函数/轻量 mock 测试，无网络。
"""
import pytest

from app.services.market_data_hub import (
    MarketDataHub,
    MANDATORY_CODES,
    LAYER_CORE,
    LAYER_SATELLITE,
    LAYER_DEFENSE,
)


def _make_hub():
    """轻量构造 hub 实例（不跑 __init__ 的 I/O 逻辑）。"""
    return MarketDataHub.__new__(MarketDataHub)


def _flat_with(code, name="test-etf", layer="core"):
    return {"symbol": code, "name": name, "layer": layer,
            "tracked_index": name, "industry": "宽基指数", "segment": name}


class TestTruncateProtectsMandatory:
    """R5-0-1 用例②：MAX_PER_LAYER 截断前剔除 MANDATORY_CODES，截断后再补回。"""

    def test_truncate_keeps_mandatory_beyond_max(self):
        """截断 max_n=3 时，排在末尾的强制标的 560600 必须保留。"""
        hub = _make_hub()
        balanced = [
            {"symbol": "588000", "name": "科创50ETF"},
            {"symbol": "159915", "name": "创业板ETF"},
            {"symbol": "510050", "name": "上证50ETF"},
            {"symbol": "560600", "name": "中证A500ETF"},  # 强制标的，排第 4
        ]
        result = hub._truncate_with_mandatory_protection(balanced, max_n=3)
        syms = [e["symbol"] for e in result]
        assert "560600" in syms, f"截断后强制标的 560600 被挤出: {syms}"
        # 非强制标的仍按 max_n 截断
        non_mandatory = [s for s in syms if s not in MANDATORY_CODES]
        assert len(non_mandatory) <= 3, f"非强制标的超过 max_n: {non_mandatory}"

    def test_truncate_no_mandatory_plain_slice(self):
        """池中无强制标的时，行为与普通截断一致。"""
        hub = _make_hub()
        balanced = [
            {"symbol": "588000"}, {"symbol": "159915"}, {"symbol": "510050"},
            {"symbol": "512480"}, {"symbol": "515030"},
        ]
        result = hub._truncate_with_mandatory_protection(balanced, max_n=3)
        assert [e["symbol"] for e in result] == ["588000", "159915", "510050"]


class TestRecheckMandatoryAfterTruncate:
    """R5-0-1 用例①：截断后二次校验，缺失强制标的从 flat 找回注入。"""

    def test_recheck_injects_missing_mandatory(self):
        """pool 截断后缺失 560600 → 二次校验从 flat 找回注入 core 层。"""
        hub = _make_hub()
        pool = {
            LAYER_CORE: [{"symbol": "510300", "name": "沪深300ETF"}],
            LAYER_SATELLITE: [],
            LAYER_DEFENSE: [],
        }
        flat = [_flat_with("560600", "中证A500ETF")]
        hub._recheck_mandatory_after_truncate(pool, flat)
        core_syms = [e["symbol"] for e in pool[LAYER_CORE]]
        assert "560600" in core_syms, f"二次校验未注入 560600: {core_syms}"

    def test_recheck_skips_when_present(self):
        """强制标的本就在池中 → 二次校验不重复注入、不抛异常。"""
        hub = _make_hub()
        pool = {
            LAYER_CORE: [{"symbol": "560600", "name": "中证A500ETF"}],
            LAYER_SATELLITE: [],
            LAYER_DEFENSE: [],
        }
        flat = [_flat_with("560600", "中证A500ETF")]
        hub._recheck_mandatory_after_truncate(pool, flat)
        core_syms = [e["symbol"] for e in pool[LAYER_CORE]]
        assert core_syms.count("560600") == 1, "强制标的被重复注入"

    def test_recheck_flat_empty_noop(self):
        """flat 为空（扫描失败）→ 不注入、不抛异常（与 _ensure_mandatory 语义一致）。"""
        hub = _make_hub()
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: []}
        hub._recheck_mandatory_after_truncate(pool, [])
        assert pool[LAYER_CORE] == []

    def test_recheck_missing_from_flat_warns_noop(self):
        """flat 中没有 560600 → 无法注入，但不抛异常（仅 WARNING）。"""
        hub = _make_hub()
        pool = {LAYER_CORE: [], LAYER_SATELLITE: [], LAYER_DEFENSE: []}
        flat = [_flat_with("588000", "科创50ETF")]
        # 不应抛异常
        hub._recheck_mandatory_after_truncate(pool, flat)
        assert pool[LAYER_CORE] == []
