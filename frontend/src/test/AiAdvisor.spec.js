/**
 * R5-3-1: AiAdvisor 组件测试（新建——此前无单测 spec，仅 e2e Playwright）。
 *
 * 真实组件 + mock useLLMStream 网络层（axios/SSE 不真实连接）：
 * - 输入 query → send → startStream 以 { query, market } 调用
 * - marketTab prop 变化 → 状态重置（response/error/loading 清空 + stopStream）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

const { startMock, stopMock } = vi.hoisted(() => ({
  startMock: vi.fn(),
  stopMock: vi.fn(),
}))

vi.mock('../composables/useLLMStream', () => ({
  useLLMStream: () => ({ start: startMock, stop: stopMock }),
}))

vi.mock('../utils/markdown', () => ({ renderMarkdown: (s) => s }))

import AiAdvisor from '../components/market/AiAdvisor.vue'

beforeEach(() => {
  startMock.mockReset().mockResolvedValue('ok')
  stopMock.mockReset()
})

describe('AiAdvisor (R5-3-1)', () => {
  it('输入 query → send → startStream 以 { query, market } 调用', async () => {
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('input.text-input').setValue('当前A股市场怎么配置')
    await wrapper.find('button.btn-primary').trigger('click')
    await nextTick()
    expect(startMock).toHaveBeenCalledTimes(1)
    expect(startMock.mock.calls[0][0]).toBe('/llm-advice/stream')
    expect(startMock.mock.calls[0][1]).toEqual({ query: '当前A股市场怎么配置', market: 'A' })
  })

  it('marketTab 变化 → 状态重置 + stopStream（A→US 旧回答不残留）', async () => {
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('input.text-input').setValue('美股怎么样')
    await wrapper.find('button.btn-primary').trigger('click')
    await nextTick()
    // 模拟流式 token 写入 response
    startMock.mock.calls[0][2]('部分回答')
    await nextTick()
    expect(wrapper.find('.response').text()).toContain('部分回答')

    wrapper.setProps({ marketTab: 'US' })
    await nextTick()
    expect(stopMock).toHaveBeenCalled()
    expect(wrapper.find('.response').exists()).toBe(false)
    expect(wrapper.find('.error').exists()).toBe(false)
  })

  it('空 query 不触发 startStream', async () => {
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('button.btn-primary').trigger('click')
    await nextTick()
    expect(startMock).not.toHaveBeenCalled()
  })
})
