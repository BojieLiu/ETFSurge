/**
 * F16 R57/R59: DeepSeek token 费用计价纯函数。
 * 单位 ¥/1k tokens（按 ¥7.2/USD 换算，2026-07 官方定价）。
 *
 * - calcCost: 单模型计价（未知模型回退 flash 单价）
 * - modelCostFromBuckets: 按 by_model 分桶逐模型计价（flash-free 贡献 ¥0）
 */

// 官方定价 (2026-07):
// deepseek-v4-flash: Input $0.14/1M, Output $0.28/1M
// deepseek-chat: Input $0.27/1M, Output $1.10/1M
// deepseek-reasoner: Input $0.55/1M, Output $2.19/1M
// deepseek-v4-flash-free: OpenCode Zen 免费模型，费用为 ¥0
export const PRICING = {
  'deepseek-v4-flash': { input: 0.001, output: 0.002, cache_hit: 0.00002 },
  'deepseek-v4-flash-free': { input: 0, output: 0, note: 'OpenCode Zen 免费额度内' },
  'deepseek-chat': { input: 0.002, output: 0.008 },
  'deepseek-reasoner': { input: 0.004, output: 0.016 },
}

export function calcCost(prompt, completion, modelName) {
  const p = PRICING[modelName] || PRICING['deepseek-v4-flash']
  return (prompt / 1000) * p.input + (completion / 1000) * p.output
}

export function modelCostFromBuckets(byModel) {
  let cost = 0
  for (const [model, d] of Object.entries(byModel || {})) {
    cost += calcCost(d.prompt_tokens || 0, d.completion_tokens || 0, model)
  }
  return Math.round(cost * 100) / 100
}
