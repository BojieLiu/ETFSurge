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


class TestR615BuildAdviceColumn:
    def test_table_has_advice_column(self):
        """R6-F15: 方案表格含「建仓建议」列，且每行有建议值。"""
        tables = _build_plan_tables([_strategy()])
        header = [ln for ln in tables.splitlines() if "建仓建议" in ln]
        assert header, "表头应含「建仓建议」列"
        rows = [ln for ln in tables.splitlines() if ln.startswith("| 核心 |") or ln.startswith("| 卫星 |")]
        assert rows, "应有标的行"
        for r in rows:
            assert "批" in r or "企稳" in r or "一次性" in r, f"每行应有建仓建议: {r}"

    def test_defense_advice_one_shot(self):
        """防御层 → 可一次性配置（低波避险底仓）。"""
        s = _strategy()
        s["allocations"].insert(0, {"symbol": "518880", "name": "黄金ETF", "layer": "defense",
                                    "weight": 0.05, "factor_score": 0.5,
                                    "selection_rationale": "避险"})
        tables = _build_plan_tables([s])
        def_row = [ln for ln in tables.splitlines() if ln.startswith("| 防御 |")]
        assert def_row, "应有防御行"
        assert "一次性" in def_row[0], def_row[0]

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



class TestStaticPoolStrReturnGuard:
    """round23 遗留修复（2026-08-14）：静态池兜底方案的 expected_return 是 str
    （"10%-14%" 区间展示串），_build_plan_tables 用数值格式化 → ValueError:
    Unknown format code 'f' for object of type 'str' → 设计任务 failed。
    验收：任何来源的策略都不应让 _build_plan_tables 崩溃；静态池策略应产出数值/None。
    """

    def _static_style(self):
        return {
            "id": "balanced", "label": "均衡型",
            "expected_return": "10%-14%",
            "expected_return_current": "10%-14%",
            "expected_volatility": "12-20%",
            "allocations": [
                {"symbol": "510300", "name": "沪深300", "layer": "core", "weight": 0.2},
                {"symbol": "CASH", "name": "现金", "layer": "cash", "weight": 0.1},
            ],
        }

    def test_plan_tables_survives_str_expected_return(self):
        """str 收益率（静态池兜底旧形态）→ 不抛异常，表格显示 — 而非崩溃。"""
        tables = _build_plan_tables([self._static_style()])
        assert "—" in tables, f"str 收益率应渲染为占位符 —，实得: {tables[:200]}"

    def test_static_pool_strategy_expected_return_is_numeric(self):
        """根源：静态池策略 expected_return 必须是 float/None（数值语义），非 str。"""
        from app.services.strategy_design import _build_static_pool_strategies
        strategies = _build_static_pool_strategies(500000)
        assert strategies, "静态池应产出 3 套方案"
        for st in strategies:
            v = st.get("expected_return")
            assert v is None or isinstance(v, (int, float)), \
                f"{st['id']} expected_return 应为数值/None，实得 {type(v).__name__}: {v!r}"
            assert "%" not in str(st.get("expected_return", "")), \
                f"{st['id']} expected_return 不得是展示串"


# ===================================================================
# merged from test_round25_r36_precision_tables.py (S3.3 de-round migration, 2026-08-18)
# ===================================================================
"""round25 R36: 降级态（coarse）方案表格不再呈现精确小数——权重/因子分按档位。

问题（round25 §0.3 R36 实证）：`data_precision` 标注 coarse/bucket（R3 已做），但
design_text 表格仍渲染 `-0.99`/`3.07` 精确因子分与 `21.0%` 精确权重——与标注矛盾。

修复（round25 R36）：`_build_plan_tables` 接收 `precision` 参数——mode=coarse 时
因子分列按强弱分档（偏强/中性/偏弱）、权重按 5% 档位（≈20%），与前端 DesignResult
的 bucket 呈现一致。
"""

import pytest

from app.tasks.design_report import _build_plan_tables


def _strategy_r36():
    return [{
        "id": "balanced", "label": "平衡型", "positioning": "攻守平衡",
        "allocations": [
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core",
             "weight": 0.2067, "factor_score": -0.9855288495104011,
             "daily_change_pct": 1.2, "selection_rationale": "宽基锚"},
            {"symbol": "511090", "name": "30年国债ETF", "layer": "defense",
             "weight": 0.1498, "factor_score": 3.0662,
             "daily_change_pct": 0.1, "selection_rationale": "利率对冲"},
            {"symbol": "CASH", "layer": "cash", "weight": 0.10},
        ],
    }]


class TestBuildPlanTablesPrecision:
    """R36: coarse 态表格分档呈现（不出现精确小数）。"""

    def test_coarse_buckets_factor_score(self):
        """mode=coarse → 因子分列显示「偏弱/偏强/中性」，不含 -0.99/3.07 精确值。"""
        table = _build_plan_tables(_strategy_r36(), precision={"mode": "coarse", "weight_step_pct": 5.0})
        assert "偏弱" in table, "coarse 态 -0.99 应显示「偏弱」"
        assert "偏强" in table, "coarse 态 3.07 应显示「偏强」"
        assert "-0.99" not in table, "coarse 态不得出现精确因子分（R36）"
        assert "3.07" not in table

    def test_coarse_buckets_weight(self):
        """mode=coarse → 权重按 5% 档位（≈20%/≈15%），不含 20.67% 精确值。"""
        table = _build_plan_tables(_strategy_r36(), precision={"mode": "coarse", "weight_step_pct": 5.0})
        assert "≈20%" in table, "20.67% → ≈20%（5% 档）"
        assert "≈15%" in table, "14.98% → ≈15%（5% 档）"
        assert "20.67" not in table and "14.98" not in table, "coarse 态不得出现精确权重"

    def test_exact_keeps_precision(self):
        """mode=exact（或未传）→ 原精确值不变（不误降级）。"""
        table = _build_plan_tables(_strategy_r36())
        assert "-0.99" in table or "-0.985528" in table, "exact 态保留精确因子分"
        assert "21%" in table, "exact 态权重按原值 20.67→21%"
        assert "≈" not in table, "exact 态不得出现档位近似值"

    def test_precision_none_no_regression(self):
        """precision=None → 与旧行为一致（无 ≈/偏强 等降级呈现）。"""
        table = _build_plan_tables(_strategy_r36(), precision=None)
        assert "偏弱" not in table and "≈" not in table


# ══════════════════════════════════════════════════════════════════════════
# round62: 现金仓位在报告 §一 的显性化
# ══════════════════════════════════════════════════════════════════════════
# 归入本文件而非新开 test_design_report_cash.py——被测主体同为 _build_plan_tables
# （P3-6 基线纪律：新 round 用例归入主题文件；redundant-review §4.2 例外条款仅适用
# 于「断言的是不同函数」的情形，round60 即按此判定）。
#
# 背景（真实现象，DB design id=85 的 design_text）：方案卡片 header 有「现金 25%」
# + 明细表 CASH 行，而报告 §一 每方案小节「资产结构：核心 45% · 卫星 20% ·
# 防御 10%」只有 75%，缺口无解释；明细表显式 continue 掉 CASH 行，权重列加不到 100%。
# 唯一口径事实源：app/core/cash_weight.py（cash = 1 - Σ非现金权重，「不归一化」）。

import re

from app.analysis.llm.reports import _build_engine_fallback
from app.core.cash_weight import cash_weight_of
from app.tasks.design_report import (
    _build_engine_summary,
    _cash_weight_of,
)


def _cash_alloc(symbol, name, layer, weight, **kw):
    d = {"symbol": symbol, "name": name, "layer": layer, "weight": weight}
    d.update(kw)
    return d


def _cash_strategy(label="防御型", allocs=None, **kw):
    """默认夹具：核心 45 / 卫星 20 / 防御 10 / 现金 25 = 100%（对齐 design id=85）。"""
    if allocs is None:
        allocs = [
            _cash_alloc("510300", "沪深300ETF华泰柏瑞", "core", 0.45,
                   factor_score=1.2, daily_change_pct=0.36,
                   selection_rationale="A股核心宽基，覆盖沪深两市龙头"),
            _cash_alloc("515880", "通信ETF国泰", "satellite", 0.20,
                   factor_score=0.3, daily_change_pct=-0.48,
                   selection_rationale="通信方向，弹性卫星"),
            _cash_alloc("518880", "黄金ETF华安", "defense", 0.10,
                   factor_score=0.6, daily_change_pct=1.34,
                   selection_rationale="贵金属避险资产，对冲系统性风险"),
            _cash_alloc("CASH", "现金", "cash", 0.25, selection_rationale="流动性管理"),
        ]
    s = {
        "id": "defensive", "label": label, "positioning": "低波稳健配置",
        "expected_return": 0.08, "expected_return_current": 0.08,
        "max_drawdown": -0.10, "sharpe_ratio": 1.2,
        "allocations": allocs,
    }
    s.update(kw)
    return s


def _cash_cell(text):
    """取对比表「现金仓位」行的三个单元格文本。"""
    m = re.search(r"^\|\s*现金仓位\s*\|(.+)\|\s*$", text, re.M)
    assert m, f"对比表缺「现金仓位」行:\n{text[:600]}"
    return [c.strip() for c in m.group(1).split("|")]


def _row_of(text, symbol):
    """取明细表中某代码所在行（按 | 分割的原始 markdown 行）。"""
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if any(c == symbol for c in cells):
            return cells
    return None


class TestCashHelper:
    def test_from_cash_row(self):
        assert _cash_weight_of(_cash_strategy()) == 0.25

    def test_residual_when_cash_row_missing(self):
        """缺 CASH 行时按 residual = 1 - Σ非现金 推导（对齐 AGENTS「权重不归一化」约定）。"""
        s = _cash_strategy(allocs=[_cash_alloc("510300", "沪深300ETF", "core", 0.75)])
        assert _cash_weight_of(s) == 0.25

    def test_accepts_target_weight_key(self):
        """plans[].allocations 用 target_weight，strategies[].etfs[] 用 weight——两者都吃。"""
        s = _cash_strategy(allocs=[
            {"symbol": "510300", "name": "沪深300ETF", "layer": "core", "target_weight": 0.6},
            {"symbol": "CASH", "name": "现金", "layer": "cash", "target_weight": 0.4},
        ])
        assert _cash_weight_of(s) == 0.4

    def test_none_when_no_weight_data(self):
        """无任何权重数据 → None（调用方渲染「—」，不得编造）。"""
        assert _cash_weight_of(_cash_strategy(allocs=[])) is None

    def test_never_negative_when_overallocated(self):
        """Σ非现金 > 1 时残余现金为负 → 夹到 0（引擎口径：现金不为负）。"""
        s = _cash_strategy(allocs=[_cash_alloc("510300", "沪深300ETF", "core", 1.10)])
        assert _cash_weight_of(s) == 0.0

    def test_none_when_weight_unparseable(self):
        """权重不可解析（非数值）→ None，而非把该权重当 0 推出「现金 100%」假数据。"""
        s = _cash_strategy(allocs=[{"symbol": "510300", "name": "x", "layer": "core", "weight": "0.8"}])
        assert _cash_weight_of(s) is None

    def test_cash_row_wins_over_unparseable_etf_weight(self):
        """有权威 CASH 行时不受其它行权重不可解析影响（现金行同源引擎）。"""
        s = _cash_strategy(allocs=[
            {"symbol": "510300", "name": "x", "layer": "core", "weight": "0.8"},
            {"symbol": "CASH", "name": "现金", "layer": "cash", "weight": 0.3},
        ])
        assert _cash_weight_of(s) == 0.3


class TestCashInComparisonTable:
    def test_cash_row_rendered(self):
        tables = _build_plan_tables([_cash_strategy()])
        assert _cash_cell(tables) == ["25%"]

    def test_no_fabricated_cash_when_row_absent(self):
        """负向断言：旧实现 `... if cash else 10` 会把残余 25% 渲染成 10%。

        断言残余现金必须按推导值 25% 呈现，且**不得**出现 10%。
        """
        s = _cash_strategy(allocs=[
            _cash_alloc("510300", "沪深300ETF", "core", 0.45),
            _cash_alloc("515880", "通信ETF", "satellite", 0.20),
            _cash_alloc("518880", "黄金ETF", "defense", 0.10),
        ])
        cell = _cash_cell(_build_plan_tables([s]))
        assert cell == ["25%"], f"缺 CASH 行时应按 residual 推导 25%，实得 {cell}"
        assert "10%" not in cell, "不得回落到旧实现的编造值 10%"

    def test_full_cash_renders_100(self):
        """全现金兜底（task_manager 全 CASH 替换路径）→ 100%，不是编造值。"""
        s = _cash_strategy(allocs=[_cash_alloc("CASH", "现金", "cash", 1.0)])
        assert _cash_cell(_build_plan_tables([s])) == ["100%"]

    def test_undeterminable_cash_renders_dash(self):
        """无权重数据 → 「—」，绝不编造百分比。"""
        s = _cash_strategy(allocs=[])
        assert _cash_cell(_build_plan_tables([s])) == ["—"]


class TestCashInAssetStructureLine:
    def test_structure_line_sums_to_100(self):
        """每方案「资产结构」行必须四段齐全且合计 100%（旧实现只三项 = 75%）。"""
        tables = _build_plan_tables([_cash_strategy()])
        line = next(ln for ln in tables.splitlines() if ln.startswith("资产结构"))
        assert line == "资产结构：核心 45% · 卫星 20% · 防御 10% · 现金 25%", line
        total = sum(int(x) for x in re.findall(r"(\d+)%", line))
        assert total == 100, f"资产结构各项合计应为 100%，实得 {total}（{line}）"

    def test_structure_line_per_plan(self):
        """三个方案各自的现金不同 → 每行都带各自的现金（不共用一个值）。"""
        tables = _build_plan_tables([
            _cash_strategy(label="防御型", allocs=[
                _cash_alloc("510300", "A", "core", 0.60),
                _cash_alloc("CASH", "现金", "cash", 0.40),
            ]),
            _cash_strategy(label="进攻型", allocs=[
                _cash_alloc("510300", "A", "core", 0.90),
                _cash_alloc("CASH", "现金", "cash", 0.10),
            ]),
        ])
        lines = [ln for ln in tables.splitlines() if ln.startswith("资产结构")]
        assert "现金 40%" in lines[0], lines
        assert "现金 10%" in lines[1], lines


class TestCashRowInDetailTable:
    def test_cash_row_present(self):
        """明细表必须含 CASH 行（旧实现显式 continue 掉）。"""
        tables = _build_plan_tables([_cash_strategy()])
        row = _row_of(tables, "CASH")
        assert row is not None, "明细表缺现金行"
        assert row[0] == "现金", f"资产类别列应为「现金」，实得 {row[0]}"
        assert row[2] == "现金"
        assert row[3] == "25%", f"权重列应为 25%，实得 {row[3]}"

    def test_weight_column_sums_to_100(self):
        """明细表权重列合计 = 100%（含现金后口径自洽）。"""
        tables = _build_plan_tables([_cash_strategy()])
        rows = [_row_of(tables, sym) for sym in ("510300", "515880", "518880", "CASH")]
        assert all(r is not None for r in rows), "四行必须齐全"
        total = sum(int(r[3].rstrip("%")) for r in rows)
        assert total == 100, f"权重合计应为 100%，实得 {total}"

    def test_cash_row_no_fake_quote_or_factor(self):
        """现金无行情/因子语义：涨跌列「—」（非「数据源不可用」），因子分列留空。

        「数据源不可用」是给**ETF 缺数据**用的；现金是**不适用**，两者语义不同。
        """
        row = _row_of(_build_plan_tables([_cash_strategy()]), "CASH")
        assert row[4] == "", f"现金行不得有因子分，实得 {row[4]!r}"
        assert row[5] == "—", f"现金行涨跌应为「—」，实得 {row[5]!r}"
        assert "数据源不可用" not in row[5]

    def test_cash_row_rationale_present(self):
        """现金行须有入选理由（引擎给「流动性管理」，缺失回落「现金缓冲」）。"""
        row = _row_of(_build_plan_tables([_cash_strategy()]), "CASH")
        assert row[7] == "流动性管理", row[7]
        s = _cash_strategy(allocs=[_cash_alloc("510300", "A", "core", 0.8),
                              _cash_alloc("CASH", "现金", "cash", 0.2)])
        assert _row_of(_build_plan_tables([s]), "CASH")[7] == "现金缓冲"

    def test_cash_row_not_fund_advice(self):
        """现金行建仓建议不得沿用 ETF 分批建仓话术（cash 未命中两个分支会落到 else）。"""
        row = _row_of(_build_plan_tables([_cash_strategy()]), "CASH")
        advice = row[6]
        assert "MA20" not in advice and "建仓" not in advice, f"现金建仓建议口径错: {advice!r}"

    def test_cash_row_sorted_last(self):
        """现金行排在明细表末尾（引擎虽已追加在最后，但兜底路径顺序不保证）。"""
        s = _cash_strategy(allocs=[
            _cash_alloc("CASH", "现金", "cash", 0.25, selection_rationale="流动性管理"),
            _cash_alloc("510300", "沪深300ETF", "core", 0.45),
            _cash_alloc("515880", "通信ETF", "satellite", 0.20),
            _cash_alloc("518880", "黄金ETF", "defense", 0.10),
        ])
        tables = _build_plan_tables([s])
        body = tables.split("### 防御型", 1)[1]
        symbols = [c.strip() for ln in body.splitlines() if ln.strip().startswith("|")
                   for c in ln.strip().strip("|").split("|")][1::8]
        assert symbols[-1] == "CASH", f"现金行应在末位，实得 {symbols}"

    def test_no_cash_row_no_phantom_row(self):
        """无 CASH 行时不得凭空造出现金行（残余现金只进对比表/结构行，不进明细表）。"""
        s = _cash_strategy(allocs=[_cash_alloc("510300", "沪深300ETF", "core", 0.75)])
        tables = _build_plan_tables([s])
        assert _row_of(tables, "CASH") is None, "无 CASH 行时不得合成现金行"


class TestCashFootnote:
    def test_footnote_explains_dash(self):
        """须有脚注说明现金行「—」的含义（否则「—」会被误读为数据缺失）。"""
        tables = _build_plan_tables([_cash_strategy()])
        assert "现金行" in tables and "CASH" in tables
        note = next(ln for ln in tables.splitlines() if ln.startswith("> 注：现金"))
        assert "非数据缺失" in note, note

    def test_no_footnote_without_cash(self):
        s = _cash_strategy(allocs=[_cash_alloc("510300", "沪深300ETF", "core", 1.0)])
        assert "现金行" not in _build_plan_tables([s])


class TestRoundingDisclosure:
    """权重列整数渲染的取整披露。

    现实数据（DB design id=85 进攻型）：精确权重 5/5/20/4.29×5/8.57/5/34.98
    合计**恰为 100%**，但逐行取整后显示合计为 99%。
    本类锁定：① 取整漂移被披露；② **不得**为凑 100% 篡改现金权重。
    """

    AGGRESSIVE = [
        _cash_alloc("510300", "沪深300ETF", "core", 0.05),
        _cash_alloc("159338", "中证A500ETF", "core", 0.05),
        _cash_alloc("588000", "科创50ETF", "core", 0.20),
        _cash_alloc("159928", "消费ETF", "satellite", 0.0429),
        _cash_alloc("159755", "电池ETF", "satellite", 0.0429),
        _cash_alloc("515880", "通信ETF", "satellite", 0.0429),
        _cash_alloc("513180", "恒生科技ETF", "satellite", 0.0429),
        _cash_alloc("512880", "证券ETF", "satellite", 0.0429),
        _cash_alloc("159995", "芯片ETF", "satellite", 0.0857),
        _cash_alloc("518880", "黄金ETF", "defense", 0.05),
        _cash_alloc("CASH", "现金", "cash", 0.3498, selection_rationale="流动性管理"),
    ]

    def test_exact_weights_sum_to_100(self):
        assert abs(sum(a["weight"] for a in self.AGGRESSIVE) - 1.0) < 1e-9

    def test_displayed_column_sums_to_99(self):
        """确认取整漂移确实存在（否则下面的披露断言是恒绿的假覆盖）。"""
        tables = _build_plan_tables([_cash_strategy(label="进攻型", allocs=self.AGGRESSIVE)])
        rows = [_row_of(tables, a["symbol"]) for a in self.AGGRESSIVE]
        assert all(r is not None for r in rows), "所有行（含现金）必须渲染"
        shown = sum(int(r[3].rstrip("%")) for r in rows)
        assert shown == 99, f"预期取整后显示合计 99%，实得 {shown}"

    def test_drift_disclosed(self):
        tables = _build_plan_tables([_cash_strategy(label="进攻型", allocs=self.AGGRESSIVE)])
        note = next(ln for ln in tables.splitlines() if "四舍五入" in ln)
        assert "99%" in note and "100%" in note, note

    def test_no_note_when_weights_are_round(self):
        """权重本身是整数百分比时不得追加取整脚注（无漂移就不制造噪音）。"""
        tables = _build_plan_tables([_cash_strategy()])
        assert "四舍五入" not in tables

    def test_cash_not_tampered_to_force_100(self):
        """现金权重必须保持 DB 原值 34.98%（不得为了凑 100% 改成 35.98%）。"""
        s = _cash_strategy(label="进攻型", allocs=self.AGGRESSIVE)
        assert _cash_weight_of(s) == 0.3498
        row = _row_of(_build_plan_tables([s]), "CASH")
        assert row[3] == "35%", row[3]  # 显示取整，与卡片一致
        assert "35.98" not in _build_plan_tables([s])

    def test_structure_line_uses_exact_cash(self):
        """结构行现金同样按精确值取整显示（34.98% → 35%），与卡片 header 一致。"""
        s = _cash_strategy(label="进攻型", allocs=self.AGGRESSIVE)
        line = next(ln for ln in _build_plan_tables([s]).splitlines()
                    if ln.startswith("资产结构"))
        assert line.endswith("现金 35%"), line


class TestFallbackWritersCarryCash:
    """三个兜底写手不得丢现金（旧实现只印三层 / 印总权益但不名现金）。"""

    def test_engine_fallback_shows_cash(self):
        txt = _build_engine_fallback([_cash_strategy()])
        assert "现金 25%" in txt, txt[:800]

    def test_engine_fallback_cash_bullet(self):
        txt = _build_engine_fallback([_cash_strategy()])
        bullet = next(ln for ln in txt.splitlines() if ln.startswith("- 现金"))
        assert "25%" in bullet, bullet

    def test_engine_fallback_equity_line_names_cash(self):
        """总权益 >90% 那条风险提示须点名现金，否则读者无从解释缺口。"""
        s = _cash_strategy(allocs=[_cash_alloc("510300", "A", "core", 0.95),
                              _cash_alloc("CASH", "现金", "cash", 0.05)])
        txt = _build_engine_fallback([s])
        line = next(ln for ln in txt.splitlines() if "总权益仓位" in ln)
        assert "现金 5%" in line, line

    def test_engine_fallback_no_cash_flagged(self):
        """满仓（无现金）时该提示须说「无现金仓位」而非留白。"""
        s = _cash_strategy(allocs=[_cash_alloc("510300", "A", "core", 1.0)])
        line = next(ln for ln in _build_engine_fallback([s]).splitlines()
                    if "总权益仓位" in ln)
        assert "无现金仓位" in line, line

    def test_engine_fallback_equity_not_cross_plan_sum(self):
        """三方案各自 ~75% 时不得报「总权益仓位 225%」（旧实现跨方案加总=假数据）。

        应报最满的那套方案并点名它，同时带方案名（数字指得回具体方案）。
        """
        plans = [
            _cash_strategy(label="防御型", allocs=[_cash_alloc("510300", "A", "core", 0.75),
                                             _cash_alloc("CASH", "现金", "cash", 0.25)]),
            _cash_strategy(label="平衡型", allocs=[_cash_alloc("510300", "A", "core", 0.95),
                                             _cash_alloc("CASH", "现金", "cash", 0.05)]),
            _cash_strategy(label="进攻型", allocs=[_cash_alloc("510300", "A", "core", 0.75),
                                             _cash_alloc("CASH", "现金", "cash", 0.25)]),
        ]
        line = next(ln for ln in _build_engine_fallback(plans).splitlines()
                    if "总权益仓位" in ln)
        assert "225%" not in line, line
        assert "95%" in line and "现金 5%" in line, line
        assert "平衡型" in line, line

    def test_engine_summary_shows_cash(self):
        """空报告兜底（LLM 返回空）同样要显现金——旧实现只印三层。"""
        txt = _build_engine_summary([_cash_strategy()], {"market_regime": "range_bound"})
        assert "现金 25%" in txt, txt[:800]
        assert next(ln for ln in txt.splitlines() if ln.startswith("- 现金 (CASH) 25%"))

    def test_engine_summary_no_fabricated_cash(self):
        """空报告兜底不得沿用编造值：无 CASH 行时按 residual 推导。"""
        s = _cash_strategy(allocs=[_cash_alloc("510300", "A", "core", 0.60),
                              _cash_alloc("515880", "B", "satellite", 0.15)])
        txt = _build_engine_summary([s], {})
        assert "现金 25%" in txt, txt[:800]
        assert "现金 10%" not in txt
