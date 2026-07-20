<template>
  <div class="dashboard">
    <GlobalIndicesStrip />


    <!-- Portfolio Type Tabs -->
    <div class="tabs" role="tablist" aria-label="组合类型">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        :class="['tab', { 'tab--active': activeTab === tab.value }]"
        @click="activeTab = tab.value"
        role="tab"
        :aria-selected="activeTab === tab.value"
        :aria-controls="`panel-${tab.value}`"
        :id="`tab-${tab.value}`"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Capital Input Bar -->
    <section class="card capital-bar">
      <div class="capital-inputs">
        <label v-if="activeTab === 'on_exchange'" class="input-group">
          <span class="input-label">场内仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOn"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            aria-label="场内仓位金额"
          />
        </label>
        <label v-else-if="activeTab === 'off_exchange'" class="input-group">
          <span class="input-label">场外仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOff"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            aria-label="场外仓位金额"
          />
        </label>
        <label v-else class="input-group dual">
          <span class="input-label">场内仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOn"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            size="sm"
            aria-label="场内仓位金额"
          />
          <span class="input-label">场外仓位</span>
          <AppInput
            type="number"
            v-model.number="capitalOff"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            size="sm"
            aria-label="场外仓位金额"
          />
        </label>
      </div>
      <div class="capital-actions">
        <AppButton variant="secondary" @click="refreshAll" :loading="loading">
          <span class="btn-icon" aria-hidden="true">↻</span>
          刷新
        </AppButton>
      </div>
    </section>

    <!-- Summary Cards -->
    <div class="summary-grid">
      <article class="card summary-card" v-if="activeTab === 'combined'">
        <div class="summary-icon" aria-hidden="true">💰</div>
        <div class="summary-content">
          <p class="summary-label">总仓位</p>
          <p class="summary-value" :class="loading ? 'skeleton' : ''" aria-live="polite">
            <Skeleton v-if="loading" type="text" width="120" />
            <span v-else>¥{{ formatNum(totalAll) }}</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab !== 'off_exchange'">
        <div class="summary-icon" :class="pnlOn >= 0 ? 'positive' : 'negative'" aria-hidden="true">
          {{ pnlOn >= 0 ? '📈' : '📉' }}
        </div>
        <div class="summary-content">
          <p class="summary-label">场内当日盈亏</p>
          <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOn >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
            <Skeleton v-if="loading" type="text" width="120" />
            <span v-else>¥{{ formatNum(pnlOn) }}</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab !== 'on_exchange'">
        <div class="summary-icon" :class="pnlOff >= 0 ? 'positive' : 'negative'" aria-hidden="true">
          {{ pnlOff >= 0 ? '📈' : '📉' }}
        </div>
        <div class="summary-content">
          <p class="summary-label">场外当日盈亏</p>
          <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOff >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
            <Skeleton v-if="loading" type="text" width="120" />
            <span v-else>¥{{ formatNum(pnlOff) }}</span>
          </p>
        </div>
      </article>

      <!-- Cumulative P&L Summary Cards -->
      <article class="card summary-card" v-if="activeTab !== 'off_exchange' && pnlHistory?.summary">
        <div class="summary-icon positive" aria-hidden="true">📊</div>
        <div class="summary-content">
          <p class="summary-label">场内累计盈亏</p>
          <p class="summary-value text-up" aria-live="polite">
            ¥{{ formatNum(pnlHistory.holdings.find(h => h.portfolio_type === 'on_exchange')?.cumulative_pnl || 0) }}
            <span class="pnl-pct">({{ (pnlHistory.holdings.find(h => h.portfolio_type === 'on_exchange')?.cumulative_pnl_pct || 0).toFixed(2) }}%)</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab !== 'on_exchange' && pnlHistory?.summary">
        <div class="summary-icon positive" aria-hidden="true">📊</div>
        <div class="summary-content">
          <p class="summary-label">场外累计盈亏</p>
          <p class="summary-value text-up" aria-live="polite">
            ¥{{ formatNum(pnlHistory.holdings.find(h => h.portfolio_type === 'off_exchange')?.cumulative_pnl || 0) }}
            <span class="pnl-pct">({{ (pnlHistory.holdings.find(h => h.portfolio_type === 'off_exchange')?.cumulative_pnl_pct || 0).toFixed(2) }}%)</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab === 'combined' && pnlHistory?.summary">
        <div class="summary-icon positive" aria-hidden="true">📊</div>
        <div class="summary-content">
          <p class="summary-label">总累计盈亏</p>
          <p class="summary-value text-up" aria-live="polite">
            ¥{{ formatNum(pnlHistory.summary.total_cumulative_pnl) }}
            <span class="pnl-pct">({{ pnlHistory.summary.total_cumulative_pnl_pct.toFixed(2) }}%)</span>
          </p>
        </div>
      </article>
    </div>

    <!-- Loading Skeletons -->
    <div v-if="loading" class="loading-grid" aria-busy="true" aria-label="加载中">
      <div class="card skeleton-card">
        <Skeleton type="chart" height="260" />
      </div>
      <div class="card skeleton-card">
        <Skeleton type="table" rows="6" />
      </div>
    </div>

    <!-- Content -->
    <template v-else>
      <!-- On Exchange Allocation -->
      <div v-if="allocationOn?.allocations?.length && (activeTab === 'on_exchange' || activeTab === 'combined')" class="content-grid">
        <section class="card chart-card" :id="`panel-on_exchange`" role="tabpanel" aria-labelledby="tab-on_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">🥧</span>
              场内分配
            </h2>
            <div class="card-meta">
              <span class="meta-item">
                <span class="meta-label">现金</span>
                <span class="meta-value" :class="cashPctOn >= 0.1 ? 'text-warning' : ''">{{ (cashPctOn * 100).toFixed(1) }}%</span>
              </span>
              <span class="meta-item">
                <span class="meta-value">¥{{ formatNum(cashOn) }}</span>
              </span>
            </div>
          </div>
          <v-chart :option="pieOptionOn" :style="{ height: '280px' }" autoresize />
        </section>

        <section class="card table-card" role="tabpanel" aria-labelledby="tab-on_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">📋</span>
              场内 ETF 目标分配
            </h2>
          </div>
            <div class="table-responsive">
            <table class="data-table alloc-table">
              <thead>
                <tr>
                  <th scope="col">代码</th>
                  <th scope="col">名称</th>
                  <th scope="col">权重</th>
                  <th scope="col" class="amount-header">目标金额</th>
                  <th scope="col" class="amount-header">现价</th>
                  <th scope="col">涨跌幅</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in allocationOn.allocations" :key="item.symbol">
                  <td><code>{{ item.symbol }}</code></td>
                  <td><strong>{{ item.name }}</strong></td>
                  <td><span class="weight-badge">{{ (item.target_weight * 100).toFixed(1) }}%</span></td>
                  <td class="amount-cell">¥{{ formatNum(item.target_amount) }}</td>
                  <td>¥{{ formatPrice(item.current_price) }}</td>
                  <td :class="changeClass(item.change_pct)">
                    <span class="change-value">{{ formatChange(item.change_pct) }}</span>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="footer-row">
                  <td colspan="2"><strong>现金仓位</strong></td>
                  <td><span class="weight-badge">{{ (cashPctOn * 100).toFixed(1) }}%</span></td>
                  <td class="amount-cell"><strong>¥{{ formatNum(cashOn) }}</strong></td>
                  <td colspan="2">—</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      </div>

      <!-- Off Exchange Allocation -->
      <div v-if="allocationOff?.allocations?.length && (activeTab === 'off_exchange' || activeTab === 'combined')" class="content-grid">
        <section class="card chart-card" :id="`panel-off_exchange`" role="tabpanel" aria-labelledby="tab-off_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">🥧</span>
              场外分配
            </h2>
            <div class="card-meta">
              <span class="meta-item">
                <span class="meta-label">现金</span>
                <span class="meta-value" :class="cashPctOff >= 0.1 ? 'text-warning' : ''">{{ (cashPctOff * 100).toFixed(1) }}%</span>
              </span>
              <span class="meta-item">
                <span class="meta-value">¥{{ formatNum(cashOff) }}</span>
              </span>
            </div>
          </div>
          <v-chart :option="pieOptionOff" :style="{ height: '280px' }" autoresize />
        </section>

        <section class="card table-card" role="tabpanel" aria-labelledby="tab-off_exchange">
          <div class="card-header">
            <h2 class="card-title">
              <span class="card-title-icon" aria-hidden="true">📋</span>
              场外 ETF 目标分配
            </h2>
          </div>
          <div class="table-responsive">
            <table class="data-table alloc-table">
              <thead>
                <tr>
                  <th scope="col">代码</th>
                  <th scope="col">名称</th>
                  <th scope="col">权重</th>
                  <th scope="col" class="amount-header">目标金额</th>
                  <th scope="col" class="amount-header">现价</th>
                  <th scope="col">涨跌幅</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in allocationOff.allocations" :key="item.symbol">
                  <td><code>{{ item.symbol }}</code></td>
                  <td><strong>{{ item.name }}</strong></td>
                  <td><span class="weight-badge">{{ (item.target_weight * 100).toFixed(1) }}%</span></td>
                  <td class="amount-cell">¥{{ formatNum(item.target_amount) }}</td>
                  <td>¥{{ formatPrice(item.current_price) }}</td>
                  <td :class="changeClass(item.change_pct)">
                    <span class="change-value">{{ formatChange(item.change_pct) }}</span>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="footer-row">
                  <td colspan="2"><strong>现金仓位</strong></td>
                  <td><span class="weight-badge">{{ (cashPctOff * 100).toFixed(1) }}%</span></td>
                  <td class="amount-cell"><strong>¥{{ formatNum(cashOff) }}</strong></td>
                  <td colspan="2">—</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      </div>

      <!-- Empty State -->
      <div v-if="!allocationOn?.allocations?.length && !allocationOff?.allocations?.length" class="empty-state">
        <div class="empty-icon" aria-hidden="true">📊</div>
        <h3 class="empty-title">暂无组合数据</h3>
        <p class="empty-description">请前往「组合与分析」添加 ETF</p>
        <AppButton variant="primary" @click="$router.push('/portfolio-analysis')">
          前往组合与分析
        </AppButton>
      </div>

      <!-- Daily P&L Details -->
      <section class="card pnl-card" v-if="pnlItems.length">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📊</span>
            当日盈亏明细
          </h2>
          <p class="card-subtitle" v-if="activeTab !== 'combined'">
            当前视图：{{ activeTab === 'on_exchange' ? '场内' : '场外' }} ETF
          </p>
        </div>

        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr>
                <th scope="col">名称</th>
                <th scope="col">类型</th>
                <th scope="col">涨跌幅</th>
                <th scope="col">目标金额</th>
                <th scope="col">当日盈亏</th>
                <th v-if="activeTab === 'off_exchange' || activeTab === 'combined'" scope="col">跟踪指数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in pnlItems" :key="item.symbol">
                <td><strong>{{ item.short_name || item.name }}</strong></td>
                <td><span class="type-badge" :class="item.portfolio_type">{{ item.portfolio_type === 'on_exchange' ? '场内' : '场外' }}</span></td>
                <td :class="changeClass(item.change_pct)">{{ formatChange(item.change_pct) }}</td>
                <td class="amount-cell">¥{{ formatNum(item.target_amount) }}</td>
                <td :class="changeClass(item.daily_pnl)">{{ formatChange(item.daily_pnl, true) }}</td>
                <td v-if="activeTab === 'off_exchange' || activeTab === 'combined'">{{ item.tracked_index || '—' }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="footer-row summary-row">
                <td colspan="2"><strong>合计</strong></td>
                <td :class="pnlWeightedChange >= 0 ? 'text-up' : 'text-down'">{{ formatChange(pnlWeightedChange) }}</td>
                <td class="amount-cell"><strong>¥{{ formatNum(pnlTotalAmount) }}</strong></td>
                <td class="amount-cell" :class="pnlTotal >= 0 ? 'text-up' : 'text-down'"><strong>¥{{ formatNum(pnlTotal) }}</strong></td>
                <td v-if="activeTab === 'off_exchange' || activeTab === 'combined'"></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <!-- P&L Bar Chart -->
      <section class="card chart-card" v-if="pnlItems.length">
        <div class="card-header">
          <h2 class="card-title">
            <span class="card-title-icon" aria-hidden="true">📈</span>
            当日盈亏分布
          </h2>
        </div>
        <v-chart :option="pnlBarOption" :style="{ height: '350px' }" autoresize />
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { usePortfolioStore } from '../stores/portfolio'
import { portfolioApi, marketApi } from '../api'
import { changeClass } from '../utils/changeClass'
import { useToastStore } from '../stores/toast'
import { useMarketStore } from '../stores/market'
import logger from '../utils/logger'
import GlobalIndicesStrip from './GlobalIndicesStrip.vue'
import AppButton from './ui/AppButton.vue'
import AppInput from './ui/AppInput.vue'
import Skeleton from './ui/Skeleton.vue'
use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const store = usePortfolioStore()
const route = useRoute()
const { show: toast } = useToastStore()

// State
const globalIndices = ref({})
const marketTimer = ref(null)
const activeTab = ref('combined')
const capitalOn = ref(500000)
const capitalOff = ref(500000)
const allocationOn = ref({ allocations: [] })
const allocationOff = ref({ allocations: [] })
const pnlOnData = ref({ items: [] })
const pnlOffData = ref({ items: [] })

const tabs = [
  { value: 'combined', label: '综合' },
  { value: 'on_exchange', label: '场内' },
  { value: 'off_exchange', label: '场外' }
]

const loading = computed(() => allocationOn.value.allocations.length === 0 && allocationOff.value.allocations.length === 0)

const pnlItems = computed(() => {
  if (activeTab.value === 'on_exchange') return pnlOnData.value.items || []
  if (activeTab.value === 'off_exchange') return pnlOffData.value.items || []
  return [...(pnlOnData.value.items || []), ...(pnlOffData.value.items || [])]
})

const totalAll = computed(() => {
  const on = allocationOn.value.total_amount || 0
  const off = allocationOff.value.total_amount || 0
  return on + off
})

const pnlOn = computed(() => pnlOnData.value.total_pnl || 0)
const pnlOff = computed(() => pnlOffData.value.total_pnl || 0)

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

// Methods
const formatNum = (n) => {
  const v = n || 0
  try {
    return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  } catch {
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }
}


const fetchGlobalIndices = async () => {
  try {
    const res = await marketApi.indicesGlobal()
    globalIndices.value = res.data?.indices || res.data || {}
  } catch (e) {
    logger.warn('[Dashboard] fetchGlobalIndices failed:', e)
    globalIndices.value = {}
  }
}

const refreshAll = async () => {
  await Promise.all([
    fetchGlobalIndices(),
    fetchAllocations(),
    fetchPnl()
  ])
}

const fetchAllocations = async () => {
  try {
    const [onRes, offRes] = await Promise.all([
      portfolioApi.getAllocation('on_exchange', capitalOn.value),
      portfolioApi.getAllocation('off_exchange', capitalOff.value)
    ])
    allocationOn.value = onRes.data || { allocations: [] }
    allocationOff.value = offRes.data || { allocations: [] }
  } catch (e) {
    toast('获取分配数据失败', 'error')
  }
}

const fetchPnl = async () => {
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

// Cumulative P&L History
const pnlHistory = ref(null)
const pnlHistoryLoading = ref(false)

const fetchPnlHistory = async (type = 'combined') => {
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

// Core Feature Panel Methods
// ECharts Options
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
    data: allocationOn.value.allocations?.map(a => ({
      value: a.target_amount,
      name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
    })) || []
  }],
  color: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#eab308']
}))

const pieOptionOff = computed(() => ({
  ...pieOptionOn.value,
  series: [{
    ...pieOptionOn.value.series[0],
    data: allocationOff.value.allocations?.map(a => ({
      value: a.target_amount,
      name: `${a.symbol} (${(a.target_weight * 100).toFixed(1)}%)`
    })) || []
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

const marketStore = useMarketStore()

onMounted(async () => {
  await Promise.all([fetchGlobalIndices(), fetchAllocations(), fetchPnl()])
  marketStore.connectWS((data) => {
    // Update matching global index in real-time (A-share indices pushed via WS)
    for (const region of Object.keys(globalIndices.value)) {
      const list = globalIndices.value[region]
      const i = list.findIndex(m => m.symbol === data.symbol)
      if (i >= 0) {
        list[i] = { ...list[i], price: data.price, change_pct: data.change_pct, available: true }
      }
    }
  })
  marketTimer.value = setInterval(fetchGlobalIndices, 60000)
})

onUnmounted(() => {
  marketStore.disconnectWS()
  if (marketTimer.value) clearInterval(marketTimer.value)
})

watch(() => route.path, () => {
  // Refresh on route change
  refreshAll()
})
</script>

<style scoped>
/* ==========================================
   Dashboard Styles
   ========================================== */
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* Page Header */
.page-header {
  margin-bottom: var(--space-2);
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  line-height: var(--line-height-tight);
  color: var(--color-text-primary);
  letter-spacing: var(--letter-spacing-tight);
}

.page-description {
  margin-top: var(--space-1);
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

/* Card */
.card {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}

.card-title-icon {
  font-size: var(--font-size-xl);
  line-height: 1;
}

.card-subtitle {
  margin: var(--space-1) 0 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-normal);
}

.card-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.card-meta {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-left: auto;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.meta-label { font-weight: var(--font-weight-medium); }
.meta-value { font-family: var(--font-family-mono); font-weight: var(--font-weight-semibold); }

/* Status Badge */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-success-700);
  background: var(--color-bg-success-subtle);
  border-radius: var(--radius-full);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-success-500);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Market Overview */
.market-overview { }

.index-regions {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
}
.index-region { }
.region-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-2);
}
.index-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--space-3);
}
.index-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  transition: var(--transition-fast);
}
.index-card:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.index-card.unavailable { opacity: 0.6; }
.index-name {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}
.index-price {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.index-change {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  padding: var(--space-0.5) var(--space-1.5);
  border-radius: var(--radius-full);
  width: fit-content;
}
.index-change.text-up {
  color: var(--color-danger-700);
  background: var(--color-danger-50);
}
.index-change.text-down {
  color: var(--color-success-700);
  background: var(--color-success-50);
}
.index-change.muted {
  color: var(--color-text-tertiary);
  background: transparent;
  font-weight: var(--font-weight-normal);
}

.change-icon {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

/* Global Indices - Ultra Compact Layout */
.global-indices-compact {
  --card-padding: var(--space-4);
}
.global-indices-compact .card-header-compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}
.global-indices-compact .card-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
}
.global-indices-compact .card-title-icon {
  font-size: var(--font-size-lg);
}
.global-indices-compact .status-badge {
  font-size: 10px;
}

.indices-scroll {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  overflow: visible;
}

.index-card-compact {
  flex-shrink: 0;
  min-width: 140px;
  max-width: 160px;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-2.5);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  transition: var(--transition-fast);
  scroll-snap-align: start;
}
.index-card-compact:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.index-card-compact.unavailable {
  opacity: 0.5;
}
.index-card-compact .index-name-compact {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.index-card-compact .index-price-compact {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  line-height: 1.2;
}
.index-card-compact .index-price-compact.muted {
  color: var(--color-text-tertiary);
  font-weight: var(--font-weight-normal);
}
.index-card-compact .index-change-compact {
  align-self: flex-start;
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  padding: var(--space-0.5) var(--space-1);
  border-radius: var(--radius-full);
  white-space: nowrap;
}
.index-card-compact .index-change-compact.text-up {
  color: var(--color-danger-700);
  background: var(--color-bg-danger-subtle);
}
.index-card-compact .index-change-compact.text-down {
  color: var(--color-success-700);
  background: var(--color-bg-success-subtle);
}
.index-card-compact .index-change-compact.muted {
  color: var(--color-text-tertiary);
  background: transparent;
  font-weight: var(--font-weight-normal);
}

.indices-empty-compact {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6) var(--space-4);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

/* Tabs */
.tabs {
  display: flex;
  gap: var(--space-1);
  background: var(--color-surface-tertiary);
  padding: var(--space-1);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-light);
}

.tab {
  flex: 1;
  padding: var(--space-2) var(--space-4);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  background: transparent;
  transition: var(--transition-fast);
}

.tab:hover {
  color: var(--color-text-primary);
}

.tab--active {
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.tab:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

/* Capital Bar */
.capital-bar {
  padding: var(--space-4) var(--space-5);
}

.capital-inputs {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}

.input-group {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 200px;
}

.input-group.dual {
  flex: none;
}

.input-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.capital-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
}

/* Summary Grid */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
}

.summary-card {
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  transition: var(--transition-fast);
}

.summary-card:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.summary-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-2xl);
  border-radius: var(--radius-lg);
  background: var(--color-surface-secondary);
  flex-shrink: 0;
}

.summary-icon.positive { background: var(--color-bg-success-subtle); }
.summary-icon.negative { background: var(--color-bg-danger-subtle); }

.summary-content { flex: 1; min-width: 0; }

.summary-label {
  margin: 0 0 var(--space-1);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.summary-content {
  min-width: 0;
}

.summary-value {
  margin: 0;
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  line-height: var(--line-height-tight);
  white-space: normal;
  overflow-wrap: anywhere;
}

.summary-value.skeleton { color: transparent; }

.text-success { color: var(--color-text-success) !important; }
.text-danger { color: var(--color-text-danger) !important; }
.text-up { color: var(--color-text-up) !important; }
.text-down { color: var(--color-text-down) !important; }
.text-warning { color: var(--color-text-warning) !important; }

/* Content Grid */
.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

@media (max-width: 1024px) {
  .content-grid { grid-template-columns: 1fr; }
}

/* Chart / Table Cards */
.chart-card, .table-card {
  display: flex;
  flex-direction: column;
}

.chart-card .card-header,
.table-card .card-header {
  flex-shrink: 0;
}

.chart-card v-chart,
.table-card .table-responsive {
  flex: 1;
  min-height: 0;
}

/* Table */
.table-responsive {
  overflow-x: auto;
  padding: var(--space-4) var(--space-5);
  -webkit-overflow-scrolling: touch;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.data-table th,
.data-table td {
  padding: var(--space-3) var(--space-4);
  text-align: left;
  vertical-align: middle;
  border-bottom: 1px solid var(--color-border-light);
}

.data-table th {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  background: var(--color-surface-secondary);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}

.data-table tbody tr {
  transition: var(--transition-fast);
}

.data-table tbody tr:hover {
  background: var(--color-surface-hover);
}

.data-table td code {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  background: var(--color-surface-tertiary);
  padding: var(--space-0.5) var(--space-1);
  border-radius: var(--radius-sm);
}

/* Compact table for allocation views */
.data-table.alloc-table { font-size: var(--font-size-xs); }
.data-table.alloc-table th,
.data-table.alloc-table td { padding: var(--space-2) var(--space-3); }
.data-table.alloc-table td:first-child { width: 85px; }
.data-table.alloc-table td:nth-child(2) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
.data-table.alloc-table .amount-cell { min-width: 100px; }

.data-table .weight-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0.5) var(--space-2);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-brand-700);
  background: var(--color-bg-brand-subtle);
  border-radius: var(--radius-full);
}

.data-table .type-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0.5) var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-full);
  text-transform: capitalize;
}

.data-table .type-badge.on_exchange {
  color: var(--color-info-700);
  background: var(--color-bg-info-subtle);
}

.data-table .type-badge.off_exchange {
  color: var(--color-warning-700);
  background: var(--color-bg-warning-subtle);
}

.data-table .change-value {
  font-family: var(--font-family-mono);
  font-weight: var(--font-weight-semibold);
}

.data-table .amount-cell {
  white-space: nowrap;
  font-family: var(--font-family-mono);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.data-table th.amount-header {
  text-align: right;
}

.data-table .footer-row {
  background: var(--color-surface-secondary);
}

.data-table .footer-row td {
  border-top: 2px solid var(--color-border-medium);
  border-bottom: none;
  font-weight: var(--font-weight-semibold);
}

.data-table .reason-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-secondary);
}

/* Comparison Table */
.comparison-table th:first-child,
.comparison-table td:first-child {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) var(--space-6);
  text-align: center;
  background: var(--color-surface-secondary);
  border: 2px dashed var(--color-border-medium);
  border-radius: var(--radius-xl);
}

.empty-icon { font-size: var(--font-size-5xl); line-height: 1; margin-bottom: var(--space-4); }
.empty-title { margin: 0 0 var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.empty-description { margin: 0 0 var(--space-6); font-size: var(--font-size-base); color: var(--color-text-secondary); max-width: 300px; }
.empty-design { padding: var(--space-6); text-align: center; color: var(--color-text-tertiary); }
.empty-design .empty-icon { font-size: var(--font-size-3xl); margin-bottom: var(--space-3); }

/* Loading Grid */
.loading-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

@media (max-width: 1024px) {
  .loading-grid { grid-template-columns: 1fr; }
}

.skeleton-card {
  padding: var(--space-5);
}

/* P&L Card */
.pnl-card { }

/* AI Design Card */
.ai-design-card { }

.ai-design-actions {
  padding: var(--space-4) var(--space-5);
  display: flex;
  justify-content: flex-end;
}

</style>