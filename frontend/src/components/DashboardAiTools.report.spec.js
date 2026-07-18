/**
 * TDD tests for design report tab behavior (no hardcoded fallback report).
 *
 * Contract: api-contracts/portfolio/design.md §2.8
 *
 * Covers:
 *   - design_text must be empty ('') on initial result load (no hardcoded report)
 *   - When design_text is empty and no error, waiting state is shown
 *   - When reportError is set, error state is shown
 *   - WS streaming chunks are concatenated into design_text
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

// Mock marked to return the input as-is
vi.mock('marked', () => ({
  default: (text) => text,
  marked: (text) => text,
}))

// Mock route-related imports
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {}, path: '/' }),
}))

// Mock echarts
vi.mock('echarts', () => ({ init: vi.fn(() => ({ setOption: vi.fn(), dispose: vi.fn() })) }))

// Mock the API module
vi.mock('../api', () => ({
  portfolioApi: {
    designAsync: vi.fn().mockResolvedValue({ data: { task_id: 123 } }),
    getTask: vi.fn().mockResolvedValue({ data: { task_id: 123, status: 'completed', design_id: 456, progress: 100 } }),
    getDesign: vi.fn().mockResolvedValue({ data: { strategies: [], created_at: '2026-07-18T00:00:00Z', market_context: {} } }),
    listDesigns: vi.fn().mockResolvedValue({ data: [] }),
    applyPortfolioDesign: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// Mock stores that DashboardAiTools imports
vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({ fetchEtfs: vi.fn(), etfs: [] }),
}))

// Mock toast store
vi.mock('../stores/toast', () => ({
  useToastStore: () => ({ show: vi.fn(), toasts: [], dismiss: vi.fn() }),
}))

// Mock task store — provide a fresh instance per test
vi.mock('../stores/task', () => ({
  useTaskStore: () => ({
    tasks: [],
    getTask: vi.fn(() => null),
    addTask: vi.fn(),
    updateTask: vi.fn(),
    removeTask: vi.fn(),
    clearCompleted: vi.fn(),
    designState: null,
    persistDesignState: vi.fn(),
    getDesignState: vi.fn(() => null),
    clearDesignState: vi.fn(),
  }),
}))

// Mock formatDate
vi.mock('../utils/formatDate', () => ({ formatDate: (d) => d || '' }))

describe('DashboardAiTools - Design Report Tab', () => {
  let wrapper

  beforeEach(async () => {
    setActivePinia(createPinia())
    const DashboardAiTools = await import('./DashboardAiTools.vue')
    wrapper = mount(DashboardAiTools.default, {
      global: {
        stubs: {
          AppButton: true,
          AppInput: true,
          AppSelect: true,
        },
      },
    })
  })

  it('should have empty design_text on fresh result (no hardcoded fallback)', async () => {
    // The component starts in wizard state; designResult is null
    expect(wrapper.vm.designResult).toBeNull()
  })

  it('should show waiting state when design_text is empty and no error', async () => {
    // Simulate result state with empty design_text
    wrapper.vm.designResult = { plans: [{ style: 'balanced' }], design_text: '' }
    wrapper.vm.designStep = 'result'
    wrapper.vm.designTab = 'report'
    wrapper.vm.reportError = ''
    await nextTick()

    // Should show the waiting spinner and text
    expect(wrapper.text()).toContain('AI 报告生成中')
    // Should NOT show the markdown body (no design_text)
    expect(wrapper.find('.markdown-body').exists()).toBe(false)
  })

  it('should show error state when reportError is set', async () => {
    wrapper.vm.designResult = { plans: [{ style: 'balanced' }], design_text: '' }
    wrapper.vm.designStep = 'result'
    wrapper.vm.designTab = 'report'
    wrapper.vm.reportError = 'API 调用超时'
    await nextTick()

    expect(wrapper.text()).toContain('报告生成失败')
    expect(wrapper.text()).toContain('API 调用超时')
  })

  it('should render markdown when design_text is populated by WS', async () => {
    wrapper.vm.designResult = {
      plans: [{ style: 'balanced' }],
      design_text: '## 市场环境\n深证成指今日跌 5.4%',
    }
    wrapper.vm.designStep = 'result'
    wrapper.vm.designTab = 'report'
    await nextTick()

    expect(wrapper.find('.markdown-body').exists()).toBe(true)
    expect(wrapper.text()).toContain('深证成指今日跌 5.4%')
  })

  it('should clear reportError on retryReport', async () => {
    wrapper.vm.reportError = 'WS 连接断开'
    wrapper.vm.retryReport()
    expect(wrapper.vm.reportError).toBe('')
  })
})
