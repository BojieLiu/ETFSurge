import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcRoot = path.resolve(__dirname, '..')

/**
 * round19 P7-② (2026-08-12): WatchlistPanel 技术分析弹窗「转 AI 分析」按钮无反应
 * ——MarketAnalysis.vue:45 的 <WatchlistPanel> 漏绑 @analyze（对照 SectorHeatMap:48 有绑）。
 * 负向断言: 无 @analyze 绑定 → FAIL（现状点击无任何 AI 动作）。
 */
describe('MarketAnalysis @analyze 绑定（round19 P7-②）', () => {
  const src = fs.readFileSync(path.join(srcRoot, 'views', 'MarketAnalysis.vue'), 'utf-8')

  it('WatchlistPanel 组件行绑定 @analyze="onQuickAnalyze"', () => {
    const line = src.split('\n').find((l) => l.includes('<WatchlistPanel'))
    expect(line).toBeTruthy()
    expect(line).toContain('@analyze="onQuickAnalyze"')
  })

  it('onQuickAnalyze 实现存在（滚动到分析区 + 触发 UnifiedAnalysis）', () => {
    expect(src).toContain('function onQuickAnalyze({ mode, query, name })')
    expect(src).toContain('externalTrigger.value = { mode, query, name }')
  })

  it('SectorHeatMap 对照绑定仍在（回归）', () => {
    const line = src.split('\n').find((l) => l.includes('<SectorHeatMap'))
    expect(line).toContain('@analyze="onQuickAnalyze"')
  })
})

/**
 * round19 P7-① (2026-08-12): fetch_history 入口剥前缀——带 sh/sz/bj 前缀的
 * watchlist 条目（如 sz301308）技术分析 0 行。后端已有单测；此处源码断言
 * 归一化逻辑存在于入口（对照 §四十二 ⑤ 工具层绿 ≠ 链路通）。
 */
describe('fetch_history 入口归一化（round19 P7-①）', () => {
  const src = fs.readFileSync(
    path.join(srcRoot, '..', '..', 'backend', 'app', 'fetchers', 'china_market.py'),
    'utf-8',
  )

  it('fetch_history 函数体首段含前缀剥离逻辑', () => {
    const fnStart = src.indexOf('def fetch_history(')
    const fnBody = src.slice(fnStart, fnStart + 1200)
    expect(fnBody).toMatch(/startswith\(\("sh", "sz", "bj"\)/)
    expect(fnBody).toMatch(/symbol = symbol\[2:\]/)
  })
})
