import { ref, computed } from 'vue'
import { portfolioApi } from '../api'
import logger from '../utils/logger'
import { useToastStore } from '../stores/toast'
import { useMarketStore } from '../stores/market' // Round34 B4/R110

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

  // round34-B7 批复①: daily-pnl 拉取失败标志——组合摘要条错误态依据（诚实降级，禁 ¥0 冒充）
  const pnlError = ref(false)

  // Loading state: true when both allocation arrays are empty
  const loading = computed(() => allocationOn.value.allocations.length === 0 && allocationOff.value.allocations.length === 0)

  // ECharts options
  // Methods – data fetching
  // Round34 B4 / R110: 经 marketStore 单飞通道取全球指数——
  // Dashboard 多面板/未来 gauge 消费方共享一次请求（30s TTL）
  const marketStore = useMarketStore()

  async function fetchGlobalIndices() {
    try {
      const data = await marketStore.fetchIndicesGlobal()
      globalIndices.value = data?.indices || data || {}
    } catch (e) {
      logger.warn('[Dashboard] fetchGlobalIndices failed:', e)
      globalIndices.value = {}
    }
    // R52: fetchAttempted 由 refreshAll 统一置位（移除各 fetch 的 finally 置位）
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
    }
    // R52: fetchAttempted 由 refreshAll 统一置位
  }

  async function fetchPnl() {
    pnlError.value = false
    try {
      const [onRes, offRes] = await Promise.all([
        portfolioApi.dailyPnl(capitalOn.value, 'on_exchange'),
        portfolioApi.dailyPnl(capitalOff.value, 'off_exchange')
      ])
      pnlOnData.value = onRes.data || { items: [] }
      pnlOffData.value = offRes.data || { items: [] }
    } catch (e) {
      pnlError.value = true
      toast('获取盈亏数据失败', 'error')
    }
    // R52: fetchAttempted 由 refreshAll 统一置位
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

  // R52: fetchAttempted 只在所有数据源完成后置位——覆盖 refreshAll 与 onMounted 两条路径
  async function refreshAll() {
    try {
      await Promise.all([fetchGlobalIndices(), fetchAllocations(), fetchPnl()])
    } finally {
      fetchAttempted.value = true
    }
  }

  return {
    allocationOn, allocationOff, pnlOnData, pnlOffData,
    pnlHistory, pnlHistoryLoading, loading, fetchAttempted, pnlError,
    globalIndices,
    totalAll, pnlOn, pnlOff, pnlItems, pnlTotal, pnlTotalAmount, pnlWeightedChange,
    cashPctOn, cashOn, cashPctOff, cashOff,
    fetchGlobalIndices, fetchAllocations, fetchPnl, fetchPnlHistory, refreshAll
  }
}
