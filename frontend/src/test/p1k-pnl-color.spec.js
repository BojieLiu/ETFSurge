/**
 * round14 P1-K: 盈亏数字红涨绿跌（scoped CSS 覆盖修复）。
 *
 * 三层次验证（docs/archived/round14 §5 P1-K 测试 1+2）：
 * 1. 组件行为断言：pnlOn>0 → 元素 class 含 text-up；pnlOff<0 → text-down
 * 2. 源码级覆盖规则断言（唯一能抓 CSS 特异性覆盖的方式——jsdom css:false 不层叠）：
 *    fs.readFileSync 读 .vue style 块，断言 `.summary-value.text-up` /
 *    `.stat-num.text-up` 覆盖规则存在、color 为 var(--color-text-up/down)
 * 3. 负向：删除覆盖规则（模拟回归）→ 源码断言 FAIL
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { mount } from '@vue/test-utils'
import SummaryCards from '../components/dashboard/SummaryCards.vue'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SUMMARY_CARDS_SRC = readFileSync(join(__dirname, '../components/dashboard/SummaryCards.vue'), 'utf-8')
const FACTOR_VIEW_SRC = readFileSync(join(__dirname, '../views/system/FactorModelView.vue'), 'utf-8')

function mountCards(pnlOn, pnlOff) {
  return mount(SummaryCards, {
    props: {
      activeTab: 'combined',
      totalAll: 100000,
      pnlOn,
      pnlOff,
      pnlTotal: 50,
      pnlHistory: { summary: {}, holdings: [], daily_series: [] },
      pnlHistoryLoading: false,
      loading: false,
    },
  })
}

describe('SummaryCards 盈亏色 class 绑定（P1-K）', () => {
  it('pnlOn>0 当日盈亏绑定 text-up（红涨）', () => {
    const wrapper = mountCards(100, -50)
    // 渲染格式 ¥{signed(pnl)}{formatNum(abs)} → "¥+100"；总仓位 "¥100000" 不含 "+"
    const onEx = wrapper.findAll('.summary-value').find((el) => el.text().includes('+100'))
    expect(onEx).toBeTruthy()
    expect(onEx.classes()).toContain('text-up')
  })

  it('pnlOff<0 当日盈亏绑定 text-down（绿跌）', () => {
    const wrapper = mountCards(100, -50)
    const offEx = wrapper.findAll('.summary-value').find((el) => el.text().includes('-50'))
    expect(offEx).toBeTruthy()
    expect(offEx.classes()).toContain('text-down')
  })
})

describe('源码级覆盖规则断言（P1-K，jsdom 抓 CSS 覆盖的唯一方式）', () => {
  it('SummaryCards.vue 含 .summary-value.text-up/.text-down 覆盖规则（红涨绿跌）', () => {
    expect(SUMMARY_CARDS_SRC).toMatch(/\.summary-value\.text-up\s*\{\s*color:\s*var\(--color-text-up\)/)
    expect(SUMMARY_CARDS_SRC).toMatch(/\.summary-value\.text-down\s*\{\s*color:\s*var\(--color-text-down\)/)
  })

  it('FactorModelView.vue 含 .stat-num.text-up/.text-down 覆盖规则（防御性含 text-warn）', () => {
    expect(FACTOR_VIEW_SRC).toMatch(/\.stat-num\.text-up\s*\{\s*color:\s*var\(--color-text-up\)/)
    expect(FACTOR_VIEW_SRC).toMatch(/\.stat-num\.text-down\s*\{\s*color:\s*var\(--color-text-down\)/)
    expect(FACTOR_VIEW_SRC).toMatch(/\.stat-num\.text-warn\s*\{\s*color:\s*var\(--color-warning-600\)/)
  })

  it('负向：移除覆盖规则后源码断言必须 FAIL（防恒绿）', () => {
    const withoutRule = SUMMARY_CARDS_SRC.replace(/\.summary-value\.text-up[^}]*}/, '')
    expect(withoutRule).not.toMatch(/\.summary-value\.text-up\s*\{\s*color:\s*var\(--color-text-up\)/)
  })
})
