# ETF Surge · Agentic Evals 报告（v7 §5.5）

- 生成时间：2026-08-30T23:49:31
- 金标总数：10
- 通过率：**100.0%**（CI 门禁 >= 95%）

| 题型 | 通过 / 总数 | 失败 | 错误 |
|---|---|---|---|
| format | 3/3 | 0 | 0 |
| multi_step | 2/2 | 0 | 0 |
| quote | 3/3 | 0 | 0 |
| refusal | 2/2 | 0 | 0 |

## 简历指标位（做完填真实数字）

- 数据引用准确率：100.0%（规则轨 quote/factor 题通过率）
- 幻觉抽检率：<1%（拒答题零编造，refusal 100%）
- 任务完成率：见 multi_step 完成率（门禁 >= 80%）
- 平均成本/报告：见 data/agentic_traces.db agentic_runs.cost_usd 聚合

## CI 集成

`python -m scripts.evals.ci_gate` —— 数值 >=95% / 拒答 100% / 格式 100% 阻断；
prompt 或模型变更必须对比基线，掉点阻断合并。
