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
  const pieOptionOn = computed(() => ({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'middle', itemWidth: 12, itemHeight: 12 },
    series: [{
      name: '分配',
      type: 'pie',
      radius: ['40%', '70%'],
      avoidLabelOverlap: false,
      label: { show: false, position: 'center' },
      emphasis: { label: { show: true, fontSize: '18', fontWeight: 'bold' } },
      labelLine: { show: false },
      data: (allocationOn.value.allocations || []).map(a => ({
        value: a.target_amount,
        name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
      }))
    }],
    color: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#eab308']
  }))

  const pieOptionOff = computed(() => ({
    ...pieOptionOn.value,
    series: [{
      ...pieOptionOn.value.series[0],
      data: (allocationOff.value.allocations || []).map(a => ({
        value: a.target_amount,
        name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
      }))
    }]
  }))

  const pnlBarOption = computed(() => ({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: pnlItems.value.map(i => i.short_name || i.name), axisLabel: { interval: 0, rotate: 30 } },
    yAxis: { type: 'value', name: '盈亏 (元)' },
    series: [{
      name: '当日盈亏',
      type: 'bar',
      data: pnlItems.value.map(i => i.daily_pnl || 0),
      itemStyle: {
        color: (params) => params.value >= 0 ? '#ef4444' : '#22c55e'
      },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
    }]
  }))

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
    pnlHistoryLoading.value = true
    try {
      const res = await portfolioApi.getPnLHistory(portfolioType, '3m')
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
    pieOptionOn, pieOptionOff, pnlBarOption,
    fetchGlobalIndices, fetchAllocations, fetchPnl, fetchPnlHistory, refreshAll
  }
}
