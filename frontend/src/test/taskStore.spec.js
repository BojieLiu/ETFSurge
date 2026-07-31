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
})
