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
})
