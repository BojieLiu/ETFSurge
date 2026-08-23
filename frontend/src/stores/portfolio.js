import { defineStore } from 'pinia'
import { ref } from 'vue'
import { portfolioApi } from '../api'

export const usePortfolioStore = defineStore('portfolio', () => {
  const etfs = ref([])
  const onExchange = ref([])
  const offExchange = ref([])
  const capitalOn = ref(500000)
  const capitalOff = ref(500000)
  // round35 FE2 (R127): 首拉 loading 标志——消除 PortfolioManager 初载闪
  // 「还没有 ETF」空态（此前 v-if="!currentEtfs.length" 在首拉期间即渲染空态）。
  const initialized = ref(false)
  const loading = ref(false)

  // round35 FE1 (§14.4-R123): fetchDailyPnl/fetchPnLHistory/fetchDriftCheck/
  // exportPortfolio/importPortfolio 五个 action 与 strategyResult/pnlHistory/
  // driftCheck 死状态已删——生产代码零调用者：同域端点实际由
  // PortfolioManager.vue 本地函数与 useDashboardData.js composable 直调，
  // strategyResult 从未被写入（DashboardAiTools 用组件本地 ref）。

  async function fetchEtfs(type) {
    loading.value = true
    try {
      const res = await portfolioApi.list(type)
      if (type) {
        if (type === 'on_exchange') onExchange.value = res.data
        else offExchange.value = res.data
      } else {
        etfs.value = res.data
      }
      return res.data
    } finally {
      loading.value = false
      initialized.value = true
    }
  }

  async function addEtf(data) {
    await portfolioApi.add(data)
    await fetchEtfs(data.portfolio_type)
    await fetchEtfs()
  }

  async function updateEtf(symbol, data) {
    const res = await portfolioApi.update(symbol, data)
    await Promise.all([fetchEtfs(), fetchEtfs('on_exchange'), fetchEtfs('off_exchange')])
    // round19 P3-③: adjust 语义响应（realized_pnl/trade/新 avg_cost）返回给调用方
    return res.data || res
  }

  async function removeEtf(symbol) {
    await portfolioApi.remove(symbol)
    await Promise.all([fetchEtfs(), fetchEtfs('on_exchange'), fetchEtfs('off_exchange')])
  }

  return {
    etfs, onExchange, offExchange,
    capitalOn, capitalOff,
    loading, initialized,
    fetchEtfs, addEtf, updateEtf, removeEtf,
  }
})
