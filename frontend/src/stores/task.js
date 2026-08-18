import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useToastStore } from './toast'
import { logger } from '../utils/logger'

// designState 仍用 localStorage 持久化（导航恢复用），但任务状态走后端 API
const LS_DESIGN_KEY = 'etf_surge_design'

/**
 * Global task store — 后端为唯一数据源，tasks.json 持久化。
 * 前端仅维护内存响应式状态，由 WS /fetchAndMergeTasks 驱动。
 * 无 localStorage 读写，避免双源不同步问题。
 */
export const useTaskStore = defineStore('task', () => {
  /** 任务列表（内存响应式，不写 localStorage） */
  const tasks = ref([])



  // ── 后端 API 装载（分页）────────────────────────────────
  const PAGE_SIZE = 10
  let _fetchPromise = null
  let _pageTotal = 0
  const taskHasMore = ref(false)

  function _normalizeTask(rt) {
    // 后端字段 → 前端 task 格式
    return {
      taskId: String(rt.task_id || rt.id),
      type: rt.task_type || rt.type || 'design',
      status: rt.status || 'pending',
      progress: rt.progress || 0,
      label: rt.label || _defaultLabel(rt.task_type || rt.type),
      designId: rt.result?.design_id || rt.design_id || null,
      // Z27: recordId — design 任务与 design_id 同值；check 任务取 record_id（可关联 strategy-checks/{id}）
      recordId: rt.record_id || (rt.type === 'design' ? (rt.result?.design_id || rt.design_id || null) : null) || null,
      errorMessage: rt.error_message || rt.error || null,
      createdAt: rt.created_at ? new Date(rt.created_at).getTime() : Date.now(),
      completedAt: rt.completed_at || null,
      stage: rt.stage || '',
    }
  }

  function _defaultLabel(type) {
    if (type === 'check') return '策略检查与分析'
    if (type === 'report') return '市场研判报告'
    return '智能组合设计'
  }

  async function fetchAndMergeTasks() {
    if (_fetchPromise) return _fetchPromise
    _fetchPromise = (async () => {
      try {
        const { portfolioApi } = await import('../api')
        const res = await portfolioApi.listTasks(PAGE_SIZE, 0)
        const remoteTasks = res.data || []
        tasks.value = remoteTasks.map(_normalizeTask)
        taskHasMore.value = remoteTasks.length >= PAGE_SIZE
        _pageTotal = remoteTasks.length
      } catch (e) {
        logger.warn('[taskStore] fetch tasks failed:', e)
      }
    })()
    _fetchPromise.finally(() => { _fetchPromise = null })
    return _fetchPromise
  }

  async function loadMoreTasks() {
    const offset = tasks.value.length
    const res = await (await import('../api')).portfolioApi.listTasks(PAGE_SIZE, offset)
    const more = (res.data || []).map(_normalizeTask)
    tasks.value.push(...more)
    taskHasMore.value = more.length >= PAGE_SIZE
    _pageTotal += more.length
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
    return getTask(taskId)
  }

  function updateTask(taskId, changes = {}) {
    const task = getTask(taskId)
    if (!task) return
    Object.assign(task, changes)

    // Side effects on terminal transitions
    const toast = useToastStore()

    // Invoke completion callback for any terminal state
    const hasCb = !!_completionCallbacks[taskId]
    if (changes.status === 'completed' || changes.status === 'failed') {
      const cb = _completionCallbacks[taskId]
      if (cb) {
        try { cb({ taskId, ...changes }) } catch (e) { logger.warn('[taskStore] completion callback error:', e) }
        delete _completionCallbacks[taskId]
      }
    }

    // factor-and-strategy-check-review 问题2 R2: 组件已注册完成回调（自管 toast 与
    // 结果页状态）时，全局「已完成」toast 不再立即弹——旧行为 WS completed 先到只
    // 触发全局 toast、组件仍停留 loading（「先提示完成再停留加载」）。
    if (changes.status === 'completed' && !hasCb) {
      const msg = task.type === 'check'
        ? '策略检查已完成'
        : '组合方案已生成，点击查看'
      toast.show(msg, 'success')
    } else if (changes.status === 'completed_with_errors') {
      toast.show('方案已完成但报告生成异常', 'warning')
    } else if (changes.status === 'failed') {
      const msg = task.type === 'check'
        ? '策略检查失败'
        : '组合方案生成失败'
      toast.show(msg, 'error')
    }
  }

  function removeTask(taskId) {
    tasks.value = tasks.value.filter((t) => t.taskId !== taskId)
  }

  function clearCompleted(delay = 5000) {
    setTimeout(() => {
      tasks.value = tasks.value.filter(
        (t) => t.status !== 'completed' && t.status !== 'failed'
      )
    }, delay)
  }

  function clearAllCompleted() {
    // 立即清除所有已完成/失败任务，用于手动「清除历史」
    tasks.value = tasks.value.filter(t => t.status !== 'completed' && t.status !== 'failed')
  }

  // ── Computed: active task detection ────────────────────────────
  const hasRunningTask = computed(() => tasks.value.some(t => t.status === 'running'))
  const activeTaskId = computed(() => {
    const running = tasks.value.find(t => t.status === 'running')
    return running ? running.taskId : null
  })

  // ── UX2: 设计面板状态持久化（仍用 localStorage，导航恢复用）───
  const _lsLoad = () => {
    try { const r = localStorage.getItem(LS_DESIGN_KEY); return r ? JSON.parse(r) : null }
    catch { return null }
  }
  const designState = ref(_lsLoad())

  function persistDesignState(state) {
    designState.value = state ? { ...state, _savedAt: Date.now() } : null
    try { localStorage.setItem(LS_DESIGN_KEY, JSON.stringify(designState.value)) }
    catch { /* quota */ }
  }

  function getDesignState() {
    return designState.value
  }

  function clearDesignState() {
    designState.value = null
    try { localStorage.removeItem(LS_DESIGN_KEY) } catch { /* ignore */ }
  }

  return {
    tasks, getTask, addTask, updateTask, removeTask,
    fetchAndMergeTasks, loadMoreTasks, taskHasMore,
    clearCompleted, clearAllCompleted,
    registerTaskCompletion,
    hasRunningTask, activeTaskId,
    designState, persistDesignState, getDesignState, clearDesignState,
  }
})
