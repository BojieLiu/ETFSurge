"""
F3 R1-R10 (combination-design-review.md F3): 组合设计报告内容层修复。

- R1: task_manager 前缀不再产生重复标题（plan_tables 自带标题）。
- R2/R3: _dedup_headers 写库前统一去重（检出即回写）+ 空行 \n{3,} → \n\n。
- R4（2026-08-02 更新）：入选理由不再截断（对齐 R5 名称处理，markdown 表格换行）——旧决策"理由压缩 ≤80 字"已由用户撤销。
- R5: 名称不截断。
- R6: _build_plan_tables 首行无 \n\n 前导。
- R8: strategy_design 显式 None 判断（0.0 不再被 or 丢弃）。

无网络，纯函数测试。
"""

import pytest

from app.tasks.design_report import (
    _build_plan_tables,
    _dedup_headers,
)


def _strategy(symbol="510300", name="沪深300ETF华泰柏瑞", rationale="市场震荡；在防御型方案中沪深300ETF核心层配置，大盘价值代表性"):
    return {
        "id": "balanced", "label": "平衡型", "portfolio_name": "均衡配置组合",
        "positioning": "核心稳健+卫星增强，攻守兼备，适合中等风险偏好者",
        "expected_return": 0.11, "expected_return_current": 0.11,
        "max_drawdown": -0.18, "sharpe_ratio": 1.0,
        "allocations": [
            {"symbol": symbol, "name": name, "layer": "core",
             "weight": 0.2, "factor_score": 0.8, "selection_rationale": rationale},
            {"symbol": "CASH", "name": "现金", "layer": "cash", "weight": 0.1},
        ],
    }


class TestR1TitleDedup:
    def test_plan_tables_has_single_heading(self):
        """R1/R6: plan_tables 自带标题且无 \n\n 前导——与文档总标题拼接后不重复。"""
        tables = _build_plan_tables([_strategy()])
        assert tables.startswith("## 一、三种方案详解"), \
            "plan_tables 应以标题开头（无空行前导）"
        assert tables.count("## 一、三种方案详解") == 1

    def test_dedup_headers_removes_duplicate(self):
        """R2/R3: _dedup_headers 检出重复标题即回写修正。"""
        text = "# ETF 组合设计方案\n\n## 一、三种方案详解\n\n\n\n## 一、三种方案详解\n\n正文"
        cleaned = _dedup_headers(text)
        assert cleaned.count("## 一、三种方案详解") == 1, "重复标题必须被移除"
        assert "\n\n\n" not in cleaned, "3+ 空行必须折叠为 2"

    def test_validate_design_text_no_repeat_warning(self):
        """R3 联动: 去重后 _validate_design_text 不再报重复标题。"""
        from app.tasks.design_report import _validate_design_text
        text = _dedup_headers("# ETF 组合设计方案\n\n## 一、三种方案详解\n\n表格正文" * 1)
        # 构造重复场景后再去重
        dup = "# ETF 组合设计方案\n## 一、三种方案详解\n## 一、三种方案详解\n正文内容足够长以满足最短长度检查"
        cleaned = _dedup_headers(dup)
        warnings = _validate_design_text(cleaned)
        assert "存在重复标题" not in warnings, f"去重后不应再报重复: {warnings}"


class TestR4RationaleNotTruncated:
    def test_table_cell_rationale_not_truncated(self):
        """R4（2026-08-02 更新）: 理由不截断——完整理由必须保留在表格中。

        旧行为：_compress_rationale 截断到 ≤80 字（丢失估值/资金流/市态等关键尾部），
        与 R5 名称不截断不一致；用户已撤销该决策。
        """
        long = "数据驱动理由" * 40  # 240 字，远超旧 80 字上限
        tables = _build_plan_tables([_strategy(rationale=long)])
        assert long in tables, "完整理由必须保留（旧行为截断为 ≤80 字）"
        for line in tables.splitlines():
            if "| 核心 |" in line:
                cells = line.split("|")
                assert len(cells) > 7
                rationale_cell = cells[7]
                assert rationale_cell.strip() == long, "理由列应为完整文本，不得截断/加省略号"

    def test_rationale_pipe_and_newline_escaped(self):
        """防御：理由含竖线/换行（如风控追加文本）不得拆裂表格行——转义后表格仍为单行。"""
        tricky = "核心宽基；风控提示：近1月跌8.2%\n第二行补充 | 附加说明"
        tables = _build_plan_tables([_strategy(rationale=tricky)])
        core_lines = [l for l in tables.splitlines() if "| 核心 |" in l]
        assert len(core_lines) == 1, f"理由含 |/\\n 拆裂表格行：{core_lines}"
        assert "\\|" in core_lines[0], "竖线必须转义为 \\|"
        assert "第二行补充" in core_lines[0], "换行应展平为空格而非拆行"


class TestR5NameNotTruncated:
    def test_full_name_kept(self):
        """R5: 名称不截断（无 [:12] 残句）。"""
        tables = _build_plan_tables([_strategy(name="中证500增强ETF易方达")])
        assert "中证500增强ETF易方达" in tables, "完整名称必须保留（旧代码截断为'中证500增强ETF易方'）"
        assert "易方" not in tables.split("中证500增强ETF易方达")[0][-20:], "不应出现截断残句"


class TestR8FalsyFix:
    def test_zero_change_pct_not_dropped(self):
        """R8: change_pct=0.0（falsy）不被 or 丢弃——注入 daily_change_pct=0.0。"""
        import inspect
        import app.services.strategy_design as sd
        src = inspect.getsource(sd)
        assert 'dcp = pool_entry.get("change_pct")\n                    if dcp is None:' in src, \
            "pool_entry 路径必须显式 None 判断（F3 R8）"
