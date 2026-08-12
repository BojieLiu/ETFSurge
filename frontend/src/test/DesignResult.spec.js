/**
 * round17 P2-6（因子分列）+ P2-8（degraded 前端消费）。
 *
 * P2-6：持仓表「因子分」列——数据由 get_design 透传 factor_score（连续值可为负），
 *       列头 tooltip 注明口径（区别于技术信号）。负向：列头误称"综合信号" → FAIL。
 * P2-8：design 响应带 degradation → 顶部黄色提示条「数据源冷却」；无 degradation /
 *       degraded=false 时不渲染（不误报）→ 负向：degraded 无提示 → FAIL。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DesignResult from '../components/design/DesignResult.vue'

function makePlan(overrides = {}) {
  return {
    style: 'balanced',
    allocations: [
      { symbol: '510300', name: '沪深300ETF', layer: 'core', target_weight: 0.3, daily_change_pct: 0.5, factor_score: 0.75 },
      { symbol: '159338', name: '中证A500ETF', layer: 'core', target_weight: 0.2, daily_change_pct: null, factor_score: -0.17 },
      { symbol: 'CASH', name: '现金', layer: 'cash', target_weight: 0.25, factor_score: null },
    ],
    ...overrides,
  }
}

async function mountResult(plan, extraProps = {}) {
  const wrapper = mount(DesignResult, {
    props: { plans: [plan], ...extraProps },
    global: {
      mocks: { $t: (s) => s },
      stubs: { AppButton: { template: '<button><slot /></button>' } },
    },
  })
  await wrapper.find('.plan-card').trigger('click')
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('DesignResult P2-6 因子分列', () => {
  it('持仓表含「因子分」列头 + tooltip 注明口径（负向：列头含「综合信号」 → FAIL）', async () => {
    const wrapper = await mountResult(makePlan())
    const head = wrapper.find('.factor-col-head')
    expect(head.exists()).toBe(true)
    expect(head.text()).toBe('因子分')
    expect(head.attributes('title')).toContain('因子综合分')
    expect(head.attributes('title')).toContain('区别于技术信号')
    expect(head.text()).not.toContain('综合信号')
  })

  it('因子分连续值渲染（正负都显示，负向：缺失时不得渲染 0）', async () => {
    const wrapper = await mountResult(makePlan())
    const rows = wrapper.findAll('tbody tr')
    const row510300 = rows.find(r => r.text().includes('510300'))
    expect(row510300.text()).toContain('+0.75')
    const row159338 = rows.find(r => r.text().includes('159338'))
    expect(row159338.text()).toContain('-0.17')
  })

  it('无 factor_score 的行显示「—」（不误显示 0.00）', async () => {
    const wrapper = await mountResult(makePlan())
    const rows = wrapper.findAll('tbody tr')
    const cashRow = rows.find(r => r.text().includes('CASH'))
    expect(cashRow.text()).not.toContain('0.00')
    expect(cashRow.text()).toContain('—')
  })
})

describe('DesignResult P2-8 degradation 提示条', () => {
  it('degradation 存在时显示「数据源冷却」提示（负向：无提示 → FAIL）', async () => {
    const wrapper = await mountResult(makePlan(), {
      degradation: { mode: 'partial_data', pool_degraded: true, reason: '部分候选标的缺因子分' },
    })
    const banner = wrapper.find('.degradation-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('数据源冷却')
    expect(banner.text()).toContain('partial_data')
    expect(banner.text()).toContain('候选池降级')
  })

  it('无 degradation 时不渲染提示条（不误报）', async () => {
    const wrapper = await mountResult(makePlan())
    expect(wrapper.find('.degradation-banner').exists()).toBe(false)
  })

  it('degradation 为 null（正常模式）时不渲染提示条', async () => {
    const wrapper = await mountResult(makePlan(), { degradation: null })
    expect(wrapper.find('.degradation-banner').exists()).toBe(false)
  })

  it('degradation mode=normal（Z11 正常路径）时不渲染提示条（不误报）', async () => {
    // 后端正常数据管道也返回 degradation={mode:'normal',...}（Z11 设计）——
    // 负向：mode=normal 渲染「数据源冷却」→ FAIL
    const wrapper = await mountResult(makePlan(), {
      degradation: { mode: 'normal', reason: '正常数据管道', pool_degraded: false },
    })
    expect(wrapper.find('.degradation-banner').exists()).toBe(false)
  })

  it('degradation pool_degraded=true 时即使 mode=normal 也渲染', async () => {
    const wrapper = await mountResult(makePlan(), {
      degradation: { mode: 'normal', pool_degraded: true, reason: '候选池冷却' },
    })
    expect(wrapper.find('.degradation-banner').exists()).toBe(true)
  })
})
