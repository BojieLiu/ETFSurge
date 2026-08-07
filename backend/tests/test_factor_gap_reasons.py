"""
O25 (docs/round8-rediagnosis.md §7 P6-新): 因子模型 6 项数据缺失 + reason 补全。

现象: /factors/active no_data=6（etf.premium_discount / etf.tracking_error /
etf.shares_change / sentiment.panic_greed_diff / sentiment.stock_divergence /
sentiment.news_direction），reason 全部为笼统「IC 未累积（样本 <3）」。
根因: ET_SPECIFIC_GAP_CODES（factor_registry.py:588-596）只含 etf 四因子 +
industry_diversification，sentiment 三因子不在任何缺口集合 → _status_of 查
_data_source_gaps 无记录 → 落「IC 未累积」兜底。

修复（已拍板：⑦ 缺口集合补全）: ET_SPECIFIC_GAP_CODES 增加 sentiment 三因子
缺口键，让 reason 能落到「数据源未接入（缺 xxx）」而非笼统「IC 未累积」。
"""

import pytest

from app.routers.factors import _status_of, GAP_FIELD_MAP
from app.factors.factor_registry import ET_SPECIFIC_GAP_CODES


class TestGapCodeCoverage:
    def test_all_six_gap_codes_present(self):
        """6 项 no_data 因子的缺口键全部在 ET_SPECIFIC_GAP_CODES 中。"""
        for code in [
            "etf.premium_discount",
            "etf.tracking_error",
            "etf.shares_change",
            "sentiment.panic_greed_diff",
            "sentiment.stock_divergence",
            "sentiment.news_direction",
        ]:
            assert code in ET_SPECIFIC_GAP_CODES, f"缺口集合缺 {code}"
            assert ET_SPECIFIC_GAP_CODES[code]

    def test_sentiment_fields_mapped(self):
        """sentiment 三因子映射到对应数据源字段（非笼统「必要字段」）。"""
        assert "sentiment_index" in ET_SPECIFIC_GAP_CODES["sentiment.panic_greed_diff"]
        assert "advance_decline" in ET_SPECIFIC_GAP_CODES["sentiment.stock_divergence"]
        assert "news_items" in ET_SPECIFIC_GAP_CODES["sentiment.news_direction"]


class FakeRegistry:
    def __init__(self, gaps):
        self._data_source_gaps = gaps
        self._constant_factor_codes = set()
        self._sample_counts = {}


class TestStatusReason:
    def test_etf_gap_reason(self, monkeypatch):
        """etf 缺口 reason 含对应字段（nav）。"""
        import app.routers.factors as fr
        monkeypatch.setattr(fr, "registry", FakeRegistry({"etf.premium_discount": ["510300"]}))
        status, reason = _status_of("etf.premium_discount", None, 0.02)
        assert status == "no_data"
        assert "数据源未接入" in reason
        assert "nav" in reason

    def test_sentiment_gap_reason_not_fallback(self, monkeypatch):
        """sentiment 缺口 reason 为「数据源未接入（缺 对应字段）」而非「IC 未累积」。"""
        import app.routers.factors as fr
        monkeypatch.setattr(fr, "registry", FakeRegistry(
            {"sentiment.panic_greed_diff": ["510300", "510500"]}
        ))
        status, reason = _status_of("sentiment.panic_greed_diff", None, 0.02)
        assert status == "no_data"
        assert "数据源未接入" in reason
        assert "sentiment_index" in reason
        assert "IC 未累积" not in reason

    def test_stock_divergence_reason(self, monkeypatch):
        import app.routers.factors as fr
        monkeypatch.setattr(fr, "registry", FakeRegistry(
            {"sentiment.stock_divergence": ["510300"]}
        ))
        status, reason = _status_of("sentiment.stock_divergence", None, 0.02)
        assert status == "no_data"
        assert "advance_decline" in reason

    def test_no_gap_falls_back_to_ic_not_accumulated(self, monkeypatch):
        """无缺口记录 → 仍走「IC 未累积」兜底（不破坏既有语义）。"""
        import app.routers.factors as fr
        monkeypatch.setattr(fr, "registry", FakeRegistry({}))
        status, reason = _status_of("technical.rsi.rsi_14", None, 0.02)
        assert status == "no_data"
        assert "IC 未累积" in reason

    def test_gap_field_map_still_applies(self):
        """GAP_FIELD_MAP 的 style.size 键仍优先（非 etf_specific 缺口字段名）。"""
        assert GAP_FIELD_MAP["style.size.ln_mcap"] == "fund_scale/total_mv"
