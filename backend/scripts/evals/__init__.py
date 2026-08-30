"""Evals 金标评估框架（v7 P2 §5.5，与 pytest 解耦的独立 harness）。

结构：
- harness.py    评估主入口：load goldens -> run agent/tool -> score -> report
- goldens/*.jsonl  金标集（P0 阶段 10 条 demo：每类 >=2）
- scorers/rule_scorer.py  规则轨：数值比对 / schema 校验 / 引用完整性 / 拒答检测
- ci_gate.py    CI 门禁：数值 >=95% / 拒答零幻觉 100% / 格式 100%（阻断）
- report.py     报告生成 + 简历指标位填充

金标格式（jsonl 每行一条）：
{"id": "q001", "type": "quote", "question": "510300 最新价",
 "tool": "get_realtime_quote", "arguments": {"symbols": ["510300"]},
 "expect": {"field_path": "data[0].price", "op": "present"},
 "notes": ""}

类型（5 类）：quote / factor / format / refusal / multi_step
- quote:   已知答案的行情快照题（op: present | approx 数值容差）
- factor:  因子数值题（对照纯函数引擎确定性输出）
- format:  格式合规题（信封字段完整性）
- refusal: 拒答题（无数据时必须明确缺失，不得编造）
- multi_step: 多步推理题（按步骤 plan 执行，验证拆分能力）

运行：cd backend && python -m scripts.evals.harness --goldens scripts/evals/goldens
CI：  cd backend && python -m scripts.evals.ci_gate
"""
