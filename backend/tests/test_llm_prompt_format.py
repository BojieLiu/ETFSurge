"""
N02 (round3-diagnosis-and-optimization-plan.md N02): 设计报告指数涨跌幅放大 100 倍 bug。

- _fmt_pct 显式单位参数（as_percent）：指数 change_pct=0.72（百分数值）→ "0.7%"
  而不是 ×100 后的 "72.0%"（旧 abs>1 启发式误判）。
- 小数比例字段（expected_return=0.08）仍按 ×100 → "8.0%"。
- prompt 含"涨跌幅已是百分数值，禁止 ×100 换算"防御指令。

无网络，纯函数测试。
"""

import inspect

from app.analysis.llm import _build_design_report_prompt, generate_design_report


class TestFmtPct:
    def test_fmt_pct_percent_value_direct(self):
        """指数 change_pct=0.72（百分数值）→ '0.7%'，不再放大 100 倍。"""
        # 通过构建 prompt 验证：注入 index_realtime 涨 0.72% 的指数
        prompt = _build_design_report_prompt(
            strategies=[],
            market_sentiment={},
            market_context={
                "index_realtime": [
                    {"symbol": "000001", "name": "上证指数", "price": 3200.0, "change_pct": 0.72}
                ],
            },
            benchmark_stocks=[],
            plan_tables=None,
        )
        assert "0.7%" in prompt, f"0.72（百分数值）应显示 0.7%，实际 prompt: {prompt}"
        assert "72.0%" not in prompt, "0.72 不得被 ×100 显示为 72.0%（N02 bug）"

    def test_fmt_pct_negative_percent_value(self):
        """指数 change_pct=-5.4（百分数值）→ '-5.4%'。"""
        prompt = _build_design_report_prompt(
            strategies=[],
            market_sentiment={},
            market_context={
                "index_realtime": [
                    {"symbol": "000001", "name": "上证指数", "price": 3000.0, "change_pct": -5.4}
                ],
            },
            benchmark_stocks=[],
            plan_tables=None,
        )
        assert "-5.4%" in prompt, prompt

    def test_fmt_pct_ratio_still_multiplies(self):
        """expected_return=0.08（小数比例）→ 仍 ×100 显示 8.0%。"""
        prompt = _build_design_report_prompt(
            strategies=[
                {
                    "id": "balanced", "label": "平衡型", "portfolio_name": "均衡配置组合",
                    "positioning": "攻守兼备", "expected_return": 0.08,
                    "max_drawdown": -0.18, "sharpe_ratio": 1.0, "allocations": [],
                }
            ],
            market_sentiment={},
            market_context={},
            benchmark_stocks=[],
            plan_tables=None,
        )
        assert "8.0%" in prompt, f"expected_return=0.08 应显示 8.0%，实际: {prompt}"

    def test_prompt_contains_no_convert_instruction(self):
        """N02 规格 4: prompt 包含"禁止 ×100 换算"防御指令。"""
        prompt = _build_design_report_prompt(
            strategies=[],
            market_sentiment={},
            market_context={"index_realtime": []},
            benchmark_stocks=[],
            plan_tables="## 一、三种方案详解\n\n表格",
        )
        assert "百分数值" in prompt and "100" in prompt, \
            "prompt 必须包含涨跌幅已是百分数、禁止换算的指令"


class TestGenerateDesignReportSignature:
    def test_generate_design_report_importable(self):
        """generate_design_report 可导入且签名含 benchmark_stocks（回归保护）。"""
        sig = inspect.signature(generate_design_report)
        assert "benchmark_stocks" in sig.parameters
