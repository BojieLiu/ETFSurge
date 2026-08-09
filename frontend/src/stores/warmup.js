/**
 * warmup store (P2-2) — 后端预热状态轮询单例
 *
 * 模块级单例：所有消费者（App.vue / Dashboard.vue）共享一个轮询定时器，
 * 避免每个组件实例各自轮询 /api/v1/system/warmup（P2-2 前 useWarmupStatus
 * 每次调用都独立创建 ref + setInterval）。
 *
 * 生命周期：首个消费者 startPolling() 启动；all_done 或 120s 超时自动停止。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { systemApi } from '../api'
import logger from '../utils/logger'

const POLL_INTERVAL_MS = 5000
const MAX_POLL_COUNT = 24 // 120s 超时

export const useWarmupStore = defineStore('warmup', () => {
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

  const isWarmingUp = computed(() => !allDone.value && !timedOut.value)

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
})
