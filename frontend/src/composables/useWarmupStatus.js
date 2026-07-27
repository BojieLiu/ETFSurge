/**
 * useWarmupStatus — 轮询后端预热状态用于 Dashboard 加载指示器
 *
 * 页面挂载时每 5s 轮询 /api/v1/system/warmup，
 * 直到 all_done === true 或超时。
 *
 * 返回：
 *   warmup       — 各预热任务状态对象 {market_cache, global_indices, etf_cache}
 *   allDone      — boolean，所有预热是否完成
 *   isWarmingUp  — boolean，预热正在进行中
 *   timedOut     — boolean，超过 120s 仍为完成
 *   phaseTitle   — string，当前阶段的友好文字
 *   phaseDesc    — string，当前阶段的详细描述
 *   elapsed      — number，已过秒数
 *   startPolling — () => void，启动轮询
 *   stopPolling  — () => void，停止轮询
 */
import { ref, computed, onUnmounted } from 'vue'
import { systemApi } from '../api'
import logger from '../utils/logger'

const POLL_INTERVAL_MS = 5000
const MAX_POLL_COUNT = 24  // 120s 超时

export function useWarmupStatus() {
  const warmup = ref(null)
  const allDone = ref(false)
  const timedOut = ref(false)
  const elapsed = ref(0)
  let pollTimer = null
  let pollCount = 0

  // Phase title derived from warmup state
  const phaseTitle = computed(() => {
    if (timedOut.value) return '数据加载超时'
    if (allDone.value) return '数据加载完成'
    if (!warmup.value) return '正在获取数据...'

    const w = warmup.value
    // Check each task in priority order
    if (w.market_cache && !w.market_cache.done) return '正在加载行情数据...'
    if (w.global_indices && !w.global_indices.done) return '正在加载全球指数...'
    if (w.etf_cache && !w.etf_cache.done) return '正在扫描 ETF...'

    // All done in backend but frontend still fetching
    return '正在加载组合数据...'
  })

  const phaseDesc = computed(() => {
    if (timedOut.value) return '后端初始化超时，请检查服务状态后刷新页面'
    if (allDone.value) return '后端缓存已就绪'
    if (!warmup.value) return '正在连接后端服务...'

    const w = warmup.value
    const parts = []
    for (const [key, val] of Object.entries(w)) {
      const label = val.label || key
      if (val.done) {
        parts.push(`${label} ${val.success ? '✓' : '✗'}`)
      } else {
        parts.push(`${label} ...`)
      }
    }
    return parts.join(' | ')
  })

  const isWarmingUp = computed(() => {
    return !allDone.value && !timedOut.value
  })

  async function pollOnce() {
    try {
      const res = await systemApi.warmup()
      const data = res.data
      warmup.value = data.warmup
      elapsed.value = data.elapsed_seconds || 0
      if (data.all_done) {
        allDone.value = true
        stopPolling()
        logger.info('[warmup] Backend warmup complete in', data.elapsed_seconds, 's')
      }
    } catch (e) {
      logger.warn('[warmup] Poll failed:', e.message)
      // If we got no response but already have state, keep trying
      if (!warmup.value) {
        // First failure — warmup stays null, phase shows "connecting"
      }
    }
    pollCount++
    if (pollCount >= MAX_POLL_COUNT && !allDone.value) {
      timedOut.value = true
      stopPolling()
      logger.warn('[warmup] Timed out after', MAX_POLL_COUNT * POLL_INTERVAL_MS / 1000, 's')
    }
  }

  function startPolling() {
    if (pollTimer) return
    logger.info('[warmup] Starting polling, interval=' + POLL_INTERVAL_MS + 'ms')
    // Fire immediately, then every POLL_INTERVAL_MS
    pollOnce()
    pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // Auto-cleanup on component unmount
  onUnmounted(() => {
    stopPolling()
  })

  return {
    warmup,
    allDone,
    isWarmingUp,
    timedOut,
    phaseTitle,
    phaseDesc,
    elapsed,
    startPolling,
    stopPolling,
  }
}
