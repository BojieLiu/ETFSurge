import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { useDashboardData } from '../composables/useDashboardData'

// ── Mock API modules ───────────────────────────────────────
vi.mock('../api', () => ({
  marketApi: {
    indicesGlobal: vi.fn(),
  },
  portfolioApi: {
    getAllocation: vi.fn(),
    dailyPnl: vi.fn(),
    getPnLHistory: vi.fn(),
  },
}))

import { marketApi, portfolioApi } from '../api'

// ── Mock toast store ───────────────────────────────────────
vi.mock('../stores/toast', () => ({
  useToastStore: () => ({
    show: vi.fn(),
  }),
}))

// ── Mock logger ────────────────────────────────────────────
vi.mock('../utils/logger', () => ({
  default: {
    warn: vi.fn(),
    debug: vi.fn(),
    error: vi.fn(),
  },
}))

describe('useDashboardData', () => {
  let capitalOn, capitalOff, activeTab

  beforeEach(() => {
    vi.clearAllMocks()
    // Round34 B4/R110: useDashboardData 内部经 useMarketStore 单飞取指数 → 需活跃 Pinia
    setActivePinia(createPinia())
    capitalOn = ref(100000)
    capitalOff = ref(50000)
    activeTab = ref('combined')

    // Default mock responses
    marketApi.indicesGlobal.mockResolvedValue({
      data: { indices: { '000001': '2800' } },
    })

    portfolioApi.getAllocation.mockResolvedValue({
      data: {
        allocations: [
          { symbol: '510300', target_weight: 0.3, target_amount: 30000 },
          { symbol: '511090', target_weight: 0.1, target_amount: 10000 },
        ],
        total_amount: 40000,
      },
    })

    portfolioApi.dailyPnl.mockResolvedValue({
      data: {
        items: [
          { symbol: '510300', daily_pnl: 300, target_amount: 30000 },
          { symbol: '511090', daily_pnl: -50, target_amount: 10000 },
        ],
        total_pnl: 250,
      },
    })

    portfolioApi.getPnLHistory.mockResolvedValue({
      data: {
        labels: ['2026-07-20', '2026-07-21', '2026-07-22'],
        datasets: [{ data: [1000, 1200, 1100] }],
      },
    })
  })

  // ── Initial state ──────────────────────────────────────
  it('starts with empty allocations and zero totals', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.allocationOn.value.allocations).toEqual([])
    expect(dash.allocationOff.value.allocations).toEqual([])
    expect(dash.totalAll.value).toBe(0)
    expect(dash.loading.value).toBe(true)
    expect(dash.pnlHistoryLoading.value).toBe(false)
  })

  it('starts with empty globalIndices', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.globalIndices.value).toEqual({})
  })

  // ── Computed: loading ──────────────────────────────────
  it('loading is true when both allocation arrays are empty', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.loading.value).toBe(true)
  })

  it('loading is false when at least one allocation has items', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.allocationOn.value = { allocations: [{ symbol: 'A' }], total_amount: 100 }
    expect(dash.loading.value).toBe(false)
  })

  // ── Computed: cash ─────────────────────────────────────
  it('cashOn reads cash_amount from allocation response', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.allocationOn.value = { allocations: [], total_amount: 40000, cash_amount: 60000 }
    expect(dash.cashOn.value).toBe(60000)
  })

  it('cashPctOn reads cash_weight from allocation response', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.allocationOn.value = { allocations: [], total_amount: 30000, cash_weight: 0.7 }
    expect(dash.cashPctOn.value).toBeCloseTo(0.7)
  })

  it('cashPctOn returns 0 when capitalOn is 0', () => {
    capitalOn.value = 0
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.cashPctOn.value).toBe(0)
  })

  it('cashOff reads cash_amount from allocation response', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.allocationOff.value = { allocations: [], total_amount: 20000, cash_amount: 30000 }
    expect(dash.cashOff.value).toBe(30000)
  })

  it('cashPctOff reads cash_weight from allocation response', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.allocationOff.value = { allocations: [], total_amount: 10000, cash_weight: 0.8 }
    expect(dash.cashPctOff.value).toBeCloseTo(0.8)
  })

  // ── Computed: totalAll ─────────────────────────────────
  it('totalAll sums on and off exchange totals', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.allocationOn.value = { allocations: [], total_amount: 40000 }
    dash.allocationOff.value = { allocations: [], total_amount: 20000 }
    expect(dash.totalAll.value).toBe(60000)
  })

  // ── Computed: pnl ──────────────────────────────────────
  it('pnlOn = total_pnl from on-exchange data', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOnData.value = { items: [], total_pnl: 250 }
    expect(dash.pnlOn.value).toBe(250)
  })

  it('pnlOff = total_pnl from off-exchange data', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOffData.value = { items: [], total_pnl: 100 }
    expect(dash.pnlOff.value).toBe(100)
  })

  it('pnlItems returns both exchanges in combined mode', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOnData.value = { items: [{ symbol: 'A' }], total_pnl: 100 }
    dash.pnlOffData.value = { items: [{ symbol: 'B' }], total_pnl: 50 }
    expect(dash.pnlItems.value).toHaveLength(2)
  })

  it('pnlItems filters by active tab when on_exchange', () => {
    activeTab.value = 'on_exchange'
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOnData.value = { items: [{ symbol: 'A' }], total_pnl: 100 }
    dash.pnlOffData.value = { items: [{ symbol: 'B' }], total_pnl: 50 }
    expect(dash.pnlItems.value).toHaveLength(1)
    expect(dash.pnlItems.value[0].symbol).toBe('A')
  })

  it('pnlItems filters by active tab when off_exchange', () => {
    activeTab.value = 'off_exchange'
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOnData.value = { items: [{ symbol: 'A' }], total_pnl: 100 }
    dash.pnlOffData.value = { items: [{ symbol: 'B' }], total_pnl: 50 }
    expect(dash.pnlItems.value).toHaveLength(1)
    expect(dash.pnlItems.value[0].symbol).toBe('B')
  })

  it('pnlTotal reads total_pnl from backend response (combined)', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOnData.value = {
      items: [
        { symbol: 'A', daily_pnl: 100, target_amount: 1000 },
        { symbol: 'B', daily_pnl: 50, target_amount: 500 },
      ],
      total_pnl: 150,
    }
    expect(dash.pnlTotal.value).toBe(150)
  })

  it('pnlTotalAmount reads total_amount from backend response (combined)', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOnData.value = {
      items: [
        { symbol: 'A', daily_pnl: 100, target_amount: 1000 },
        { symbol: 'B', daily_pnl: 50, target_amount: 500 },
      ],
      total_amount: 1500,
    }
    expect(dash.pnlTotalAmount.value).toBe(1500)
  })

  it('pnlWeightedChange uses backend weighted_change_pct or combined formula', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    dash.pnlOnData.value = {
      items: [
        { symbol: 'A', daily_pnl: 100, target_amount: 1000 },
        { symbol: 'B', daily_pnl: 50, target_amount: 500 },
      ],
      total_pnl: 150,
      total_amount: 1500,
    }
    // combined: (totalPnl / totalAmount) * 100 = (150/1500)*100 = 10%
    expect(dash.pnlWeightedChange.value).toBeCloseTo(10, 0.01)
  })

  it('pnlWeightedChange returns 0 when total amount is 0', () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.pnlWeightedChange.value).toBe(0)
  })

  // ── fetchGlobalIndices ──────────────────────────────────
  it('fetchGlobalIndices calls marketApi.indicesGlobal and sets data', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchGlobalIndices()
    expect(marketApi.indicesGlobal).toHaveBeenCalledTimes(1)
    expect(dash.globalIndices.value).toEqual({ '000001': '2800' })
  })

  it('fetchGlobalIndices handles error gracefully', async () => {
    marketApi.indicesGlobal.mockRejectedValue(new Error('Network error'))
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchGlobalIndices()
    expect(dash.globalIndices.value).toEqual({})
  })

  it('R110 验收：同一加载窗口内多消费方并发调用，indices/global 请求数 ==1（基线 ×3）', async () => {
    // Round34 B4/R110 头条口径——多个面板/composable 实例共享 marketStore
    // 单飞通道（30s TTL），进行中请求复用同一 Promise
    const dashA = useDashboardData(capitalOn, capitalOff, activeTab)
    const dashB = useDashboardData(capitalOn, capitalOff, activeTab)
    await Promise.all([
      dashA.fetchGlobalIndices(),
      dashB.fetchGlobalIndices(),
      dashA.fetchGlobalIndices(),
    ])
    expect(marketApi.indicesGlobal).toHaveBeenCalledTimes(1)

    // TTL 内的新实例（模拟路由回切）同样命中缓存，不触发第二次网络
    const dashC = useDashboardData(capitalOn, capitalOff, activeTab)
    await dashC.fetchGlobalIndices()
    expect(marketApi.indicesGlobal).toHaveBeenCalledTimes(1)
    expect(dashC.globalIndices.value).toEqual({ '000001': '2800' })
  })

  // ── fetchAllocations ────────────────────────────────────
  it('fetchAllocations calls getAllocation for both types', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchAllocations()
    expect(portfolioApi.getAllocation).toHaveBeenCalledTimes(2)
    expect(portfolioApi.getAllocation).toHaveBeenCalledWith('on_exchange', 100000)
    expect(portfolioApi.getAllocation).toHaveBeenCalledWith('off_exchange', 50000)
  })

  it('fetchAllocations sets both allocation values from response', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchAllocations()
    expect(dash.allocationOn.value.total_amount).toBe(40000)
    expect(dash.allocationOn.value.allocations).toHaveLength(2)
    expect(dash.allocationOff.value.total_amount).toBe(40000)
  })

  it('fetchAllocations handles error gracefully, allocations stay empty', async () => {
    portfolioApi.getAllocation.mockRejectedValue(new Error('API error'))
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchAllocations()
    expect(dash.allocationOn.value.allocations).toEqual([])
  })

  // ── fetchPnl ────────────────────────────────────────────
  it('fetchPnl calls dailyPnl for both types', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchPnl()
    expect(portfolioApi.dailyPnl).toHaveBeenCalledTimes(2)
  })

  it('fetchPnl sets pnl data from responses', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchPnl()
    expect(dash.pnlOnData.value.total_pnl).toBe(250)
    expect(dash.pnlOnData.value.items).toHaveLength(2)
    expect(dash.pnlOffData.value.total_pnl).toBe(250)
  })

  // ── fetchPnlHistory ─────────────────────────────────────
  it('fetchPnlHistory calls getPnLHistory with correct params', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchPnlHistory('combined')
    expect(portfolioApi.getPnLHistory).toHaveBeenCalledWith(null, '3m', 150000)
  })

  it('fetchPnlHistory passes type for non-combined', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchPnlHistory('on_exchange')
    expect(portfolioApi.getPnLHistory).toHaveBeenCalledWith('on_exchange', '3m', 100000)
  })

  it('fetchPnlHistory sets pnlHistory data', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchPnlHistory()
    expect(dash.pnlHistory.value).toBeTruthy()
    expect(dash.pnlHistory.value.labels).toHaveLength(3)
  })

  it('fetchPnlHistory manages loading state', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    const promise = dash.fetchPnlHistory()
    expect(dash.pnlHistoryLoading.value).toBe(true)
    await promise
    expect(dash.pnlHistoryLoading.value).toBe(false)
  })

  it('fetchPnlHistory handles error and stops loading', async () => {
    portfolioApi.getPnLHistory.mockRejectedValue(new Error('API error'))
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.fetchPnlHistory()
    expect(dash.pnlHistory.value).toBeNull()
    expect(dash.pnlHistoryLoading.value).toBe(false)
  })

  // ── refreshAll ──────────────────────────────────────────
  it('refreshAll calls all three data fetchers', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.refreshAll()
    expect(marketApi.indicesGlobal).toHaveBeenCalledTimes(1)
    expect(portfolioApi.getAllocation).toHaveBeenCalledTimes(2)
    expect(portfolioApi.dailyPnl).toHaveBeenCalledTimes(2)
  })

  it('R52: fetchAttempted set only after refreshAll completes (not per-fetch)', async () => {
    // 单个 fetch 的 finally 不再置位——只有 refreshAll 全部完成后才置位
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.fetchAttempted.value).toBe(false)
    await dash.fetchGlobalIndices()
    expect(dash.fetchAttempted.value).toBe(false)
    await dash.fetchAllocations()
    expect(dash.fetchAttempted.value).toBe(false)
    await dash.refreshAll()
    expect(dash.fetchAttempted.value).toBe(true)
  })

  it('R52: refreshAll sets fetchAttempted even when a fetch fails', async () => {
    marketApi.indicesGlobal.mockRejectedValue(new Error('boom'))
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    await dash.refreshAll()  // 不抛异常（fetch 内部捕获）
    expect(dash.fetchAttempted.value).toBe(true)
  })

  // ── Computed reactivity ────────────────────────────────
  it('loading recomputes when allocation data changes', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.loading.value).toBe(true)
    dash.allocationOn.value = { allocations: [{ symbol: 'A' }], total_amount: 100 }
    await nextTick()
    expect(dash.loading.value).toBe(false)
  })

  it('totalAll recomputes when allocation totals change', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.totalAll.value).toBe(0)
    dash.allocationOn.value = { allocations: [], total_amount: 50000 }
    dash.allocationOff.value = { allocations: [], total_amount: 30000 }
    await nextTick()
    expect(dash.totalAll.value).toBe(80000)
  })

  it('cashOn recomputes when allocationOn cash_amount changes', async () => {
    const dash = useDashboardData(capitalOn, capitalOff, activeTab)
    expect(dash.cashOn.value).toBe(0)
    dash.allocationOn.value = { allocations: [], total_amount: 40000, cash_amount: 60000 }
    await nextTick()
    expect(dash.cashOn.value).toBe(60000)
  })
})
