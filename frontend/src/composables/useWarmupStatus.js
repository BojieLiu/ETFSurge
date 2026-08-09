/**
 * useWarmupStatus — 后端预热状态（P2-2 起为 Pinia store 单例薄封装）
 *
 * 保留原 composable 签名（warmup/allDone/isWarmingUp/timedOut/phaseTitle/
 * phaseDesc/elapsed/startPolling/stopPolling），实际状态与轮询生命周期
 * 收敛到 stores/warmup.js 单例——多组件共享一个轮询定时器。
 *
 * 注意：Pinia store 在组件外使用时需先经 pinia 实例激活；本封装假定在
 * setup() 内调用（App.vue / Dashboard.vue 均满足）。
 */
import { storeToRefs } from 'pinia'
import { useWarmupStore } from '../stores/warmup'

export function useWarmupStatus() {
  const store = useWarmupStore()
  const {
    warmup,
    allDone,
    isWarmingUp,
    timedOut,
    phaseTitle,
    phaseDesc,
    elapsed,
  } = storeToRefs(store)

  return {
    warmup,
    allDone,
    isWarmingUp,
    timedOut,
    phaseTitle,
    phaseDesc,
    elapsed,
    startPolling: store.startPolling,
    stopPolling: store.stopPolling,
  }
}
