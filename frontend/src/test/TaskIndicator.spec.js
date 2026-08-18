/**
 * TDD tests for TaskIndicator navigation (Z27 §7.3).
 *
 * Covers:
 *   - check task completed + recordId → click navigates to /portfolio-analysis
 *   - design task completed + designId → click navigates to '/' with designId query
 *   - completed_with_errors design task with designId is clickable
 *   - quick_ready / completed_with_errors status text rendering
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import TaskIndicator from '../components/TaskIndicator.vue'

function makeRouter() {
  const routes = [
    { path: '/', name: 'dashboard', component: { template: '<div />' } },
    { path: '/portfolio-analysis', name: 'portfolio-analysis', component: { template: '<div />' } },
  ]
  return createRouter({ history: createMemoryHistory(), routes })
}

// 等 router.push 异步导航落定（isReady 在首次导航后立即 resolve，不等待后续 push）
async function flushNav() {
  await new Promise((r) => setTimeout(r, 0))
  await new Promise((r) => setTimeout(r, 0))
}

function addTask(store, task) {
  store.tasks.push({
    taskId: task.taskId,
    type: task.type || 'design',
    status: task.status || 'running',
    progress: task.progress || 0,
    label: task.label || '智能组合设计',
    designId: task.designId || null,
    recordId: task.recordId || null,
    createdAt: task.createdAt || Date.now(),
  })
}

describe('TaskIndicator (Z27 §7.3)', () => {
  let router

  beforeEach(async () => {
    setActivePinia(createPinia())
    router = makeRouter()
    await router.push('/')
    await router.isReady()
  })

  it('navigates to /portfolio-analysis when completed check task has recordId', async () => {
    const { useTaskStore } = await import('../stores/task')
    const store = useTaskStore()
    addTask(store, { taskId: '9', type: 'check', status: 'completed', recordId: 97 })

    const wrapper = mount(TaskIndicator, { global: { plugins: [router] } })
    // 打开面板
    await wrapper.find('.task-bell').trigger('click')
    const item = wrapper.find('.task-item')
    expect(item.classes()).toContain('is-clickable')

    await item.trigger('click')
    await flushNav()
    expect(router.currentRoute.value.path).toBe('/portfolio-analysis')
  })

  it('navigates to dashboard with designId query for design task', async () => {
    const { useTaskStore } = await import('../stores/task')
    const store = useTaskStore()
    addTask(store, { taskId: '5', type: 'design', status: 'completed', designId: 222 })

    const wrapper = mount(TaskIndicator, { global: { plugins: [router] } })
    await wrapper.find('.task-bell').trigger('click')
    const item = wrapper.find('.task-item')
    expect(item.classes()).toContain('is-clickable')

    await item.trigger('click')
    await flushNav()
    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.query.designId).toBe('222')
  })

  it('completed_with_errors design task with designId is clickable', async () => {
    const { useTaskStore } = await import('../stores/task')
    const store = useTaskStore()
    addTask(store, {
      taskId: '8', type: 'design', status: 'completed_with_errors',
      designId: 333, recordId: 333,
    })

    const wrapper = mount(TaskIndicator, { global: { plugins: [router] } })
    await wrapper.find('.task-bell').trigger('click')
    expect(wrapper.find('.task-item').classes()).toContain('is-clickable')

    await wrapper.find('.task-item').trigger('click')
    await flushNav()
    expect(router.currentRoute.value.query.designId).toBe('333')
  })

  it('renders Chinese status text for quick_ready and completed_with_errors', async () => {
    const { useTaskStore } = await import('../stores/task')
    const store = useTaskStore()
    addTask(store, { taskId: '1', type: 'design', status: 'quick_ready', progress: 60 })
    addTask(store, { taskId: '2', type: 'design', status: 'completed_with_errors', progress: 100 })

    const wrapper = mount(TaskIndicator, { global: { plugins: [router] } })
    await wrapper.find('.task-bell').trigger('click')

    const texts = wrapper.findAll('.task-status').map((el) => el.text())
    expect(texts).toContain('方案已就绪')
    expect(texts).toContain('已完成（报告异常）')
  })

  it('running check task without recordId is NOT clickable', async () => {
    const { useTaskStore } = await import('../stores/task')
    const store = useTaskStore()
    addTask(store, { taskId: '3', type: 'check', status: 'running', recordId: null })

    const wrapper = mount(TaskIndicator, { global: { plugins: [router] } })
    await wrapper.find('.task-bell').trigger('click')
    expect(wrapper.find('.task-item').classes()).not.toContain('is-clickable')
  })
})
