import { defineStore } from 'pinia'
import { ref } from 'vue'
import { portfolioApi } from '../api'

export const usePortfolioStore = defineStore('portfolio', () => {
  const etfs = ref([])
  const onExchange = ref([])
  const offExchange = ref([])
  const strategyResult = ref(null)
  const pnlHistory = ref(null)
  const driftCheck = ref(null)
  const capitalOn = ref(500000)
  const capitalOff = ref(500000)

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

  async function fetchPnLHistory(type, period = 'all') {
    const res = await portfolioApi.getPnLHistory(type, period)
    pnlHistory.value = res.data
    return res.data
  }

  async function fetchDriftCheck(type) {
    const res = await portfolioApi.getDriftCheck(type)
    driftCheck.value = res.data
    return res.data
  }

  async function exportPortfolio(type, format = 'csv') {
    const res = await portfolioApi.export(type, format)
    return res
  }

  async function importPortfolio(file, type, mode = 'merge', skipInvalid = true) {
    const res = await portfolioApi.import(file, type, mode, skipInvalid)
    if (res.data) {
      await Promise.all([fetchEtfs(), fetchEtfs('on_exchange'), fetchEtfs('off_exchange')])
    }
    return res.data
  }

  return {
    etfs, onExchange, offExchange, strategyResult,
    pnlHistory, driftCheck,
    capitalOn, capitalOff,
    fetchEtfs, addEtf, updateEtf, removeEtf,
    fetchDailyPnl, fetchPnLHistory, fetchDriftCheck,
    exportPortfolio, importPortfolio,
  }
})
