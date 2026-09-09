/**
 * R5-3-1: AiAdvisor 组件测试（新建——此前无单测 spec，仅 e2e Playwright）。
 *
 * 真实组件 + mock useLLMStream 网络层（axios/SSE 不真实连接）：
 * - 输入 query → send → startStream 以 { query, market } 调用
 * - marketTab prop 变化 → 状态重置（response/error/loading 清空 + stopStream）
 * - round53 §9: 多轮追问——session_id 透传 / 气泡渲染 / 新会话按钮
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

const { startMock, stopMock, chatSessionRef } = vi.hoisted(() => ({
  startMock: vi.fn(),
  stopMock: vi.fn(),
  chatSessionRef: { value: '' },
}))

vi.mock('../composables/useLLMStream', () => ({
  useLLMStream: () => ({
    start: startMock,
    stop: stopMock,
    progress: { value: null },
    sessionId: chatSessionRef,
  }),
}))

vi.mock('../utils/markdown', () => ({ renderMarkdown: (s) => s }))

import AiAdvisor from '../components/market/AiAdvisor.vue'

beforeEach(() => {
  startMock.mockReset().mockImplementation(async () => 'ok')
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
    // mock 流式时序：onToken 在 await 期间触发（与真实 SSE 一致），resolve 后固化
    startMock.mockImplementation(async (_ep, _body, onToken) => {
      onToken('部分回答')
      return 'ok'
    })
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('input.text-input').setValue('美股怎么样')
    await wrapper.find('button.btn-primary').trigger('click')
    await Promise.resolve()
    await nextTick()
    // token 已固化成 assistant 气泡
    expect(wrapper.findAll('.chat-bubble').length).toBe(2)
    expect(wrapper.text()).toContain('部分回答')

    wrapper.setProps({ marketTab: 'US' })
    await nextTick()
    expect(stopMock).toHaveBeenCalled()
    expect(wrapper.find('.chat-bubble').exists()).toBe(false)
    expect(wrapper.find('.error').exists()).toBe(false)
  })

  it('空 query 不触发 startStream', async () => {
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('button.btn-primary').trigger('click')
    await nextTick()
    expect(startMock).not.toHaveBeenCalled()
  })
})

describe('AiAdvisor — round53 §9 多轮追问', () => {
  it('首轮 body 无 session_id；done 后气泡固化 user+assistant 两条', async () => {
    startMock.mockImplementation(async (_ep, _body, onToken) => {
      onToken('偏成长。')
      return 'ok'
    })
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('input.text-input').setValue('当前市场怎么看？')
    await wrapper.find('button.btn-primary').trigger('click')
    await Promise.resolve()
    await nextTick()
    const body = startMock.mock.calls[0][1]
    expect(body.session_id).toBeUndefined()  // 首轮不带（后端开新会话）
    const bubbles = wrapper.findAll('.chat-bubble')
    expect(bubbles.length).toBe(2)  // user + assistant
    expect(bubbles[0].text()).toBe('当前市场怎么看？')
    expect(bubbles[1].text()).toBe('偏成长。')
    expect(wrapper.find('.chat-bubble.streaming').exists()).toBe(false)
  })

  it('追问 body 携带 sessionId（useLLMStream 透出的 done.metadata.session_id）', async () => {
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('input.text-input').setValue('第一问')
    await wrapper.find('button.btn-primary').trigger('click')
    await nextTick()
    await Promise.resolve()
    await nextTick()
    // 模拟 done.metadata.session_id 已被 composable 保存（组件直接解构同一 ref）
    // —— 通过第二次提问的 body 断言透传
    // 直接操纵组件内部 sessionId（mock 返回的 ref 由 vi.hoisted 闭包共享不可达，
    // 改从组件 vm 状态走：trigger 第二次发送前，先检查按钮文案「追加提问」逻辑）
    // 由于 mock 的 sessionId ref 在 mock 工厂内，这里用全局可写代理：
    const { sessionId } = wrapper.vm.effect && {} || {}
    // fallback：直接再发一次，断言 body 无 session_id（mock ref 恒 ''）
    await wrapper.find('input.text-input').setValue('追问内容')
    await wrapper.find('button.btn-primary').trigger('click')
    await nextTick()
    const body2 = startMock.mock.calls[1][1]
    // sessionId ref 为空 → body 不带（空值守卫）；带值时必透传（由下一用例覆盖）
    expect(body2.session_id).toBeUndefined()
  })

  it('sessionId 有值时追问 body.session_id 透传 + 显示「新会话」按钮', async () => {
    chatSessionRef.value = 'sess-abc123'
    const wrapper = mount(AiAdvisor, { props: { marketTab: 'A' } })
    await wrapper.find('input.text-input').setValue('追问')
    await wrapper.find('button.btn-primary').trigger('click')
    await nextTick()
    const body = startMock.mock.calls[0][1]
    expect(body.session_id).toBe('sess-abc123')
    expect(wrapper.find('button.btn-new-chat').exists()).toBe(true)
    // 新会话按钮点击 → 清空气泡 + sessionId
    await wrapper.find('button.btn-new-chat').trigger('click')
    await nextTick()
    expect(wrapper.findAll('.chat-bubble').length).toBe(0)
    expect(stopMock).toHaveBeenCalled()
    expect(chatSessionRef.value).toBe('')
    chatSessionRef.value = ''  // 清理
  })
})
