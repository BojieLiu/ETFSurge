"""
round19 P1（问题 1：组合关联度）测试（2026-08-12 实施）：
- correlation.py 纯函数（构造 r=1.0/-1.0/0；窗口 <30 → None）
- rationale 文案条件化（correlation_median=None 时不含「低相关」；<0.3 时允许）
- _dedup_same_index 同指数硬约束（aggressive 不得同时含两只 A500；强制锚豁免）
- 关键词补漏（A500ETF华泰柏瑞 → 大盘宽基识别）
"""

import pytest

from app.engine.correlation import (
    correlation_matrix, high_correlation_pairs, avg_correlation,
    median_correlation_for,
)
from app.engine.rationale import build_rationale
from app.engine.allocation_engine import (
    _dedup_same_index, _is_large_cap_wide_basis, MANDATORY_CODES,
)


def _series(base, drift=0.001, n=80):
    """构造近 n 根单调上涨序列（同 drift → r≈1.0；反向 drift → r≈-1.0）。"""
    out = []
    v = base
    for i in range(n):
        v += drift
        out.append(v)
    return out


def _wave(base, amp, phase, n=80):
    """正弦波动序列（相位差 π → r≈-1.0；不同频率 → r≈0）。"""
    import math
    return [base + amp * math.sin(i / 5.0 + phase) for i in range(n)]


class TestCorrelationEngine:
    """round19 P1-①: correlation.py 纯函数。"""

    def test_matrix_perfectly_correlated(self):
        closes = {
            "510300": _series(4.0),
            "159338": _series(4.1),  # 同向同漂移 → r≈1.0
        }
        m = correlation_matrix(closes, window=60)
        r = m[("159338", "510300")]
        assert r is not None and abs(r - 1.0) < 0.02, f"同向序列 r 应≈1.0，实得 {r}"

    def test_matrix_negative_correlation(self):
        closes = {
            "A": _wave(4.0, 0.1, 0.0),
            "B": _wave(4.0, 0.1, 3.14159),  # 反相 → r≈-1.0
        }
        m = correlation_matrix(closes, window=60)
        r = m[("A", "B")]
        assert r is not None and abs(r + 1.0) < 0.05, f"反向序列 r 应≈-1.0，实得 {r}"

    def test_window_insufficient_returns_none(self):
        """历史 <30 根 → r=None（数据不足诚实标注，负向：0 冒充 → FAIL）。"""
        closes = {"A": _series(4.0, n=20), "B": _series(5.0, n=80)}
        m = correlation_matrix(closes, window=60)
        assert m[("A", "B")] is None, "数据不足标的 r 应为 None 而非 0"

    def test_high_correlation_pairs_threshold(self):
        closes = {"A": _series(4.0), "B": _series(4.1), "C": _series(50.0, drift=-0.01)}
        m = correlation_matrix(closes, window=60)
        pairs = high_correlation_pairs(m, threshold=0.8)
        assert len(pairs) >= 1
        assert pairs[0][0] > 0.8

    def test_avg_correlation(self):
        closes = {"A": _series(4.0), "B": _series(4.1), "C": _series(50.0, drift=-0.01)}
        m = correlation_matrix(closes, window=60)
        avg = avg_correlation(m, ["A", "B", "C"])
        assert avg is not None and -1 <= avg <= 1

    def test_median_correlation_for(self):
        closes = {"A": _series(4.0), "B": _series(4.1), "C": _series(50.0, drift=-0.01)}
        m = correlation_matrix(closes, window=60)
        med = median_correlation_for(m, "A", ["B", "C"])
        assert med is not None


class TestRationaleCorrelationGuard:
    """round19 P1-③: rationale「低相关性」措辞条件化。"""

    def _rationale(self, correlation_median):
        return build_rationale(
            code="513500",
            layer="defense",
            strategy="defensive",
            meta={"name": "标普500ETF", "tracked_index": "标普500"},
            factor_scores={"momentum": 0.3},
            correlation_median=correlation_median,
        )

    def test_none_median_no_low_correlation_claim(self):
        """correlation_median=None（矩阵不可用）→ 不含「低相关」字样（负向：None 时
        出现「低相关」→ FAIL——杜绝无数据冒充低相关）。"""
        r = self._rationale(None)
        assert "低相关" not in r, f"矩阵不可用不应声称低相关: {r}"
        assert "防御" in r or "避险" in r or "下行" in r, "应回退中性防御文案"

    def test_high_median_no_low_correlation_claim(self):
        r = self._rationale(0.6)
        assert "低相关" not in r

    def test_low_median_allows_low_correlation(self):
        """correlation_median=0.1（<0.3）→ 防御池保留低相关句（可被抽样命中）。"""
        from app.engine.rationale import _layer_phrase, _DEFENSE_PHRASES
        # 防御池本身含低相关句
        assert any("低相关" in fn("X") for fn in _DEFENSE_PHRASES)
        # median=0.1 时不过滤 → 多 sym 抽样至少 1 条含「低相关性/低相关」
        hit = any(
            "低相关" in _layer_phrase("defense", "标普500ETF", sym, "defensive", 0.1)
            for sym in ["513500", "513300", "518880", "511090", "159920", "513100", "513050", "159941", "513080", "513180"]
        )
        assert hit, "真实低相关（0.1）时防御池应保留低相关句"

    def test_high_median_filters_all_samples(self):
        """median=0.6（≥0.3）→ 多 sym 抽样均不含低相关句。"""
        from app.engine.rationale import _layer_phrase
        for sym in ["513500", "513300", "518880", "511090"]:
            r = _layer_phrase("defense", "标普500ETF", sym, "defensive", 0.6)
            assert "低相关" not in r, f"median=0.6 不应出现低相关措辞: {r}"


class TestDedupSameIndex:
    """round19 P1-②: 同指数双持有硬约束。"""

    def _alloc(self, symbol, name, layer, weight, fs, tidx=None):
        return {"symbol": symbol, "name": name, "layer": layer,
                "weight": weight, "factor_score": fs, "tracked_index": tidx}

    def test_aggressive_no_dual_a500(self):
        """159338 中证A500（强制锚 core）+ 563360 A500ETF（satellite）→ 剔除非锚低分者
        （负向：同仓双 A500 → FAIL）。"""
        allocs = [
            self._alloc("159338", "中证A500ETF国泰", "core", 0.05, 0.8, "中证A500"),
            self._alloc("563360", "A500ETF华泰柏瑞", "satellite", 0.2064, 0.3, ""),
            self._alloc("510300", "沪深300ETF", "core", 0.1, 0.7, "沪深300"),
        ]
        out = _dedup_same_index(allocs)
        syms = {a["symbol"] for a in out}
        assert "563360" not in syms, "非锚低分 A500 应被剔除（双持有）"
        assert "159338" in syms, "强制锚豁免剔除"
        # 剔除权重回补同层——satellite 层只有 563360 一只被剔、无同层可回补 →
        # 权重丢弃（allocate 主流程转为现金 = 1 - Σ权重）
        total = sum(a["weight"] for a in out)
        assert abs(total - 0.15) < 1e-6, f"剔除权重应转为现金，实得 {total}"

    def test_mandatory_anchor_pair_exempt(self):
        """510300 + 159338 双强制锚（r=0.983）→ 豁免剔除（不报错）。"""
        allocs = [
            self._alloc("510300", "沪深300ETF", "core", 0.06, 0.7, "沪深300"),
            self._alloc("159338", "中证A500ETF国泰", "core", 0.05, 0.8, "中证A500"),
        ]
        out = _dedup_same_index(allocs)
        assert {a["symbol"] for a in out} == {"510300", "159338"}

    def test_same_layer_weight_reclaim(self):
        """同层双持有（无锚）→ 低分者剔除、权重按同层其余标的权重比例回补。"""
        allocs = [
            self._alloc("588200", "科创芯片ETF", "satellite", 0.03, 0.6, "芯片"),
            self._alloc("159995", "芯片ETF", "satellite", 0.05, 0.2, "芯片"),
            self._alloc("515880", "通信ETF", "satellite", 0.05, 0.5, "通信"),
        ]
        out = _dedup_same_index(allocs)
        syms = {a["symbol"] for a in out}
        assert "159995" not in syms, "低分芯片应剔除"
        # 剔除 0.05 → 按同层剩余权重比例回补：588200(0.03) 与 515880(0.05)
        kept_comm = next(a for a in out if a["symbol"] == "515880")
        kept_chip = next(a for a in out if a["symbol"] == "588200")
        # round(…,4) 精度 → 断言放宽 1e-3
        assert kept_comm["weight"] == pytest.approx(0.05 + 0.05 * 0.05 / 0.08, abs=1e-3)
        assert kept_chip["weight"] == pytest.approx(0.03 + 0.05 * 0.03 / 0.08, abs=1e-3)
        # 权重守恒（不含 CASH；round(…,4) 累计误差放宽）
        assert abs(sum(a["weight"] for a in out) - 0.13) < 1e-3


class TestKeywordGap:
    """round19 P1-②: 裸 A500/A50 关键词补漏（563360 漏判场景）。"""

    def test_bare_a500_detected_as_large_cap(self):
        c = {"name": "A500ETF华泰柏瑞", "tracked_index": ""}
        assert _is_large_cap_wide_basis(c) is True, "裸 A500 应判大盘宽基（旧实现漏判）"
