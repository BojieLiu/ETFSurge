import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useToastStore } from './toast'

/**
 * Global task store for long-running async jobs (e.g. intelligent portfolio design).
 * Driven by the backend /ws/task-notifications WebSocket broadcast.
 */
export const useTaskStore = defineStore('task', () => {
  const tasks = ref([])

  function getTask(taskId) {
    return tasks.value.find((t) => t.taskId === taskId) || null
  }

  function addTask(taskId, label = '智能组合设计') {
    const existing = getTask(taskId)
    if (existing) {
      existing.status = 'running'
      existing.progress = existing.progress || 0
      existing.label = label
      return existing
    }
    tasks.value.push({
      taskId,
      type: 'design',
      status: 'running',
      progress: 0,
      label,
      designId: null,
      createdAt: Date.now(),
    })
    return getTask(taskId)
  }

  function updateTask(taskId, changes = {}) {
    const task = getTask(taskId)
    if (!task) return
    Object.assign(task, changes)

    // Side effects on terminal transitions
    const toast = useToastStore()
    if (changes.status === 'completed') {
      toast.show('组合方案已生成，点击查看', 'success')
      clearCompleted()
    } else if (changes.status === 'failed') {
      toast.show('组合方案生成失败', 'error')
      clearCompleted()
    }
  }

  function removeTask(taskId) {
    tasks.value = tasks.value.filter((t) => t.taskId !== taskId)
  }

  function clearCompleted(delay = 30000) {
    setTimeout(() => {
      tasks.value = tasks.value.filter(
        (t) => t.status !== 'completed' && t.status !== 'failed'
      )
    }, delay)
  }

  // ── UX2: 设计面板状态持久化 ──────────────────────────────────
  // 当用户导航离开设计面板时保存状态，返回时恢复
  const designState = ref(null)  // { designStep, designResult, loadingProgress, selectedPlan, ... }

  function persistDesignState(state) {
    designState.value = state ? { ...state, _savedAt: Date.now() } : null
  }

  function getDesignState() {
    return designState.value
  }

  function clearDesignState() {
    designState.value = null
  }

  return {
    tasks, getTask, addTask, updateTask, removeTask, clearCompleted,
    designState, persistDesignState, getDesignState, clearDesignState,
  }
})
