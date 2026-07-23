/**
 * DesignHistory component tests.
 *
 * Guards against regression of:
 *   - Empty state shows "暂无任务记录" without crashing
 *   - Item list shows designs and checks with icons/labels
 *   - Status filter pills visible and interactive
 *   - Filter by status shows/hides items
 *   - "查看详情" link only shown for completed items
 *   - Emitting 'select' and 'close' events
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DesignHistory from '../components/design/DesignHistory.vue'

describe('DesignHistory.vue', () => {
  const stubs = {
    AppButton: { template: '<button class="app-btn-stub"><slot /></button>' },
  }

  const sampleItems = [
    { id: 1, _type: 'design', status: 'completed', created_at: '2026-07-23T10:00:00Z', capital: 500000 },
    { id: 2, _type: 'check', status: 'completed', created_at: '2026-07-23T09:00:00Z' },
    { id: 3, _type: 'design', status: 'running', created_at: '2026-07-23T08:00:00Z', capital: '-' },
    { id: 4, _type: 'design', status: 'failed', created_at: '2026-07-23T07:00:00Z', capital: 300000 },
  ]

  it('renders empty message when items is empty', () => {
    const wrapper = mount(DesignHistory, {
      props: { items: [], loading: false, loaded: true },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('暂无任务记录')
  })

  it('renders loading message when loading=true', () => {
    const wrapper = mount(DesignHistory, {
      props: { items: [], loading: true, loaded: false },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('加载中')
  })

  it('renders each history item with correct type label', () => {
    const wrapper = mount(DesignHistory, {
      props: { items: sampleItems, loading: false, loaded: true },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('智能组合设计')
    expect(wrapper.text()).toContain('策略检查与分析')
  })

  it('shows status badge for each item', () => {
    const wrapper = mount(DesignHistory, {
      props: { items: sampleItems, loading: false, loaded: true },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('成功')
    expect(wrapper.text()).toContain('运行中')
    expect(wrapper.text()).toContain('失败')
  })

  it('shows 查看详情 link only for completed items', () => {
    const wrapper = mount(DesignHistory, {
      props: { items: sampleItems, loading: false, loaded: true },
      global: { stubs },
    })
    // item 1 (completed) and item 2 (completed) should have it
    const detailLinks = wrapper.findAll('.history-detail-link')
    expect(detailLinks.length).toBe(2)
  })

  it('emits select with id and item on history item click', async () => {
    const wrapper = mount(DesignHistory, {
      props: { items: [sampleItems[0]], loading: false, loaded: true },
      global: { stubs },
    })
    await wrapper.find('.history-item').trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')[0]).toEqual([1, sampleItems[0]])
  })

  it('emits close when close button is clicked', async () => {
    const wrapper = mount(DesignHistory, {
      props: { items: sampleItems, loading: false, loaded: true },
      global: { stubs },
    })
    await wrapper.find('.history-close').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders filter tabs and filters items on click', async () => {
    const wrapper = mount(DesignHistory, {
      props: { items: sampleItems, loading: false, loaded: true },
      global: { stubs },
    })
    // All 4 filter tabs should be visible
    const tabs = wrapper.findAll('.filter-tab')
    expect(tabs.length).toBe(4)
    expect(tabs[0].text()).toBe('全部')
    expect(tabs[1].text()).toBe('运行中')
    expect(tabs[2].text()).toBe('已完成')
    expect(tabs[3].text()).toBe('失败')

    // Default shows all items
    expect(wrapper.findAll('.history-item').length).toBe(sampleItems.length)

    // Click "运行中" filter
    await tabs[1].trigger('click')
    expect(wrapper.findAll('.history-item').length).toBe(1)

    // Click "已完成"
    await tabs[2].trigger('click')
    expect(wrapper.findAll('.history-item').length).toBe(2)

    // Click "失败"
    await tabs[3].trigger('click')
    expect(wrapper.findAll('.history-item').length).toBe(1)

    // Click "全部" again
    await tabs[0].trigger('click')
    expect(wrapper.findAll('.history-item').length).toBe(sampleItems.length)
  })

  it('shows "当前筛选项无匹配任务" when filter has no match but items exist', async () => {
    const wrapper = mount(DesignHistory, {
      props: { items: sampleItems, loading: false, loaded: true },
      global: { stubs },
    })
    const tabs = wrapper.findAll('.filter-tab')
    // Click "运行中" — will have 1 match, so not zero
    await tabs[3].trigger('click') // "失败"
    expect(wrapper.text()).not.toContain('暂无任务记录')
    expect(wrapper.findAll('.history-item').length).toBe(1)

    // Remove failed items and see the empty-filter message
    await wrapper.setProps({ items: [sampleItems[0]] }) // only completed
    // Click "失败" — now no match
    await tabs[3].trigger('click')
    expect(wrapper.text()).toContain('当前筛选项无匹配任务')
  })
})
