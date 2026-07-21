import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useToastStore } from './toast'

const LS_KEYS = { tasks: 'etf_surge_tasks', design: 'etf_surge_design' }

function _load(key, fallback) {
  try { const r = localStorage.getItem(key); return r ? JSON.parse(r) : fallback }
  catch { return fallback }
}
function _save(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)) } catch { /* quota */ }
}

/**
 * Global task store persisted to localStorage (survives F5 / tab close).
 * Driven by back-end /ws/task-notifications WebSocket broadcast.
 */
export const useTaskStore = defineStore('task', () => {
  const tasks = ref(_loadTasks())

  function _loadTasks() {
    const raw = _load(LS_KEYS.tasks, [])
    const now = Date.now()
    raw.forEach(t => {
      if (t.status === 'running' && now - (t.createdAt || 0) > 300000) {
        t.status = 'failed'
        t.errorMessage = '生成超时，请重新尝试'
      }
    })
    _save(LS_KEYS.tasks, raw)
    return raw
  }

  function getTask(taskId) {
    return tasks.value.find((t) => t.taskId === taskId) || null
  }

  // Internal callback registry for WS-driven completion notifications
  const _completionCallbacks = {}

  function registerTaskCompletion(taskId, callback) {
    if (typeof callback === 'function') {
      _completionCallbacks[taskId] = callback
    }
  }

  function addTask(taskId, label = '智能组合设计', taskType = 'design') {
    const existing = getTask(taskId)
    if (existing) {
      existing.status = 'running'
      existing.progress = existing.progress || 0
      existing.label = label
      _save(LS_KEYS.tasks, tasks.value)
      return existing
    }
    tasks.value.push({
      taskId,
      type: taskType,
      status: 'running',
      progress: 0,
      label,
      designId: null,
      createdAt: Date.now(),
    })
    _save(LS_KEYS.tasks, tasks.value)
    return getTask(taskId)
  }

  function updateTask(taskId, changes = {}) {
    const task = getTask(taskId)
    if (!task) return
    Object.assign(task, changes)
    _save(LS_KEYS.tasks, tasks.value)

    // Side effects on terminal transitions
    const toast = useToastStore()

    // Invoke completion callback for any terminal state
    if (changes.status === 'completed' || changes.status === 'failed') {
      const cb = _completionCallbacks[taskId]
      if (cb) {
        try { cb({ taskId, ...changes }) } catch (e) { console.warn('[taskStore] completion callback error:', e) }
        delete _completionCallbacks[taskId]
      }
    }

    if (changes.status === 'completed') {
      const msg = task.type === 'check'
        ? '策略检查已完成'
        : '组合方案已生成，点击查看'
      toast.show(msg, 'success')
      clearCompleted()
    } else if (changes.status === 'failed') {
      const msg = task.type === 'check'
        ? '策略检查失败'
        : '组合方案生成失败'
      toast.show(msg, 'error')
      clearCompleted()
    }
    _save(LS_KEYS.tasks, tasks.value)
  }

  function removeTask(taskId) {
    tasks.value = tasks.value.filter((t) => t.taskId !== taskId)
    _save(LS_KEYS.tasks, tasks.value)
  }

  function clearCompleted(delay = 30000) {
    setTimeout(() => {
      tasks.value = tasks.value.filter(
        (t) => t.status !== 'completed' && t.status !== 'failed'
      )
      _save(LS_KEYS.tasks, tasks.value)
    }, delay)
  }

  // ── Computed: active task detection ────────────────────────────
  const hasRunningTask = computed(() => tasks.value.some(t => t.status === 'running'))
  const activeTaskId = computed(() => {
    const running = tasks.value.find(t => t.status === 'running')
    return running ? running.taskId : null
  })

  // ── UX2: 设计面板状态持久化 ──────────────────────────────────
  // 当用户导航离开设计面板时保存状态，返回时恢复
  // UX2: 设计面板状态，同样持久化到 localStorage
  const designState = ref(_load(LS_KEYS.design, null))

  function persistDesignState(state) {
    designState.value = state ? { ...state, _savedAt: Date.now() } : null
    _save(LS_KEYS.design, designState.value)
  }

  function getDesignState() {
    return designState.value
  }

  function clearDesignState() {
    designState.value = null
    _save(LS_KEYS.design, null)
  }

  return {
    tasks, getTask, addTask, updateTask, removeTask, clearCompleted, _loadTasks,
    registerTaskCompletion,
    hasRunningTask, activeTaskId,
    designState, persistDesignState, getDesignState, clearDesignState,
  }
})
