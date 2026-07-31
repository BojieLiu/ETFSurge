/**
 * TDD tests for DashboardAiTools history list (Z27 §7.4).
 *
 * Covers the ReferenceError fix in loadHistoryList():
 *   - `checks` was referenced but never declared → history tab always threw
 *     ReferenceError (swallowed by catch → "加载历史记录失败" toast, empty list)
 *   - Now uses /portfolio/timeline `data.items` directly (design + check merged)
 *
 * Guards:
 *   - loadHistoryList renders timeline items without error
 *   - check items are passed to DesignHistory (clickable via getStrategyCheckDetail)
 *   - no "加载历史记录失败" error toast on success
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const getTimeline = vi.fn()
const getStrategyCheckDetail = vi.fn()
const toastShow = vi.fn()

vi.mock('../api', () => ({
  portfolioApi: {
    getTimeline,
    getStrategyCheckDetail,
    getDesign: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('../stores/toast', () => ({
  useToastStore: () => ({ show: toastShow, success: vi.fn(), error: vi.fn(), dismiss: vi.fn() }),
}))

vi.mock('../stores/task', () => ({
  useTaskStore: () => ({
    tasks: [],
    getTask: vi.fn(() => null),
    addTask: vi.fn(),
    updateTask: vi.fn(),
    removeTask: vi.fn(),
    hasRunningTask: false,
    activeTaskId: null,
    getDesignState: vi.fn(() => null),
    clearDesignState: vi.fn(),
    persistDesignState: vi.fn(),
    clearCompleted: vi.fn(),
    registerTaskCompletion: vi.fn(),
  }),
}))

vi.mock('../components/design/DesignWizard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignLoading.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../utils/formatDate', () => ({ formatDate: (d) => String(d) || '' }))

const DesignHistoryStub = {
  template: '<div class="history-stub" />',
  props: ['items', 'loading', 'loaded'],
}

describe('DashboardAiTools — loadHistoryList (Z27 §7.4)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getTimeline.mockReset()
    getStrategyCheckDetail.mockReset()
    toastShow.mockReset()
  })

  it('renders timeline items (design + check) without ReferenceError', async () => {
    getTimeline.mockResolvedValue({
      data: {
        items: [
          { id: 1, _type: 'design', status: 'completed', created_at: '2026-07-31T10:00:00Z' },
          { id: 97, _type: 'check', status: 'completed', created_at: '2026-07-31T11:00:00Z' },
        ],
      },
    })

    const wrapper = mount(await import('../views/DashboardAiTools.vue').then(m => m.default), {
      global: {
        plugins: [createPinia()],
        stubs: {
          DesignHistory: DesignHistoryStub,
          Teleport: { template: '<div><slot /></div>' },
        },
      },
    })

    // 触发历史 Tab（第 3 个 core-action-btn：设计/策略检查/任务列表）
    const buttons = wrapper.findAll('.core-action-btn')
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    await buttons[2].trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await wrapper.vm.$nextTick()

    // DesignHistory 收到合并后的 items（含 check 项）
    const stub = wrapper.findComponent(DesignHistoryStub)
    expect(stub.exists()).toBe(true)
    const items = stub.props('items') || []
    expect(items.some((i) => i._type === 'design')).toBe(true)
    expect(items.some((i) => i._type === 'check')).toBe(true)

    // 关键断言：不再抛 ReferenceError → 不弹「加载历史记录失败」
    expect(toastShow).not.toHaveBeenCalledWith('加载历史记录失败，请检查后端连接', 'error')
  })

  it('does not emit error toast when timeline returns empty items', async () => {
    getTimeline.mockResolvedValue({ data: { items: [] } })

    const wrapper = mount(await import('../views/DashboardAiTools.vue').then(m => m.default), {
      global: {
        plugins: [createPinia()],
        stubs: {
          DesignHistory: DesignHistoryStub,
          Teleport: { template: '<div><slot /></div>' },
        },
      },
    })

    const buttons = wrapper.findAll('.core-action-btn')
    await buttons[2].trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    await wrapper.vm.$nextTick()

    expect(toastShow).not.toHaveBeenCalledWith('加载历史记录失败，请检查后端连接', 'error')
  })
})
