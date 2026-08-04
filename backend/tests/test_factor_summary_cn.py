"""F11 (round6 §15.3): 因子评分中文解读——FACTOR_LABELS 映射 + 方向/值域解读。

现象：持仓明细"因子评分"栏为原始因子键值对——
`sentiment.news_heat: 100.00; technical.rsi.rsi_14: 39.53; technical.kdj.d_value: -3.46`
无中文名、无方向含义、无值域说明（§15.3）。

修复：新增 format_factor_summary(real_fs) —— 键→中文名映射
（news_heat→"新闻热度"、rsi_14→"RSI(14)"、kdj.d_value→"KDJ.D" 等）
+ 方向/值域解读（RSI<30 超卖/30-70 中性/>70 超买；KDJ D 负→超卖区），
保持 factor_summary 字符串契约不变（前端 td 零改动）。
"""
from app.services.portfolio_service import format_factor_summary


class TestFactorSummaryChinese:
    def test_key_mapping_chinese_name(self):
        """F11: 因子键映射中文名（新闻热度/RSI(14)/KDJ.D）。"""
        s = format_factor_summary({
            "sentiment.news_heat": 100.0,
            "technical.rsi.rsi_14": 39.53,
            "technical.kdj.d_value": -3.46,
        })
        assert "新闻热度" in s, f"应含中文名'新闻热度', got {s}"
        assert "RSI(14)" in s or "RSI" in s, f"应含 RSI 名, got {s}"
        assert "KDJ" in s, f"应含 KDJ 名, got {s}"
        # 原键名不应裸露出现
        assert "sentiment.news_heat" not in s, f"不应裸拼因子键, got {s}"
        assert "technical.rsi.rsi_14" not in s

    def test_rsi_value_range_interpretation(self):
        """F11: RSI 值域解读——39.5 中性、85 超买、15 超卖。"""
        s_mid = format_factor_summary({"technical.rsi.rsi_14": 39.5})
        assert "中性" in s_mid, f"RSI 39.5 应解读中性, got {s_mid}"
        s_hi = format_factor_summary({"technical.rsi.rsi_14": 85.0})
        assert "超买" in s_hi, f"RSI 85 应解读超买, got {s_hi}"
        s_lo = format_factor_summary({"technical.rsi.rsi_14": 15.0})
        assert "超卖" in s_lo, f"RSI 15 应解读超卖, got {s_lo}"

    def test_kdj_negative_oversold(self):
        """F11: KDJ D 负值 → 超卖区解读。"""
        s = format_factor_summary({"technical.kdj.d_value": -3.46})
        assert "超卖" in s, f"KDJ D -3.46 应解读超卖, got {s}"

    def test_unknown_key_fallback(self):
        """F11: 未知键回退为原样（不崩溃、不丢失信息）。"""
        s = format_factor_summary({"future.unknown_factor": 0.5})
        assert "future.unknown_factor" in s, f"未知键应原样保留, got {s}"
        assert "0.5" in s

    def test_empty_input(self):
        """F11: 空输入不崩溃。"""
        s = format_factor_summary({})
        assert s == "" or "因子" in s
