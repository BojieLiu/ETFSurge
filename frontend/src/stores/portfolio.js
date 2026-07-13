import { defineStore } from 'pinia'
import { ref } from 'vue'
import { portfolioApi } from '../api'

export const usePortfolioStore = defineStore('portfolio', () => {
  const etfs = ref([])
  const onExchange = ref([])
  const offExchange = ref([])
  const strategyResult = ref(null)

  async function fetchEtfs(type) {
    const res = await portfolioApi.list(type)
    if (type) {
      if (type === 'on_exchange') onExchange.value = res.data
      else offExchange.value = res.data
    } else {
      etfs.value = res.data
    }
    return res.data
  }

  async function addEtf(data) {
    await portfolioApi.add(data)
    await fetchEtfs(data.portfolio_type)
    await fetchEtfs()
  }

  async function updateEtf(symbol, data) {
    await portfolioApi.update(symbol, data)
    await Promise.all([fetchEtfs(), fetchEtfs('on_exchange'), fetchEtfs('off_exchange')])
  }

  async function removeEtf(symbol) {
    await portfolioApi.remove(symbol)
    await Promise.all([fetchEtfs(), fetchEtfs('on_exchange'), fetchEtfs('off_exchange')])
  }

  async function fetchDailyPnl(capital, type) {
    const res = await portfolioApi.dailyPnl(capital, type)
    return res.data
  }

  async function runStrategyCheck(capital) {
    const res = await portfolioApi.strategyCheck(capital)
    strategyResult.value = res.data
    return res.data
  }

  return {
    etfs, onExchange, offExchange, strategyResult,
    fetchEtfs, addEtf, updateEtf, removeEtf,
    fetchDailyPnl, runStrategyCheck,
  }
})
