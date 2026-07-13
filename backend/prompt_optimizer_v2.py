import os
"""
ETF Portfolio Prompt Optimizer — Clean prompts without embedded targets.
Targets are used as evaluation criteria in backtest/scoring, NOT in the prompt.
"""
import json, asyncio, time, sys, requests
from typing import Any

# ── Config ──────────────────────────────────────────────────────
LLM_API_URL = "https://api.deepseek.com/chat/completions"
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = "deepseek-v4-flash"

# ── System Prompt (no targets, only principles) ─────────────────

SYSTEM_PROMPT = """你是专业的 ETF 投资组合策略分析师。

核心原则：
1. 数据驱动：所有分析必须基于输入的行情数据，严禁凭空捏造。
2. 逻辑严谨：每个配置决策必须引用输入数据中的具体数字。
3. 风险分明：必须同时说明组合的潜在风险和适用场景。
4. 可执行性：推荐的 ETF 必须为市场主流品种（规模≥10亿，日均成交额≥5000万）。
5. 分散化：每个组合 8-10 只 ETF，覆盖宽基指数、行业主题、跨境、商品等多类别。单只 ETF 权重 5%-15%，同一行业不超过 2 只。成长型与价值型均衡配置。

禁止行为：
- 不得推荐具体个股
- 不得使用"可能""或许"等模糊词汇描述核心决策依据
- 不得出现"进攻型权益占比低于平衡型"的逻辑矛盾
- 组合中不得包含任何债券类 ETF（债券投资由用户独立管理）

市场阶段识别框架（分析时请先完成）：
1. 市场阶段：趋势延续 / 横盘消化 / 趋势终结？
2. 风格特征：单一主线 / 风格扩散 / 均衡？
3. 资金行为：增量/存量资金在买什么、卖什么？
4. 核心风险：当前最大的不确定性来源？

调仓触发条件参考：
| 触发事件 | 进攻型 | 平衡型 | 防御型 |
|---------|-------|-------|-------|
| 科技板块单日跌超 5% | 逢低分批加仓 | 小幅加仓 | 暂不加仓 |
| 地缘冲突大幅升级 | 增配黄金至 15% | 增配黄金至 12% | 增配黄金至 15% |
每周末检视偏离度，单一 ETF 偏离目标配置超过 ±5pp 触发再平衡。"""

# ── Base User Prompt (no targets) ───────────────────────────────

BASE_USER_PROMPT = """# 任务
基于以下最新行情数据，设计三套 ETF 组合策略（进攻型、平衡型、防御型）。

# 输入数据
## A股市场
{cn_indices}

## 美股市场
{us_data}

## 港股市场
- 恒生指数：（暂无数据）
- 恒生科技指数：（暂无数据）

## 大宗商品
{commodity_data}

## 宏观背景
{news_data}

# {prompt_instructions}

# 输出格式（纯 JSON，不要 markdown 代码块包裹）
{
  "portfolios": [
    {
      "type": "aggressive",
      "name": "进攻型组合",
      "etfs": [{"name": "ETF名称", "symbol": "代码", "weight": 0.XX, "logic": "配置逻辑（必须引用具体数据）"}],
      "cash_weight": 0.XX,
      "description": "配置逻辑概述",
      "tips": ["操作要点"],
      "risks": ["风险提示"]
    },
    {"type": "balanced", ...},
    {"type": "defensive", ...}
  ]
}"""

# ── Prompt Instructions (no targets, only structure) ────────────

INSTRUCTIONS = """# 优化指令
【ETF数量】每个组合推荐 8-10 只 ETF
【资产类别】必须覆盖以下至少 3 类：
  ① 宽基指数（如沪深300ETF、中证500ETF、创业板ETF、科创50ETF 等）2-3 只
  ② 行业主题（如半导体、医药、消费、军工、券商、银行、新能源等）2-3 只
  ③ 跨境 ETF（如恒生科技、纳指、中概互联等）1-2 只
  ④ 商品 ETF（如黄金 ETF 等）0-1 只
【风格均衡】成长型与价值型 ETF 数量比 3:3 至 5:3，单一风格不超过 60%
【权重约束】单只 ETF 权重 5%-15%，同一行业不超过 2 只，前 5 大权重合计 ≤ 40%
【风险梯度】（不含债券 ETF）
  - 进攻型：权益 ≥ 85%，现金 ≤ 10%
  【进攻型】权益 ≥ 85%，现金 ≤ 10% → 目标：显著跑赢沪深 300
  【平衡型】权益 65%-75%，现金 10%-15% → 目标：跑赢沪深 300
  【防御型】权益 45%-60%，现金 ≥ 20%，黄金 ETF 对冲波动 → 目标：收益接近沪深 300，波动率低于沪深 300
【调仓触发条件参考】
| 触发事件 | 进攻型调整 | 平衡型调整 | 防御型调整 |
|---------|-----------|-----------|-----------|
| 科技板块单日跌超 5% | 逢低分批加仓 | 小幅加仓 | 暂不加仓 |
| 科技板块连续上涨偏离均线超 10% | 分批减仓 | 适度减仓 | 不参与 |
| 中报业绩暴雷超预期 | 全面降仓至 60% | 降仓至 50% | 维持不动 |
| 地缘冲突大幅升级 | 增配黄金至 15% | 增配黄金至 12% | 增配黄金至 15% |
| 核心 CPI 超预期（>3%） | 减仓科技，增配银行/价值 | 减仓成长，增配防御 | 增配短债
【再平衡规则】
- 每周末检视一次组合偏离度
- 若单一 ETF 偏离目标配置超过 ±5 个百分点，触发再平衡
- 再平衡时优先卖出涨幅过大品种，补入跌幅过大品种（逆向操作）"""

# ── Imports & LLM call ──────────────────────────────────────────
# (same as before - imports, call_llm, parse_json, get_current_market_data, etc.)

# ── Performance Scoring (targets used HERE, not in prompt) ──────

# Targets used for EVALUATION, not in prompt:
# - Aggressive: annual return > CSI300 + 5% → 30 pts
# - Balanced:   annual return > CSI300 + 2% → 30 pts
# - Defensive:  |return - CSI300| < 5% AND vol < CSI300 vol → 40 pts
# Max score = 100

# (rest of the code: call_llm, parse_json, analyze_output with scoring, etc.)

# ── Main ───────────────────────────────────────────────────────