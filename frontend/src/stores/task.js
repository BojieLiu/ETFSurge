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

  // 定时清除超时任务（30s 检查一次，避免 localStorage 中的 running 任务永久显示）
  let _staleTimer = null
  function _startStaleCheck() {
    if (_staleTimer) return
    _staleTimer = setInterval(() => {
      let changed = false
      const now = Date.now()
      tasks.value.forEach(t => {
        if (t.status === 'running' && now - (t.createdAt || 0) > 300000) {
          t.status = 'failed'
          t.errorMessage = '生成超时，请重新尝试'
          changed = true
        }
      })
      if (changed) _save(LS_KEYS.tasks, tasks.value)
    }, 30000)
  }
  _startStaleCheck()

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
    const st = designState.value
    if (!st) return null
    // 如果保存超过 30 分钟，视为过期，不恢复旧设计
    if (st._savedAt && Date.now() - st._savedAt > 30 * 60 * 1000) {
      clearDesignState()
      return null
    }
    return st
  }

  function clearDesignState() {
    designState.value = null
    _save(LS_KEYS.design, null)
  }

  // ── Backend sync: fetch task list from API and merge with local ──
  let _fetchPromise = null

  async function fetchAndMergeTasks() {
    if (_fetchPromise) return _fetchPromise
    _fetchPromise = (async () => {
      const { portfolioApi } = await import('../api')
      try {
        const res = await portfolioApi.listTasks(20, 0)
        const remoteTasks = Array.isArray(res.data) ? res.data : []
        const localIds = new Set(tasks.value.map(t => t.taskId))
        let changed = false
        for (const rt of remoteTasks) {
          if (!localIds.has(rt.task_id)) {
            tasks.value.push({
              taskId: rt.task_id,
              type: rt.type || 'design',
              status: rt.status || 'running',
              progress: rt.progress || 0,
              label: rt.type === 'check' ? '策略检查与分析' : '智能组合设计',
              designId: rt.result?.design_id || null,
              createdAt: new Date(rt.created_at || Date.now()).getTime(),
            })
            changed = true
          }
        }
        if (changed) _save(LS_KEYS.tasks, tasks.value)
      } catch {
        // Silently ignore — localStorage tasks are still available
      }
    })()
    try {
      await _fetchPromise
    } finally {
      _fetchPromise = null
    }
  }

  return {
    tasks, getTask, addTask, updateTask, removeTask, clearCompleted, _loadTasks,
    registerTaskCompletion, fetchAndMergeTasks,
    hasRunningTask, activeTaskId,
    designState, persistDesignState, getDesignState, clearDesignState,
  }
})
