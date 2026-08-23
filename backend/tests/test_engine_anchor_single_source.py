"""round35 B1-F2/F3 (docs/round35-architecture-review.md §4.2/§4.3/§6.1) —

锚常量与公司名单单一真相源收敛验证：
- F2: CORE_ANCHORS/DEFENSE_ANCHORS/MANDATORY_CODES/MANDATORY_MIN_WEIGHT/
  MANDATORY_FLOOR 真相源上移 budgets.py；allocation_engine re-export；
  pool_balancing 删本地字面量、使用点 lazy import。
- F3: _COMPANY_NAMES 并集单源（allocation_engine）+ 两处提取函数统一 len 降序替换。

负向断言：monkeypatch budgets.MANDATORY_CODES 注入假锚 → pool_balancing 视野
必须同步可见（若仍是独立副本即 FAIL——能抓住「改了一半」的回归）。
"""
import pytest

from app.engine import allocation_engine, budgets, pool_balancing
from app.engine.allocation_engine import _extract_index_concept


# ── F2: 锚常量单一真相源 ──────────────────────────────────────────

def test_mandatory_codes_identity_with_budgets():
    """allocation_engine re-export 与 budgets 真相源是**同一对象**（防再次复制）。"""
    assert allocation_engine.MANDATORY_CODES is budgets.MANDATORY_CODES
    assert allocation_engine.CORE_ANCHORS is budgets.CORE_ANCHORS
    assert allocation_engine.DEFENSE_ANCHORS is budgets.DEFENSE_ANCHORS


def test_anchor_values_unchanged():
    """值原样搬移：换锚历史（560600→159338）不得因重构而变化。"""
    assert budgets.CORE_ANCHORS == {"510300", "159338"}
    assert budgets.DEFENSE_ANCHORS == {"518880", "511090"}
    assert budgets.MANDATORY_CODES == {"510300", "159338", "518880", "511090"}
    assert budgets.MANDATORY_MIN_WEIGHT == 0.03
    assert budgets.MANDATORY_FLOOR == 0.05


def test_no_local_literal_copy_in_pool_balancing(monkeypatch):
    """负向：篡改 budgets 真相源注入假锚 → pool_balancing 视野同步可见。
    若 pool_balancing 仍持有独立字面量副本，ensure_mandatory 将无视假锚 → FAIL。"""
    fake = {"999999", *budgets.MANDATORY_CODES}
    monkeypatch.setattr(budgets, "MANDATORY_CODES", fake)

    flat = [
        {"symbol": "999999", "name": "假锚ETF", "tracked_index": "", "fund_scale": 10.0},
        {"symbol": "510300", "name": "沪深300ETF", "tracked_index": "沪深300", "fund_scale": 100.0},
        {"symbol": "512480", "name": "半导体ETF", "tracked_index": "半导体", "fund_scale": 50.0},
    ]
    pool = {layer: [] for layer in pool_balancing.ALL_LAYERS}
    pool_balancing.ensure_mandatory(pool, flat)
    all_syms = {e["symbol"] for layer in pool.values() for e in layer}
    assert "999999" in all_syms, (
        "pool_balancing 未跟随 budgets 真相源——存在未清理的字面量副本（改了一半）"
    )


def test_truncate_protection_follows_truth_source(monkeypatch):
    """truncate_with_mandatory_protection 的保护视野同样来自 budgets。"""
    fake = {"888888"}
    monkeypatch.setattr(budgets, "MANDATORY_CODES", fake)
    balanced = [
        {"symbol": "512480", "name": "半导体ETF"},
        {"symbol": "888888", "name": "假锚ETF"},
    ]
    out = pool_balancing.truncate_with_mandatory_protection(balanced, max_n=1)
    assert out[0]["symbol"] == "888888"


# ── F3: 公司名单单源 + len 降序 ────────────────────────────────────

def test_company_names_superset_converged():
    """pool_balancing 不再持有局部副本；单源名单为并集（含长名条目）。"""
    for required in ("华泰柏瑞", "天弘基金", "广发基金", "金元顺安", "爱建"):
        assert required in allocation_engine._COMPANY_NAMES


def test_extract_concept_len_desc_no_residue():
    """「A500ETF华泰柏瑞」不残留「柏瑞」（长名优先于子串「华泰」，round19 P1-② 根治）。"""
    concept = _extract_index_concept("A500ETF华泰柏瑞")
    assert concept == "A500"
    assert "柏瑞" not in concept


def test_extract_concept_basic_cases():
    assert _extract_index_concept("科创100ETF汇添富") == "科创100"
    assert _extract_index_concept("沪深300ETF华夏") == "沪深300"


def test_pool_balancing_dedup_uses_shared_list():
    """deduplicate_by_index 对无 tracked_index 条目按名称概念去重时，
    长名优先语义生效（华泰柏瑞整体剥除 → 与其它 A500 同概念合并留规模大者）。"""
    pool = {
        "core": [
            {"symbol": "563360", "name": "A500ETF华泰柏瑞", "tracked_index": "", "fund_scale": 80.0},
            {"symbol": "159339", "name": "A500ETF华夏", "tracked_index": "", "fund_scale": 90.0},
        ],
    }
    result = pool_balancing.deduplicate_by_index(pool)
    # 两只同概念（均为 A500）→ 只留规模大的一只
    syms = [e["symbol"] for e in result["core"]]
    assert syms == ["159339"]
