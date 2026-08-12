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
        """F11: 因子键映射中文名（新闻热度/RSI(14)/KDJ.D）。

        round18 P0-3: KDJ 归一化负值需 tech_ind 原始值才展示（对齐 indicators 口径）——
        无 tech_ind 时 KDJ 键排除，其余键正常映射。
        """
        s = format_factor_summary({
            "sentiment.news_heat": 100.0,
            "technical.rsi.rsi_14": 39.53,
            "technical.kdj.d_value": -3.46,
        })
        assert "新闻热度" in s, f"应含中文名'新闻热度', got {s}"
        assert "RSI(14)" in s or "RSI" in s, f"应含 RSI 名, got {s}"
        assert "KDJ" not in s, f"无 tech_ind 时 KDJ 归一化键应排除, got {s}"
        # 原键名不应裸露出现
        assert "sentiment.news_heat" not in s, f"不应裸拼因子键, got {s}"
        assert "technical.rsi.rsi_14" not in s

    def test_key_mapping_kdj_with_tech_ind(self):
        """round18 P0-3: 传 tech_ind 时 KDJ 以原始值映射中文名。"""
        s = format_factor_summary({
            "sentiment.news_heat": 100.0,
            "technical.kdj.d_value": -3.46,
        }, tech_ind={"kdj": {"d": 84.77}})
        assert "KDJ.D 84.77" in s, f"应含原始 KDJ.D 84.77, got {s}"

    def test_rsi_value_range_interpretation(self):
        """F11: RSI 值域解读——39.5 中性、85 超买、15 超卖。"""
        s_mid = format_factor_summary({"technical.rsi.rsi_14": 39.5})
        assert "中性" in s_mid, f"RSI 39.5 应解读中性, got {s_mid}"
        s_hi = format_factor_summary({"technical.rsi.rsi_14": 85.0})
        assert "超买" in s_hi, f"RSI 85 应解读超买, got {s_hi}"
        s_lo = format_factor_summary({"technical.rsi.rsi_14": 15.0})
        assert "超卖" in s_lo, f"RSI 15 应解读超卖, got {s_lo}"

    def test_kdj_negative_oversold(self):
        """F11: KDJ D 负值 → 超卖区解读。

        round18 P0-3 更新: KDJ 归一化负值不再冒充原始值——无 tech_ind（原始指标）
        时排除 KDJ 键（负向: 负数出现在 factor_summary → FAIL）。
        """
        s = format_factor_summary({"technical.kdj.d_value": -3.46})
        assert "KDJ" not in s, f"归一化负值应被排除, got {s}"

    def test_kdj_aligned_with_tech_indicators(self):
        """round18 P0-3: 传 tech_ind 时 KDJ 显示指标源原始值（0-100，对齐
        /market/indicators）；负向: 仍显示归一化负值 → FAIL。"""
        tech_ind = {"kdj": {"k": 84.77, "d": 14.74, "j": 70.0}}
        s = format_factor_summary(
            {"technical.kdj.k_value": -1.9, "technical.kdj.d_value": -3.46},
            tech_ind=tech_ind,
        )
        assert "KDJ.K 84.77" in s, f"应显示原始 KDJ.K 84.77, got {s}"
        assert "KDJ.D 14.74" in s, f"应显示原始 KDJ.D 14.74, got {s}"
        assert "-3.46" not in s and "-1.90" not in s, f"归一化负值不应出现, got {s}"

    def test_kdj_original_oversold_hint(self):
        """round18 P0-3: 原始 KDJ <20 → 超卖区解读（0-100 口径）。"""
        tech_ind = {"kdj": {"d": 14.74}}
        s = format_factor_summary({"technical.kdj.d_value": -3.46}, tech_ind=tech_ind)
        assert "KDJ.D 14.74" in s
        assert "超卖" in s, f"KDJ 14.74 应判超卖, got {s}"

    def test_unknown_key_fallback(self):
        """F11: 未知键回退为原样（不崩溃、不丢失信息）。"""
        s = format_factor_summary({"future.unknown_factor": 0.5})
        assert "future.unknown_factor" in s, f"未知键应原样保留, got {s}"
        assert "0.5" in s

    def test_empty_input(self):
        """F11: 空输入不崩溃。"""
        s = format_factor_summary({})
        assert s == "" or "因子" in s
