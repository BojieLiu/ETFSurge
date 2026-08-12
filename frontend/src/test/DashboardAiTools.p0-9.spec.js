/**
 * P0-9 (round16 3.10): 任务列表双显示 + 策略检查运行中不可见修复。
 *
 * 验收:
 * ① running check 任务也合入历史列表（旧只 design）→ 不丢失；
 * ② 同一 running 任务（task_id 已存在于 timeline items）不重复合成 → 无双显示；
 * ③ running 条目 _type 反映真实任务类型。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const timelineMock = vi.fn()
const getTaskMock = vi.fn()

vi.mock('../api', () => ({
  portfolioApi: {
    getTimeline: (...a) => timelineMock(...a),
    getTask: (...a) => getTaskMock(...a),
    listDesigns: vi.fn().mockResolvedValue({ data: [] }),
    listStrategyChecks: vi.fn().mockResolvedValue({ data: [] }),
  },
}))

const runningTasks = []

vi.mock('../stores/task', () => ({
  useTaskStore: () => ({
    tasks: runningTasks,
    getTask: getTaskMock,
    fetchAndMergeTasks: vi.fn(),
    hasRunningTask: false,
    activeTaskId: null,
    getDesignState: vi.fn(() => null),
    clearDesignState: vi.fn(),
  }),
}))
vi.mock('../stores/toast', () => ({
  useToastStore: () => ({ show: vi.fn(), success: vi.fn(), error: vi.fn(), dismiss: vi.fn() }),
}))
vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({ fetchEtfs: vi.fn(), etfs: [], capitalOn: 500000, capitalOff: 0 }),
}))
vi.mock('../components/FactorModelView.vue', () => ({
  default: { name: 'FactorModelView', template: '<div />' },
}))
vi.mock('../components/design/DesignWizard.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignLoading.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/DesignHistory.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/design/StrategyCheckResult.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../components/ui/AppModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../utils/formatDate', () => ({ formatDate: (d) => String(d) || '' }))

import DashboardAiTools from '../views/DashboardAiTools.vue'

function flush() {
  return new Promise((r) => setTimeout(r, 0))
}

describe('DashboardAiTools — P0-9 任务列表双显示', () => {
  beforeEach(() => {
    timelineMock.mockReset()
    getTaskMock.mockReset()
    runningTasks.length = 0
  })

  it('running check 任务合入历史列表（_type=check）', async () => {
    runningTasks.push({ taskId: '388', type: 'check', status: 'running', createdAt: Date.now() })
    timelineMock.mockResolvedValue({ data: { items: [], total: 0 } })
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await wrapper.vm.loadHistoryList()
    await flush()
    const list = wrapper.vm.designHistoryList
    const running = list.filter((i) => i.status === 'running')
    expect(running.length).toBe(1)
    expect(running[0]._type).toBe('check')
    expect(running[0].task_id).toBe('388')
  })

  it('running 任务已存在于 timeline（task_id 相同）→ 不重复合成（无双显示）', async () => {
    timelineMock.mockResolvedValue({
      data: { items: [{ id: 506, _type: 'design', status: 'running', task_id: '506', created_at: '2026-08-11' }], total: 1 },
    })
    // taskStore 同一 running 任务（taskId='506'）
    runningTasks.push({ taskId: '506', type: 'design', status: 'running', createdAt: Date.now() })
    const wrapper = mount(DashboardAiTools, { props: { active: false } })
    await wrapper.vm.loadHistoryList()
    await flush()
    const list = wrapper.vm.designHistoryList
    const runningDesigns = list.filter((i) => i._type === 'design' && i.status === 'running')
    expect(runningDesigns.length).toBe(1, `同一 running 任务不得双显示: ${JSON.stringify(list)}`)
  })
})
