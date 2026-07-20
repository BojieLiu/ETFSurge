import { ref, watch, computed } from 'vue'
import { fetchJson } from '../utils/fetchJson'

export function useChartView(symbol, assetType) {
  const period = ref('daily')
  const chartMode = ref('kline')
  const chartData = ref(null)
  const indicatorData = ref(null)
  const signal = ref(null)
  const loading = ref(false)
  const showMA5 = ref(true)
  const showMA10 = ref(true)
  const showMA20 = ref(true)
  const showMA60 = ref(false)
  const showBoll = ref(false)
  const showMACD = ref(true)

  const periodOptions = [
    { value: '15m', label: '15分钟' },
    { value: '30m', label: '30分钟' },
    { value: '1h', label: '1小时' },
    { value: '4h', label: '4小时' },
    { value: 'daily', label: '日线' },
    { value: 'weekly', label: '周线' },
    { value: 'monthly', label: '月线' }
  ]

  const signalText = computed(() => ({ buy: '买入', sell: '卖出', hold: '持有' })[signal.value?.signal] || '')
  const signalIcon = computed(() => ({ buy: '⬆️', sell: '⬇️', hold: '➡️' })[signal.value?.signal] || '')

  async function fetchAll() {
    if (!symbol.value) return
    loading.value = true
    try {
      const sym = symbol.value
      const at = assetType?.value || 'A'
      const [chartRes, indRes, sigRes] = await Promise.all([
        fetchJson(`/api/v1/market/chart/${sym}?asset_type=${at}&period=${period.value}`),
        fetchJson(`/api/v1/market/indicators/${sym}?asset_type=${at}`),
        fetchJson(`/api/v1/market/signal/${sym}?asset_type=${at}`)
      ])
      chartData.value = chartRes.data || chartRes
      indicatorData.value = indRes.data || indRes
      signal.value = sigRes.data || sigRes
    } catch {
      chartData.value = null
      indicatorData.value = null
      signal.value = null
    }
    loading.value = false
  }

  // Watch symbol changes
  watch([symbol, assetType], () => {
    if (symbol.value) fetchAll()
  })

  return { period, chartMode, chartData, indicatorData, signal, loading,
    showMA5, showMA10, showMA20, showMA60, showBoll, showMACD,
    periodOptions, signalText, signalIcon, fetchAll }
}
