import { ref, onUnmounted } from 'vue'
import { portfolioApi } from '../api'

/**
 * Reusable task polling composable.
 * @param {string} taskId - Task ID to poll
 * @param {object} options - Options
 * @param {number} options.interval - Poll interval in ms (default 5000)
 * @param {number} options.timeout - Timeout in ms (default 180000)
 * @param {number} options.maxErrors - Max consecutive errors before abort (default 5)
 * @param {function} options.onCompleted - Completion callback
 * @param {function} options.onFailed - Failure callback
 * @param {function} options.onProgress - Progress update callback
 */
export function useTaskPolling(taskId, options = {}) {
  const {
    interval = 5000,
    timeout = 180000,
    maxErrors = 5,
    onCompleted = null,
    onFailed = null,
    onProgress = null,
  } = options

  const isRunning = ref(false)
  const progress = ref(0)
  const stage = ref('')
  const status = ref('pending')
  const error = ref(null)

  let timer = null
  let timeoutTimer = null
  let pollCount = 0
  let consecutiveErrors = 0

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    if (timeoutTimer) {
      clearTimeout(timeoutTimer)
      timeoutTimer = null
    }
    isRunning.value = false
  }

  async function poll() {
    if (!taskId) return
    try {
      const res = await portfolioApi.getTask(taskId)
      const task = res.data
      consecutiveErrors = 0
      pollCount++

      progress.value = task.progress || 0
      stage.value = task.stage || ''
      status.value = task.status || 'pending'

      if (onProgress) onProgress(task)

      if (task.status === 'completed') {
        stop()
        if (onCompleted) onCompleted(task)
      } else if (task.status === 'failed') {
        stop()
        error.value = task.error_message || task.error || 'Task failed'
        if (onFailed) onFailed(task)
      }
    } catch (e) {
      consecutiveErrors++
      if (consecutiveErrors >= maxErrors) {
        stop()
        error.value = 'Backend unreachable, task may be lost'
        status.value = 'failed'
        if (onFailed) onFailed({ error_message: error.value })
      }
    }
  }

  function start() {
    if (isRunning.value) return
    if (!taskId) return
    isRunning.value = true
    poll()
    timer = setInterval(poll, interval)

    // Timeout safeguard
    if (timeout > 0) {
      timeoutTimer = setTimeout(() => {
        stop()
        error.value = 'Task timed out'
        status.value = 'failed'
        if (onFailed) onFailed({ error_message: 'Task timed out' })
      }, timeout)
    }
  }

  // Auto-cleanup on component unmount
  onUnmounted(() => stop())

  return { start, stop, progress, stage, status, error, isRunning }
}
