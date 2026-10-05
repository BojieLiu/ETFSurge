/**
 * TDD tests for task store — hasRunningTask / activeTaskId.
 *
 * Covers:
 *   - addTask creates a running task
 *   - hasRunningTask returns true when a task is running
 *   - hasRunningTask returns false when no task exists
 *   - activeTaskId returns the first running task's taskId
 *   - activeTaskId returns null when no task is running
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTaskStore } from '../stores/task'

// Mock the api module for fetchAndMergeTasks tests
const mockListTasks = vi.fn()
vi.mock('../api', () => ({
  portfolioApi: { listTasks: mockListTasks },
}))

describe('taskStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // Clear localStorage between tests
    localStorage.clear()
  })

  it('should have no running task initially', () => {
    const store = useTaskStore()
    expect(store.hasRunningTask).toBe(false)
    expect(store.activeTaskId).toBeNull()
  })

  it('should have running task after addTask', () => {
    const store = useTaskStore()
    store.addTask('test-task-001')
    expect(store.hasRunningTask).toBe(true)
    expect(store.activeTaskId).toBe('test-task-001')
  })

  it('should track the first running task taskId', () => {
    const store = useTaskStore()
    store.addTask('task-1')
    store.addTask('task-2')
    // activeTaskId returns the FIRST running task
    expect(store.activeTaskId).toBe('task-1')
  })

  it('should update hasRunningTask when task completes', () => {
    const store = useTaskStore()
    store.addTask('test-task-002')
    expect(store.hasRunningTask).toBe(true)

    store.updateTask('test-task-002', { status: 'completed' })
    expect(store.hasRunningTask).toBe(false)
    expect(store.activeTaskId).toBeNull()
  })

  it('should return activeTaskId when task fails', () => {
    const store = useTaskStore()
    store.addTask('test-task-003')
    expect(store.hasRunningTask).toBe(true)

    store.updateTask('test-task-003', { status: 'failed' })
    expect(store.hasRunningTask).toBe(false)
    expect(store.activeTaskId).toBeNull()
  })

  // ── Z27: recordId 映射（§7.1） ────────────────────────────────

  it('should map record_id to recordId for check tasks', async () => {
    mockListTasks.mockResolvedValue({
      data: [{
        task_id: 7,
        type: 'check',
        status: 'completed',
        progress: 100,
        record_id: 97,
        created_at: '2026-07-31T10:00:00Z',
      }],
    })
    const store = useTaskStore()
    await store.fetchAndMergeTasks()
    const t = store.getTask('7')
    expect(t).not.toBeNull()
    expect(t.recordId).toBe(97)
    expect(t.type).toBe('check')
  })

  it('should map result.design_id to recordId for design tasks', async () => {
    mockListTasks.mockResolvedValue({
      data: [{
        task_id: 5,
        type: 'design',
        status: 'completed',
        progress: 100,
        result: { design_id: 222 },
        created_at: '2026-07-31T10:00:00Z',
      }],
    })
    const store = useTaskStore()
    await store.fetchAndMergeTasks()
    const t = store.getTask('5')
    expect(t).not.toBeNull()
    expect(t.recordId).toBe(222)
    expect(t.designId).toBe(222)
  })

  it('should map fallback rt.design_id to recordId', async () => {
    mockListTasks.mockResolvedValue({
      data: [{
        task_id: 6,
        type: 'design',
        status: 'completed',
        design_id: 333,
        created_at: '2026-07-31T10:00:00Z',
      }],
    })
    const store = useTaskStore()
    await store.fetchAndMergeTasks()
    const t = store.getTask('6')
    expect(t.recordId).toBe(333)
  })

  // ── taskId 类型一致性（string/number 混用导致重复行 + 状态永不更新）──────
  //
  // 现场（2026-10-05 tasks 162）：_normalizeTask 把 taskId 字符串化，
  // 而 POST /design-async 的响应与 WS 推送的 task_id 是**数字**。getTask 用
  // === 比较 → fetchAndMergeTasks（WS 重连时整表替换为字符串键）之后，
  // 数字键的 WS 消息永远匹配不上 → updateTask 静默 no-op、WS 分支再 addTask
  // 造出第二个条目。残留的 running 条目会被 AiDesign 合成为幻影行，
  // 于是「一次设计」在任务列表出现两条。
  describe('taskId type coercion', () => {
    it('should find a task added with a number id by its string id', () => {
      const store = useTaskStore()
      store.addTask(162, '智能组合设计', 'design')
      expect(store.getTask('162')).not.toBeNull()
    })

    it('should find a string-keyed task by its number id (WS path)', async () => {
      // 模拟 WS 重连：fetchAndMergeTasks 整表替换为字符串键
      mockListTasks.mockResolvedValue({
        data: [{
          task_id: 162, type: 'design', status: 'running', progress: 80,
          created_at: '2026-10-05T04:53:22Z',
        }],
      })
      const store = useTaskStore()
      await store.fetchAndMergeTasks()
      expect(store.getTask(162)).not.toBeNull()
    })

    it('should apply a WS update sent with a number id', async () => {
      mockListTasks.mockResolvedValue({
        data: [{
          task_id: 162, type: 'design', status: 'quick_ready', progress: 80,
          created_at: '2026-10-05T04:53:22Z',
        }],
      })
      const store = useTaskStore()
      await store.fetchAndMergeTasks()
      store.updateTask(162, { status: 'completed', progress: 100 })
      // 负向：字符串键条目未更新 → 任务永远 running → 前端合成幻影重复行
      expect(store.getTask('162').status).toBe('completed')
      expect(store.hasRunningTask).toBe(false)
    })

    it('should not create a twin entry when WS addTask uses a number id', async () => {
      mockListTasks.mockResolvedValue({
        data: [{
          task_id: 162, type: 'design', status: 'running', progress: 0,
          created_at: '2026-10-05T04:53:22Z',
        }],
      })
      const store = useTaskStore()
      await store.fetchAndMergeTasks()
      // WS 的 if (!getTask(id)) addTask(id) 分支——字符串键已存在，不得再加一条
      store.addTask(162, '智能组合设计', 'design')
      expect(store.tasks.filter(t => String(t.taskId) === '162')).toHaveLength(1)
    })

    it('should remove a task by number id', () => {
      const store = useTaskStore()
      store.addTask(162, '智能组合设计', 'design')
      store.removeTask(162)
      expect(store.getTask('162')).toBeNull()
    })

    it('should store taskId as a string when added with a number', () => {
      const store = useTaskStore()
      store.addTask(162, '智能组合设计', 'design')
      expect(store.tasks[0].taskId).toBe('162')
    })

    it('should fire the completion callback registered with a number id', () => {
      const store = useTaskStore()
      const cb = vi.fn()
      store.addTask(162, '智能组合设计', 'design')
      store.registerTaskCompletion(162, cb)
      store.updateTask('162', { status: 'completed' })
      expect(cb).toHaveBeenCalledTimes(1)
    })
  })
})
