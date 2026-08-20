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
                 gaps=None, constants=None, produced=None):
    """构造 _factor_data_quality_report 的 registry 状态并返回报告。"""
    from app.services import strategy_design as sd
    from app.factors import factor_registry as freg

    monkeypatch.setattr(freg.registry, "_factors", factors or {})
    monkeypatch.setattr(freg.registry, "_ic_series_cache", ic_series or {})
    monkeypatch.setattr(freg.registry, "_data_source_gaps", gaps or {})
    monkeypatch.setattr(freg.registry, "_constant_factor_codes", constants or set())
    monkeypatch.setattr(freg.registry, "_sample_counts", samples or {})
    # R100: produced 状态显式注入——默认 {} 表示 compute() 未跑过（回退定义就位率），
    # 保证既有 R96 用例确定性（不依赖测试套件中其它 compute() 调用的残留状态）。
    monkeypatch.setattr(freg.registry, "_last_compute_produced",
                        {} if produced is None else produced)
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


class TestR100ActualOutputRate:
    """round32 R100: 数据可用性口径对齐 compute() 实际产出（guard S2）。

    根因：`_factor_data_quality_report` 的「数据可用性」= 定义层 `_data_source_gaps`
    （字段无缺口即「可用」），而 factor_breakdown 实际值 = compute() 产出。盘后
    etf.return_* 未产出（None）但无 gap 标注 → 旧口径报「97% 可用」掩盖占位退化
    （设计 697 实证）。

    修复：data_available/valid_rate 改用 `_last_compute_produced`（compute() 非 None
    数值的因子键数）；新增 definition_ready_pct（定义就位率）与 actual_output_rate
    （实际产出率）并列，口径脱节显性化。
    """

    def test_data_available_matches_produced_keys(self, monkeypatch):
        """R100 ①: compute() 产出的键数即 data_available（对齐 factor_breakdown）。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(10)}
        # 只有 5/10 因子在 compute() 中产出非 None 数值（如盘后 etf.return_* no_data）
        produced = {f"test.factor_{i}": 1 for i in range(5)}
        report = _make_report(monkeypatch, factors=factors, gaps={}, produced=produced)
        assert report["data_available"] == 5, (
            f"data_available 应对齐 compute() 实际产出 5，实际 {report['data_available']}"
        )
        assert report["data_available_pct"] == pytest.approx(0.5, abs=1e-4)
        assert report["actual_output_rate"] == pytest.approx(0.5, abs=1e-4)
        # 定义就位率仍反映字段缺口口径（gaps 全空 → 100%）
        assert report["definition_ready_pct"] == pytest.approx(1.0, abs=1e-4)
        assert report["degraded"] is True, "实际产出率 50% < 60% 应降级"

    def test_negative_degraded_output_not_reported_97pct(self, monkeypatch):
        """负向：factor_breakdown 退化为占位值时 data_available 不得报 97%（掩盖退化）。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(50)}
        # 场景复刻设计 697：定义 193 只，但盘后大量因子未产出——仅 20 键产出
        produced = {f"test.factor_{i}": 1 for i in range(20)}
        report = _make_report(monkeypatch, factors=factors, gaps={}, produced=produced)
        assert report["data_available"] == 20
        assert report["data_available_pct"] < 0.5, (
            f"占位退化时 data_available_pct 不得报 97%，实际 {report['data_available_pct']}"
        )
        assert "97%" not in report["note"]
        # 口径脱节显性化：定义就位率 100%（无 gap）vs 实际产出率 40%
        assert report["definition_ready_pct"] == pytest.approx(1.0, abs=1e-4)
        assert report["actual_output_rate"] == pytest.approx(0.4, abs=1e-4)
        assert report["degraded"] is True

    def test_fallback_when_no_compute_ran(self, monkeypatch):
        """compute() 未跑过（produced 空）→ 回退定义就位率（不误报降级）。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(10)}
        report = _make_report(monkeypatch, factors=factors, gaps={})
        assert report["data_available"] == 10
        assert report["data_available_pct"] == pytest.approx(1.0, abs=1e-4)
        # 回退时实际产出率无从统计 → None（诚实「未知」，非假 0%）
        assert report["actual_output_rate"] is None
        assert report["degraded"] is False

    def test_definition_ready_tracks_gaps_independent(self, monkeypatch):
        """定义就位率独立跟踪 _data_source_gaps——与实际产出口径可分离。"""
        factors = {f"test.factor_{i}": {"name": f"F{i}"} for i in range(10)}
        # 3 因子字段缺口（定义未就位），但 compute() 产出了 8 个（gap 与产出可并存）
        gaps = {f"test.factor_{i}": ["510300"] for i in range(3)}
        produced = {f"test.factor_{i}": 1 for i in range(8)}
        report = _make_report(monkeypatch, factors=factors, gaps=gaps, produced=produced)
        assert report["definition_ready"] == 7
        assert report["definition_ready_pct"] == pytest.approx(0.7, abs=1e-4)
        assert report["data_available"] == 8
        assert report["actual_output_rate"] == pytest.approx(0.8, abs=1e-4)
        # 脱节显性化：定义 70% vs 实际 80%——两维并列可查
        assert report["definition_ready_pct"] != report["actual_output_rate"]
