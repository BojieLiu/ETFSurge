import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import GlobalIndicesStrip from '../components/GlobalIndicesStrip.vue'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcRoot = path.resolve(__dirname, '..')

describe('GlobalIndicesStrip', () => {
  const mockData = {
    'A股': [
      { symbol: '000001', name: '上证指数', price: 3245.67, change_pct: 1.23,
        available: true, region: 'A股', asset_type: 'index', change_amount: 39.5 },
    ],
    '港股': [
      { symbol: '^HSI', name: '恒生指数', price: 22000.0, change_pct: -0.5,
        available: true, region: '港股', asset_type: 'index', change_amount: -110.0 },
    ],
  }

  it('renders index data when available=true', () => {
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: mockData },
    })
    // Should show price and change, not '暂无'
    expect(wrapper.text()).toContain('3245.67')
    expect(wrapper.text()).toContain('+1.23%')
    expect(wrapper.text()).toContain('22000.00')
    expect(wrapper.text()).toContain('-0.50%')
    expect(wrapper.text()).not.toContain('暂无数据')
    expect(wrapper.text()).toContain('上证指数')
    expect(wrapper.text()).toContain('恒生指数')
  })

  it('shows stale data when available=false but price present', () => {
    const staleData = {
      '港股': [
        { symbol: '^HSI', name: '恒生指数', price: 22000.0, change_pct: -0.5,
          available: false, region: '港股', asset_type: 'index' },
      ],
    }
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: staleData },
    })
    // Should still show the cached price but indicate '已收盘'
    expect(wrapper.text()).toContain('22000.00')
    expect(wrapper.text()).toContain('已收盘')
    expect(wrapper.text()).not.toContain('暂无数据')
  })

  it('shows empty state when globalIndices is empty', () => {
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: {} },
    })
    expect(wrapper.text()).toContain('暂无数据')
    expect(wrapper.text()).toContain('点击刷新获取')
  })

  it('shows placeholder when available=false and price=null', () => {
    const emptyData = {
      'A股': [
        { symbol: '000001', name: '上证指数', price: null, change_pct: null,
          available: false, region: 'A股', asset_type: 'index' },
      ],
    }
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: emptyData },
    })
    expect(wrapper.text()).toContain('上证指数')
    expect(wrapper.text()).toContain('—')  // placeholder for both price and change
  })
})

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

  it('F35: 骨架卡片高度对齐真实 index-card（~88px，消除每行高度差）', () => {
    // round23 F35 (P0-2 补完): 行数对齐只消除「2→5 行」增量，每行高度差
    // （骨架 64px vs 真实 ~88px）仍使数据替换时下方下移 → CLS 0.39 恒定。
    const card = src.match(/\.gis-skeleton-card\s*\{[^}]+\}/)
    expect(card).toBeTruthy()
    const h = card[0].match(/height:\s*(\d+)px/)
    expect(h).toBeTruthy()
    const height = Number(h[1])
    expect(height).toBeGreaterThanOrEqual(84)
    expect(height).toBeLessThanOrEqual(96)
  })

  it('F35: 骨架行 margin 对齐 .region-row（10px）', () => {
    const row = src.match(/\.gis-skeleton-row\s*\{[^}]+\}/)
    expect(row).toBeTruthy()
    expect(row[0]).toContain('margin-bottom: 10px')
  })
})
