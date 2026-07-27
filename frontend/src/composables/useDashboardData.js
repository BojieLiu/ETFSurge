import { ref, computed } from 'vue'
import { portfolioApi, marketApi } from '../api'
import logger from '../utils/logger'
import { useToastStore } from '../stores/toast'

export function useDashboardData(capitalOn, capitalOff, activeTab) {
  const { show: toast } = useToastStore()

  // States
  const allocationOn = ref({ allocations: [], total_amount: 0 })
  const allocationOff = ref({ allocations: [], total_amount: 0 })
  const pnlOnData = ref({ items: [] })
  const pnlOffData = ref({ items: [] })
  const pnlHistory = ref(null)
  const pnlHistoryLoading = ref(false)
  const globalIndices = ref({})

  // Computed – derived values
  const totalAll = computed(() => (allocationOn.value.total_amount || 0) + (allocationOff.value.total_amount || 0))
  const pnlOn = computed(() => pnlOnData.value.total_pnl || 0)
  const pnlOff = computed(() => pnlOffData.value.total_pnl || 0)

  const pnlItems = computed(() => {
    if (activeTab.value === 'on_exchange') return pnlOnData.value.items || []
    if (activeTab.value === 'off_exchange') return pnlOffData.value.items || []
    return [...(pnlOnData.value.items || []), ...(pnlOffData.value.items || [])]
  })

  // PnL computed — use backend aggregate fields directly (Sprint 1 P0)
  const pnlTotal = computed(() => {
    if (activeTab.value === 'on_exchange') return pnlOnData.value.total_pnl || 0
    if (activeTab.value === 'off_exchange') return pnlOffData.value.total_pnl || 0
    return (pnlOnData.value.total_pnl || 0) + (pnlOffData.value.total_pnl || 0)
  })

  const pnlTotalAmount = computed(() => {
    if (activeTab.value === 'on_exchange') return pnlOnData.value.total_amount || 0
    if (activeTab.value === 'off_exchange') return pnlOffData.value.total_amount || 0
    return (pnlOnData.value.total_amount || 0) + (pnlOffData.value.total_amount || 0)
  })

  const pnlWeightedChange = computed(() => {
    if (activeTab.value === 'on_exchange') return pnlOnData.value.weighted_change_pct || 0
    if (activeTab.value === 'off_exchange') return pnlOffData.value.weighted_change_pct || 0
    const totalAmount = (pnlOnData.value.total_amount || 0) + (pnlOffData.value.total_amount || 0)
    const totalPnl = (pnlOnData.value.total_pnl || 0) + (pnlOffData.value.total_pnl || 0)
    return totalAmount > 0 ? (totalPnl / totalAmount) * 100 : 0
  })

  // Cash metrics — use backend cash_weight/cash_amount directly (Sprint 1 P0)
  const cashPctOn = computed(() => allocationOn.value.cash_weight || 0)
  const cashOn = computed(() => allocationOn.value.cash_amount || 0)
  const cashPctOff = computed(() => allocationOff.value.cash_weight || 0)
  const cashOff = computed(() => allocationOff.value.cash_amount || 0)

  // fetchAttempted: true after first API call completes (success or failure).
  // This lets the dashboard distinguish "loading" from "empty portfolio".
  const fetchAttempted = ref(false)

  // Loading state: true when both allocation arrays are empty
  const loading = computed(() => allocationOn.value.allocations.length === 0 && allocationOff.value.allocations.length === 0)

  // ECharts options
  // Methods – data fetching
  async function fetchGlobalIndices() {
    try {
      const res = await marketApi.indicesGlobal()
      globalIndices.value = res.data?.indices || res.data || {}
    } catch (e) {
      logger.warn('[Dashboard] fetchGlobalIndices failed:', e)
      globalIndices.value = {}
    } finally {
      fetchAttempted.value = true
    }
  }

  async function fetchAllocations() {
    try {
      const [onRes, offRes] = await Promise.all([
        portfolioApi.getAllocation('on_exchange', capitalOn.value),
        portfolioApi.getAllocation('off_exchange', capitalOff.value)
      ])
      allocationOn.value = onRes.data || { allocations: [], total_amount: 0 }
      allocationOff.value = offRes.data || { allocations: [], total_amount: 0 }
    } catch (e) {
      toast('获取分配数据失败', 'error')
    } finally {
      fetchAttempted.value = true
    }
  }

  async function fetchPnl() {
    try {
      const [onRes, offRes] = await Promise.all([
        portfolioApi.getPnl('on_exchange', capitalOn.value),
        portfolioApi.getPnl('off_exchange', capitalOff.value)
      ])
      pnlOnData.value = onRes.data || { items: [] }
      pnlOffData.value = offRes.data || { items: [] }
    } catch (e) {
      toast('获取盈亏数据失败', 'error')
    } finally {
      fetchAttempted.value = true
    }
  }

  async function fetchPnlHistory(type = 'combined') {
    const portfolioType = type === 'combined' ? null : type
    // 根据类型传递对应的投资额，用于成本数据缺失时的估算
    const capital = type === 'combined'
      ? (capitalOn.value + capitalOff.value)
      : type === 'on_exchange' ? capitalOn.value : capitalOff.value
    pnlHistoryLoading.value = true
    try {
      const res = await portfolioApi.getPnLHistory(portfolioType, '3m', capital)
      pnlHistory.value = res.data
    } catch (e) {
      toast('获取累计盈亏历史失败', 'error')
    } finally {
      pnlHistoryLoading.value = false
    }
  }

  async function refreshAll() {
    await Promise.all([fetchGlobalIndices(), fetchAllocations(), fetchPnl()])
  }

  return {
    allocationOn, allocationOff, pnlOnData, pnlOffData,
    pnlHistory, pnlHistoryLoading, loading, fetchAttempted,
    globalIndices,
    totalAll, pnlOn, pnlOff, pnlItems, pnlTotal, pnlTotalAmount, pnlWeightedChange,
    cashPctOn, cashOn, cashPctOff, cashOff,
    fetchGlobalIndices, fetchAllocations, fetchPnl, fetchPnlHistory, refreshAll
  }
}
