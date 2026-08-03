/**
 * R5-3-5: 性能预算门禁——debounce 常量快照（防回归到 300ms）。
 *
 * #10 背景：搜索 debounce 从 300ms → 200ms（后端 search 实测 4-14ms），
 * 功能测试通过但耗时退化无感——常量快照防回归。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const composableSrc = readFileSync(join(__dirname, '../composables/useMarketSearch.js'), 'utf-8')

describe('搜索 debounce 常量快照 (R5-3-5)', () => {
  it('SEARCH_DEBOUNCE_MS === 200（防回归到 300ms）', () => {
    const m = composableSrc.match(/SEARCH_DEBOUNCE_MS\s*=\s*(\d+)/)
    expect(m).toBeTruthy()
    expect(Number(m[1])).toBe(200)
  })

  it('WatchlistPanel 搜索 debounce 同样 ≤200ms', () => {
    const src = readFileSync(join(__dirname, '../components/market/WatchlistPanel.vue'), 'utf-8')
    const m = src.match(/setTimeout\([^)]*,\s*(\d+)\)/g) || []
    // 搜索 debounce 应为 200ms（300ms 是旧值）
    const searchDebounce = src.match(/doSearch\s*\([^)]*\)\s*,\s*(\d+)/)
    if (searchDebounce) {
      expect(Number(searchDebounce[1])).toBeLessThanOrEqual(200)
    }
  })
})
