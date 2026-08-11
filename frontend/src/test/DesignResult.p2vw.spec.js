/**
 * round14 P2-V（现金仓位展示）+ P2-W（涨跌幅缺失显性化）。
 *
 * - header 显示「现金 x%」（从 allocations 找 symbol==CASH）
 * - ETF 计数排除 CASH（负向：CASH 计入时计数错误）
 * - dcp=null 显示「数据源不可用」（负向：不得渲染「—」或「0%」）
 * - CASH 行涨跌列不显示「数据源不可用」（现金无涨跌幅语义）
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DesignResult from '../components/design/DesignResult.vue'

function makePlan(overrides = {}) {
  return {
    style: 'balanced',
    allocations: [
      { symbol: '510300', name: '沪深300ETF', layer: 'core', target_weight: 0.3, daily_change_pct: 0.5 },
      { symbol: '159338', name: '中证A500ETF', layer: 'core', target_weight: 0.2, daily_change_pct: null },
      { symbol: 'CASH', name: '现金', layer: 'cash', target_weight: 0.25 },
    ],
    ...overrides,
  }
}

async function mountResult(plan) {
  const wrapper = mount(DesignResult, {
    props: { plans: [plan] },
    global: {
      mocks: { $t: (s) => s },
      stubs: { AppButton: { template: '<button><slot /></button>' } },
    },
  })
  // plan-detail 需 expandedPlan === style 才渲染 → 点击卡片展开 + 等渲染
  await wrapper.find('.plan-card').trigger('click')
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('DesignResult P2-V 现金仓位', () => {
  it('header 显示「现金 25%」', async () => {
    const wrapper = await mountResult(makePlan())
    const stats = wrapper.find('.plan-stats').text()
    expect(stats).toContain('现金 25%')
  })

  it('ETF 计数排除 CASH（负向：CASH 计入时计数错误）', async () => {
    const wrapper = await mountResult(makePlan())
    const stats = wrapper.find('.plan-stats').text()
    expect(stats).toContain('2 只 ETF')
    expect(stats).not.toContain('3 只 ETF')
  })

  it('无 CASH 时不显示现金项', async () => {
    const plan = makePlan({ allocations: makePlan().allocations.filter(a => a.symbol !== 'CASH') })
    const wrapper = await mountResult(plan)
    expect(wrapper.find('.plan-stats').text()).not.toContain('现金')
  })
})

describe('DesignResult P2-W 涨跌幅缺失显性化', () => {
  it('dcp=null 渲染「数据源不可用」（负向：不得渲染「—」或「0%」）', async () => {
    const wrapper = await mountResult(makePlan())
    const text = wrapper.text()
    expect(text).toContain('数据源不可用')
    const rows = wrapper.findAll('tbody tr')
    const row159338 = rows.find(r => r.text().includes('159338'))
    expect(row159338.text()).toContain('数据源不可用')
    expect(row159338.text()).not.toContain('0.00%')
  })

  it('CASH 行不显示「数据源不可用」（现金无涨跌幅语义）', async () => {
    const wrapper = await mountResult(makePlan())
    const rows = wrapper.findAll('tbody tr')
    const cashRow = rows.find(r => r.text().includes('CASH'))
    expect(cashRow.text()).not.toContain('数据源不可用')
  })

  it('dcp 有值时显示红涨绿跌 class', async () => {
    const wrapper = await mountResult(makePlan())
    const rows = wrapper.findAll('tbody tr')
    const row510300 = rows.find(r => r.text().includes('510300'))
    expect(row510300.text()).toContain('+0.50%')
    expect(row510300.find('.text-up').exists()).toBe(true)
  })
})
