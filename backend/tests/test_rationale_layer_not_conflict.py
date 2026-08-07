"""
O16 (docs/round8-rediagnosis.md §7 §5.1B): rationale 宽基风格统一。

根因: _style_probe 宽基关键词缺 A100/A50/A500/深证100/MSCI/上证180 → 562000
A100ETF 被误判 theme_satellite → core 层抽到「卫星仓位，高弹性品种」；
中证500 归 low_vol_wide → 抽到「大盘价值代表性」（中盘被说成大盘价值）。
短语池「压舱石低波」与「价值代表/高弹性」混池按 symbol hash 随机抽。

修复: _style_probe 并入 A100/A50/A500/深证100/MSCI/上证180；_CORE_PHRASES 删除
「大盘价值代表性」改中性「宽基底仓」；_layer_phrase 对 core/defense 层过滤
「卫星」语义句。

验收: ① 510500（中证500 core）文案不再含"大盘价值代表性"；② 562000（A100 core）
不再出现"卫星仓位/高弹性品种"；③ test_rationale_layer_not_conflict（layer=core
短语不含"卫星"）。
"""

import pytest

from app.engine.rationale import build_rationale, _style_probe, _layer_phrase


def _meta(tidx, name):
    return {"tracked_index": tidx, "name": name, "industry": ""}


class TestStyleProbe:
    def test_a100_is_wide_basis(self):
        """A100ETF 归 low_vol_wide（此前被误判 theme_satellite）。"""
        assert _style_probe(_meta("中证A100", "A100ETF华宝")) == "low_vol_wide"

    def test_z500_midcap_wide(self):
        assert _style_probe(_meta("中证500", "中证500ETF南方")) == "low_vol_wide"

    def test_shenzhen100_msci(self):
        assert _style_probe(_meta("深证100", "深证100ETF")) == "low_vol_wide"
        assert _style_probe(_meta("MSCI中国A50", "MSCI A50ETF")) == "low_vol_wide"

    def test_theme_still_satellite(self):
        """主题标的仍归 theme_satellite（不误伤）。"""
        assert _style_probe(_meta("中证军工", "军工ETF")) == "theme_satellite"
        assert _style_probe(_meta("", "半导体设备ETF")) == "high_growth"


class TestLayerNotConflict:
    def test_core_phrase_never_contains_satellite(self):
        """③: layer=core 时短语不含「卫星」（过滤 + 中性池兜底）。"""
        for style in ("low_vol_wide", "high_growth", "theme_satellite", "defensive"):
            for _ in range(30):
                txt = _layer_phrase("core", "某宽基ETF", "510500", style)
                assert "卫星" not in txt, f"core 层短语含卫星: {txt} (style={style})"

    def test_510500_no_da_pan_value(self):
        """①: balance 方案 510500（中证500 core）文案不含「大盘价值代表性」。"""
        text = build_rationale(
            "510500", "core", "balanced",
            meta=_meta("中证500", "中证500ETF南方"),
            factor_scores={"technical.rsi.rsi_14_raw": 55.0},
        )
        assert "大盘价值代表性" not in text
        assert "卫星" not in text

    def test_562000_no_satellite_high_beta(self):
        """②: 562000（A100 core）不再出现「卫星仓位/高弹性品种」。"""
        text = build_rationale(
            "562000", "core", "balanced",
            meta=_meta("中证A100", "A100ETF华宝"),
            factor_scores={"technical.rsi.rsi_14_raw": 50.0},
        )
        assert "卫星" not in text
        assert "高弹性" not in text

    def test_satellite_layer_still_uses_theme_phrases(self):
        """satellite 层保留弹性语义（不误伤卫星标的）。"""
        txt = _layer_phrase("satellite", "军工ETF", "512660", "theme_satellite")
        assert txt  # 非空即可（可能命中弹性句或主题句）
