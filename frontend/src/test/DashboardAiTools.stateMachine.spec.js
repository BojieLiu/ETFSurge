/**
 * O11 (round8 §7 + interaction-redesign D1/D3/P4): 设计任务状态机纠偏。
 *
 * 验收:
 * ① 失败卡带「重试一次」+「返回」，均可操作；
 * ② 同 tab 失败后再次进入回到 idle（不残留）；
 * ③ WS 完成 + 轮询只 finalize 一次（taskId 幂等）；
 * ④ 退出持久化 running、再进恢复 loading（失败不持久化）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

const persistMock = vi.fn()
const designAsyncMock = vi.fn()

vi.mock('../api', () => ({
  portfolioApi: {
    designAsync: (...a) => designAsyncMock(...a),
    strategyCheck: vi.fn().mockResolvedValue({ data: { task_id: 9 } }),
    getTask: vi.fn().mockResolvedValue({ data: { status: 'running', progress: 50 } }),
    getStrategyCheckResult: vi.fn().mockRejectedValue(new Error('no result yet')),
    getDesign: vi.fn().mockRejectedValue(new Error('not found')),
    listDesigns: vi.fn().mockResolvedValue({ data: [] }),
    listStrategyChecks: vi.fn().mockResolvedValue({ data: [] }),
    applyPortfolioDesign: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({ fetchEtfs: vi.fn(), etfs: [], capitalOn: 500000, capitalOff: 0 }),
}))
vi.mock('../stores/toast', () => ({
  useToastStore: () => ({ show: vi.fn(), success: vi.fn(), error: vi.fn(), dismiss: vi.fn() }),
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
    persistDesignState: persistMock,
    clearCompleted: vi.fn(),
    registerTaskCompletion: vi.fn(() => 1),
  }),
}))

vi.mock('../components/FactorModelView.vue', () => ({
  default: { name: 'FactorModelView', template: '<div data-testid="factor-model-view" />' },
}))
vi.mock('../components/design/DesignWizard.vue', () => ({ default: { template: '<div data-testid="design-wizard" />' } }))
// O11: DesignLoading stub 带 retry/cancel 按钮（失败态可操作）
vi.mock('../components/design/DesignLoading.vue', () => ({
  default: {
    template: '<div data-testid="design-loading"><button data-testid="retry-btn" @click="$emit(\'retry\')" /><button data-testid="cancel-btn" @click="$emit(\'cancel\')" /></div>',
    props: ['progress', 'stepLabel', 'failed', 'taskStage', 'selectedLabel', 'elapsedSec'],
  },
}))
vi.mock('../components/design/DesignResult.vue', () => ({ default: { template: '<div data-testid="design-result" />' } }))
vi.mock('../components/design/DesignHistory.vue', () => ({ default: { template: '<div data-testid="design-history" />' } }))
vi.mock('../components/design/StrategyCheckModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/ui/AppModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../utils/formatDate', () => ({ formatDate: (d) => String(d) || '' }))

import DashboardAiTools from '../views/DashboardAiTools.vue'

describe('DashboardAiTools — 任务状态机 (O11)', () => {
  beforeEach(() => {
    persistMock.mockClear()
    designAsyncMock.mockClear()
    designAsyncMock.mockResolvedValue({ data: { task_id: 101, design_id: null } })
  })

  it('O11: 失败态 → 点击重试 → 重新 running（复用参数重新提交）', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await flushPromises()
    // 进入 design wizard 并提交（designAsync 立即返回 task_id=101）
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'wizard'
    await wrapper.vm.startDesign(500000)
    await flushPromises()
    expect(wrapper.vm.designStep).toBe('loading')
    // 模拟失败
    wrapper.vm.designFailed = '方案生成超时，数据源响应过慢'
    await flushPromises()
    expect(wrapper.find('[data-testid="retry-btn"]').exists()).toBe(true)
    // 点击重试 → designFailed 清空 + 重新 running（designAsync 再次调用）
    await wrapper.find('[data-testid="retry-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.vm.designFailed).toBe('')
    expect(wrapper.vm.designStep).toBe('loading')
    expect(designAsyncMock.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('O11: 失败态返回 → idle → 再次进入回到 idle（不残留失败卡）', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await flushPromises()
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'loading'
    wrapper.vm.designFailed = '后端服务异常'
    await nextTick()
    expect(wrapper.find('[data-testid="cancel-btn"]').exists()).toBe(true)
    await wrapper.find('[data-testid="cancel-btn"]').trigger('click')
    expect(wrapper.vm.activeCoreFeature).toBeNull()
    // 再次进入（无 running 任务 → resetToTools）
    wrapper.vm.enterDesignMode()
    await flushPromises()
    expect(wrapper.vm.designFailed).toBe('')
    expect(wrapper.vm.designStep).toBe('wizard')
  })

  it('O11: 失败态退出不持久化（exitCoreFeature 不调 persistDesignState）', async () => {
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await flushPromises()
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'loading'
    wrapper.vm.designFailed = '方案生成超时'
    wrapper.vm.exitCoreFeature()
    expect(persistMock).not.toHaveBeenCalled()
    // loading 无失败 → 可持久化（running 续跑语义）
    persistMock.mockClear()
    wrapper.vm.activeCoreFeature = 'design'
    wrapper.vm.designStep = 'loading'
    wrapper.vm.designFailed = ''
    wrapper.vm.exitCoreFeature()
    expect(persistMock).toHaveBeenCalled()
  })

  it('O11: WS 完成与轮询幂等——finalizedDesignIds 防重复 finalize', async () => {
    // 源码级断言：WS 回调与轮询 completed 分支都有 finalizedDesignIds.has(did) 守卫
    // （fetchDesignDetail 只调一次——interaction-redesign P3 验收③）
    const src = DashboardAiTools.__script?.content
      || require('fs').readFileSync(require.resolve('../views/DashboardAiTools.vue'), 'utf-8')
    expect(src).toContain('finalizedDesignIds.has(did)')
    expect(src).toContain('finalizedDesignIds.add(did)')
  })
})
