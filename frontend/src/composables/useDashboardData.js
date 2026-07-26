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

  const pnlTotal = computed(() => pnlItems.value.reduce((sum, item) => sum + (item.daily_pnl || 0), 0))
  const pnlTotalAmount = computed(() => pnlItems.value.reduce((sum, item) => sum + (item.target_amount || 0), 0))

  const pnlWeightedChange = computed(() => {
    const total = pnlTotalAmount.value
    if (!total) return 0
    return pnlItems.value.reduce((sum, item) => sum + ((item.daily_pnl || 0) / total) * 100, 0)
  })

  const cashPctOn = computed(() => {
    const total = capitalOn.value
    const used = allocationOn.value.total_amount || 0
    return total > 0 ? Math.max(0, (total - used) / total) : 0
  })
  const cashOn = computed(() => capitalOn.value - (allocationOn.value.total_amount || 0))

  const cashPctOff = computed(() => {
    const total = capitalOff.value
    const used = allocationOff.value.total_amount || 0
    return total > 0 ? Math.max(0, (total - used) / total) : 0
  })
  const cashOff = computed(() => capitalOff.value - (allocationOff.value.total_amount || 0))

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
    pnlHistory, pnlHistoryLoading, loading,
    globalIndices,
    totalAll, pnlOn, pnlOff, pnlItems, pnlTotal, pnlTotalAmount, pnlWeightedChange,
    cashPctOn, cashOn, cashPctOff, cashOff,
    fetchGlobalIndices, fetchAllocations, fetchPnl, fetchPnlHistory, refreshAll
  }
}
