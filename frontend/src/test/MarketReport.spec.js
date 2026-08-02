/**
 * F8 R25: MarketReport 按钮三态——loading / 已生成 / 未生成。
 * R4-28: 切换 marketTab → 清空旧报告 + 自动重新生成。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('../utils/markdown', () => ({ renderMarkdown: (s) => s }))

const startMock = vi.fn()
const stopMock = vi.fn()
vi.mock('../composables/useLLMStream', () => ({
  useLLMStream: () => ({ start: startMock, stop: stopMock }),
}))

import MarketReport from '../components/market/MarketReport.vue'

function mounted(tab = 'A') {
  return mount(MarketReport, {
    props: { marketTab: tab },
    global: { mocks: { $t: (s) => s } },
  })
}

describe('MarketReport R25 (按钮三态)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    startMock.mockResolvedValue({ fullText: '' })
  })

  it('未生成 → 显示"生成A股研判"', () => {
    const wrapper = mounted()
    expect(wrapper.text()).toContain('生成A股研判')
    expect(wrapper.text()).not.toContain('重新生成研判')
  })

  it('已生成 report → 显示"重新生成研判"', async () => {
    const wrapper = mounted()
    wrapper.vm.report = '## 测试报告'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('重新生成研判')
    expect(wrapper.text()).not.toContain('生成A股研判')
  })

  it('loading 态 → 显示"AI 分析中..."', async () => {
    const wrapper = mounted()
    wrapper.vm.loading = true
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('AI 分析中...')
  })
})

describe('MarketReport R4-28 (切换 marketTab)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    startMock.mockResolvedValue({ fullText: '' })
  })

  it('切换 tab → 取消旧流、清空旧报告、以新市场自动重新生成', async () => {
    const wrapper = mounted('HK')
    // 先有一份港股报告
    wrapper.vm.report = '## 港股研判'
    await wrapper.vm.$nextTick()
    // 切到 A 股
    await wrapper.setProps({ marketTab: 'A' })
    await wrapper.vm.$nextTick()
    expect(stopMock).toHaveBeenCalled() // 取消旧流
    expect(wrapper.vm.report).toBe('') // 旧报告清空
    expect(startMock).toHaveBeenCalledTimes(1)
    expect(startMock.mock.calls[0][1]).toMatchObject({ market: 'A' }) // 新市场参数
  })

  it('快速切换时序号守卫：旧流 token 不再写入报告', async () => {
    const wrapper = mounted('A')
    const callbacks = []
    startMock.mockImplementation((endpoint, body, cb) => {
      callbacks.push(cb)
      return new Promise(() => {}) // 永不 resolve，模拟进行中的流
    })
    await wrapper.setProps({ marketTab: 'HK' }) // watch 触发 → 流 1
    wrapper.vm.generate() // 手动再生成（流 2，序号更高）
    expect(callbacks.length).toBe(2)
    callbacks[0]('旧的 token') // 流 1 的 token——应被序号守卫丢弃
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.report).toBe('')
  })
})
