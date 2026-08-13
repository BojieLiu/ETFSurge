import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcRoot = path.resolve(__dirname, '..')

/**
 * round20 P0-2 (2026-08-13): home CLS 0.3885 根因——GlobalIndicesStrip 骨架 2 行
 * vs 实际 5 个 region（A股/港股/美股/日经韩国/欧洲）→ 数据加载后高度 2→5 行，
 * 下方 summary cards 整体下移 → CLS。
 * 负向断言：骨架行数 != 实际 region 数 → FAIL（CLS 复现）。
 */
describe('GlobalIndicesStrip 骨架行数对齐（round20 P0-2 CLS）', () => {
  const src = fs.readFileSync(path.join(srcRoot, 'components', 'GlobalIndicesStrip.vue'), 'utf-8')

  it('骨架 v-for 行数为 5（对齐实际 region 数量）', () => {
    // 骨架：<div class="gis-skeleton-row" v-for="i in 5"
    const skeletonMatch = src.match(/gis-skeleton-row"\s+v-for="i in (\d+)"/)
    expect(skeletonMatch).toBeTruthy()
    expect(Number(skeletonMatch[1])).toBe(5)
  })

  it('regionOrder 定义 5 个 region（与骨架一致）', () => {
    // regionOrder = ['A股', '港股', '美股', '日经·韩国', '欧洲']
    const m = src.match(/regionOrder\s*=\s*\[([^\]]+)\]/)
    expect(m).toBeTruthy()
    const regions = m[1].split(',').filter((s) => s.includes("'")).length
    expect(regions).toBe(5)
  })

  it('骨架卡片行间距对齐 .indices-grid（padding 消除替换重排）', () => {
    const skeletonCards = src.match(/\.gis-skeleton-cards\s*\{[^}]+\}/)
    expect(skeletonCards).toBeTruthy()
    expect(skeletonCards[0]).toContain('padding: var(--space-2) 0')
  })
})
