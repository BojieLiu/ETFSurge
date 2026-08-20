# -*- coding: utf-8 -*-
"""round31 R96: factor_data_quality valid_rate 口径误导。

根因（§4.4）：`_factor_data_quality_report`（strategy_design.py:998-1058）复用 F25②
`_status_of` IC 样本门禁（样本<250 交易日 → no_data）→ 数据积累期 valid_rate 恒 0%、
`factor_missing_pct=100`「方案仅供参考」，而 rationale 已引用真实 RSI/动量——meta 与
正文自相矛盾。R85 修复后**数据可用性 ≠ IC 积累**，指标未拆两维。

修复：拆「数据可用性」（字段就位率，R85 后技术因子有值 → valid_rate>0）与
「IC 积累」（样本 N/250 交易日，独立标注）两维。

无网络：纯函数断言（monkeypatch registry 状态）。
"""
import pytest


def _make_report(monkeypatch, factors=None, ic_series=None, samples=None,
                 gaps=None, constants=None):
    """构造 _factor_data_quality_report 的 registry 状态并返回报告。"""
    from app.services import strategy_design as sd
    from app.factors import factor_registry as freg

    monkeypatch.setattr(freg.registry, "_factors", factors or {})
    monkeypatch.setattr(freg.registry, "_ic_series_cache", ic_series or {})
    monkeypatch.setattr(freg.registry, "_data_source_gaps", gaps or {})
    monkeypatch.setattr(freg.registry, "_constant_factor_codes", constants or set())
    monkeypatch.setattr(freg.registry, "_sample_counts", samples or {})
    return sd._factor_data_quality_report()


class TestR96DataAvailabilityDimension:
    def test_valid_rate_positive_when_data_available(self, monkeypatch):
        """数据可用（字段就位、样本 240/250 积累中）→ valid_rate>0 且不 degraded。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(10)}
        # 技术因子字段已就位（无 gaps），但 IC 样本 240 < 250（积累中）
        samples = {f"test.factor_{i}": 240 for i in range(10)}
        ic = {f"test.factor_{i}": [0.02] * 240 for i in range(10)}
        report = _make_report(monkeypatch, factors=factors, ic_series=ic,
                              samples=samples, gaps={})
        # R96 ①：数据可用率 > 0，不再恒 0%
        assert report["valid_rate"] > 0, f"数据可用时应 valid_rate>0，实际 {report}"
        assert report["data_available"] == 10
        assert report["degraded"] is False, f"数据可用不应降级，实际 {report}"
        # IC 积累维度独立标注（样本 240/250）
        acc = report["ic_accumulation"]
        assert acc["median_samples"] == 240
        assert "240/250" in acc["note"]
        # 负向：note 不再说「缺失 100%」
        assert "缺失 100" not in report["note"]

    def test_degraded_when_data_unavailable(self, monkeypatch):
        """字段缺口（数据源未接入）→ valid_rate 低 + degraded True。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(10)}
        # 8/10 因子缺 nav/benchmark_close 等字段
        gaps = {f"test.factor_{i}": ["510300"] for i in range(8)}
        report = _make_report(monkeypatch, factors=factors, gaps=gaps)
        assert report["data_available"] == 2
        assert report["valid_rate"] < 0.6
        assert report["degraded"] is True

    def test_all_missing_still_zero(self, monkeypatch):
        """负向：数据全缺失（字段全缺口）→ 仍报 0%（不误报正常）。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(5)}
        gaps = {f"test.factor_{i}": ["510300"] for i in range(5)}
        report = _make_report(monkeypatch, factors=factors, gaps=gaps)
        assert report["valid_rate"] == 0.0
        assert report["data_available"] == 0
        assert report["degraded"] is True

    def test_ic_valid_factors_still_counted(self, monkeypatch):
        """IC 统计显著（t≥2/IR≥0.5、样本 260）→ valid 计数保留（向后兼容）。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(10)}
        ic = {
            f"test.factor_{i}": [0.05 + (i % 7) * 0.002 for i in range(260)]
            for i in range(8)
        }
        ic.update({f"test.factor_{i}": None for i in range(8, 10)})
        samples = {f"test.factor_{i}": 260 for i in range(8)}
        report = _make_report(monkeypatch, factors=factors, ic_series=ic,
                              samples=samples, gaps={})
        assert report["valid"] >= 8
        assert report["ic_accumulation"]["median_samples"] == 260
