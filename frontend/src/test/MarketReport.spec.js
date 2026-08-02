/**
 * F8 R25: MarketReport 按钮三态——loading / 已生成 / 未生成。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('../utils/markdown', () => ({ renderMarkdown: (s) => s }))

import MarketReport from '../components/market/MarketReport.vue'

function mounted() {
  return mount(MarketReport, {
    props: { marketTab: 'A' },
    global: { mocks: { $t: (s) => s } },
  })
}

describe('MarketReport R25 (按钮三态)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('未生成 → 显示"生成市场研判"', () => {
    const wrapper = mounted()
    expect(wrapper.text()).toContain('生成市场研判')
    expect(wrapper.text()).not.toContain('重新生成研判')
  })

  it('已生成 report → 显示"重新生成研判"', async () => {
    const wrapper = mounted()
    wrapper.vm.report = '## 测试报告'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('重新生成研判')
    expect(wrapper.text()).not.toContain('生成市场研判')
  })

  it('loading 态 → 显示"AI 分析中..."', async () => {
    const wrapper = mounted()
    wrapper.vm.loading = true
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('AI 分析中...')
  })
})
