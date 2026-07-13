import { defineStore } from 'pinia'
import { ref } from 'vue'
import { marketApi } from '../api'

export const useMarketStore = defineStore('market', () => {
  const realtimeData = ref([])
  const indicators = ref(null)
  const signal = ref(null)
  const history = ref([])

  async function fetchRealtime() {
    const res = await marketApi.realtimePortfolio()
    realtimeData.value = res.data
  }

  async function fetchIndicators(symbol, assetType = 'A') {
    const res = await marketApi.indicators(symbol, assetType)
    indicators.value = res.data
  }

  async function fetchSignal(symbol, assetType = 'A') {
    const res = await marketApi.signal(symbol, assetType)
    signal.value = res.data
  }

  async function fetchHistory(symbol, assetType = 'A', period = 'daily') {
    const res = await marketApi.history(symbol, assetType, period)
    history.value = res.data
  }

  function getQuote(symbol) {
    return realtimeData.value.find(item => item.symbol === symbol)
  }

  return { realtimeData, indicators, signal, history, fetchRealtime, fetchIndicators, fetchSignal, fetchHistory, getQuote }
})
