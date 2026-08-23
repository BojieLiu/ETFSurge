/**
 * round35 §16-T-P2-10 (docs/round35-architecture-review.md)：裸奔组件补 mount 测试
 * 第一批 4 个（ErrorOverlay / CapitalInputBar / AllocationTable / ConfigView）。
 * 断言行为而非实现细节：条件渲染、事件透出、数据驱动渲染。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('../api/index.js', () => ({
  adminApi: {
    // ConfigView 契约：getConfig() → { items: [{key,label,value,description,...}] }
    getConfig: vi.fn().mockResolvedValue({
      data: {
        items: [
          { key: 'llm_primary_provider', label: 'LLM 主提供方', value: 'deepseek', description: 'LLM 主提供方', editable: true },
          { key: 'data_dir', label: '数据目录', value: 'data', description: '数据目录', editable: false },
        ],
      },
    }),
    updateConfig: vi.fn().mockResolvedValue({ data: {} }),
    resetConfigKey: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import ErrorOverlay from '../components/dashboard/ErrorOverlay.vue'
import CapitalInputBar from '../components/dashboard/CapitalInputBar.vue'
import AllocationTable from '../components/dashboard/AllocationTable.vue'
import ConfigView from '../views/ConfigView.vue'

describe('ErrorOverlay (T-P2-10 裸奔组件补测)', () => {
  it('hasError=false 时不渲染错误卡', () => {
    const w = mount(ErrorOverlay, { props: { hasError: false } })
    expect(w.find('.error-card').exists()).toBe(false)
  })

  it('hasError=true 渲染错误信息且重试按钮 emit retry（负向：无此断言则错误态不可验）', async () => {
    const w = mount(ErrorOverlay, { props: { hasError: true, errorMessage: '行情源超时' } })
    expect(w.find('.error-card').exists()).toBe(true)
    expect(w.text()).toContain('行情源超时')
    await w.find('button').trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
  })
})

describe('CapitalInputBar (T-P2-10)', () => {
  const mountBar = (props) => mount(CapitalInputBar, {
    props: { activeTab: 'on_exchange', capitalOn: 500000, capitalOff: 0, ...props },
  })

  it('渲染当前场内仓位金额到输入框', () => {
    const w = mountBar()
    const input = w.find('input[type="number"]')
    expect(input.exists()).toBe(true)
    expect(Number(input.element.value)).toBe(500000)
  })

  it('修改输入 emit update:capitalOn（v-model 语义）', async () => {
    const w = mountBar()
    const input = w.find('input[type="number"]')
    input.element.value = '600000'
    await input.trigger('input')
    expect(w.emitted('update:capitalOn')?.[0]).toEqual([600000])
  })

  it('off_exchange tab 渲染场外输入并 emit 对应事件', async () => {
    const w = mountBar({ activeTab: 'off_exchange' })
    const input = w.find('input[type="number"]')
    input.element.value = '123000'
    await input.trigger('input')
    expect(w.emitted('update:capitalOff')?.[0]).toEqual([123000])
  })
})

describe('AllocationTable (T-P2-10)', () => {
  const rows = [
    { symbol: '510300', name: '沪深300ETF', target_weight: 0.3, target_amount: 150000, current_price: 3.9, change_pct: 0.5 },
    { symbol: '518880', name: '黄金ETF', target_weight: 0.1, target_amount: 50000, current_price: 7.2, change_pct: -1.2 },
  ]

  it('渲染标题、持仓行数与现金行', () => {
    const w = mount(AllocationTable, {
      props: { items: rows, cashPct: 0.05, cashAmount: 25000, title: '防御型配置' },
    })
    expect(w.text()).toContain('防御型配置')
    expect(w.findAll('tbody tr')).toHaveLength(2)
    expect(w.text()).toContain('510300')
    expect(w.text()).toContain('30.0%')
    // 现金行
    expect(w.text()).toContain('5.0%')
    expect(w.text()).toContain('25,000')
  })

  it('空 items 仅表头 + 现金行（不抛错）', () => {
    const w = mount(AllocationTable, { props: { items: [], cashPct: 1, cashAmount: 100, title: '空组合' } })
    expect(w.findAll('tbody tr')).toHaveLength(0)
    expect(w.text()).toContain('100.0%')
  })
})

describe('ConfigView (T-P2-10)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('加载后渲染配置条目（loading → loaded）', async () => {
    const { adminApi } = await import('../api/index.js')
    const w = mount(ConfigView)
    await flushPromises()
    expect(adminApi.getConfig.mock.calls.length).toBeGreaterThan(0)
    expect(w.find('.loading').exists()).toBe(false)
    expect(w.text()).toContain('LLM 主提供方')
    expect(w.text()).toContain('数据目录')
  })

  it('getConfig reject → 错误提示而非空白冒充成功', async () => {
    const { adminApi } = await import('../api/index.js')
    adminApi.getConfig.mockRejectedValueOnce(new Error('backend down'))
    const w = mount(ConfigView)
    await flushPromises()
    expect(w.text()).toMatch(/加载配置失败/)
  })
})
