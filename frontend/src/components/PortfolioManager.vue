<template>
  <div class="portfolio-manager">
    <!-- Page Header -->
    <header class="page-header">
      <h1 class="page-title">组合管理</h1>
      <p class="page-description">管理场内/场外 ETF 组合，设置目标权重，实时监控收益</p>
    </header>

    <!-- Tabs -->
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

    <!-- Add ETF Form -->
    <section class="card add-form">
      <div class="card-header">
        <h2 class="card-title">
          <span class="card-title-icon" aria-hidden="true">➕</span>
          添加 ETF 到 {{ activeTab === 'on_exchange' ? '场内' : '场外' }}
        </h2>
      </div>

      <form class="form" @submit.prevent="onAdd">
        <div class="form-row">
          <label class="form-field form-field--search">
            <span class="form-label">搜索 ETF</span>
            <div class="search-wrap" ref="searchRef">
              <AppInput
                v-model="searchQuery"
                placeholder="输入ETF代码或名称（如：510300）"
                :loading="searchLoading"
                :clearable="true"
                @input="onSearch"
                @keydown="onSearchKeydown"
                @focus="showDropdown = true"
                @blur="onSearchBlur"
              />
              <Transition name="dropdown">
                <ul v-if="showDropdown && searchResults.length" class="search-dropdown" @mousedown.prevent>
                  <li
                    v-for="(r, i) in searchResults"
                    :key="r.symbol"
                    :class="{ active: i === searchIndex }"
                    @click="selectSearch(r)"
                    @mouseenter="searchIndex = i"
                  >
                    <span class="result-symbol">{{ r.symbol }}</span>
                    <span class="result-name">{{ r.name }}</span>
                    <span class="result-tag">{{ r.asset_type }}</span>
                  </li>
                </ul>
                <div v-else-if="showDropdown && !searchQuery" class="search-dropdown hot-etfs" @mousedown.prevent>
                  <div class="hot-header">热门 ETF</div>
                  <button
                    v-for="h in hotEtfs"
                    :key="h.symbol"
                    class="hot-etf-item"
                    @click="selectHotEtf(h)"
                  >
                    <span class="result-symbol">{{ h.symbol }}</span>
                    <span class="result-name">{{ h.name }}</span>
                    <span class="result-tag">{{ h.tag }}</span>
                  </button>
                </div>
              </Transition>
            </div>
          </label>

          <div class="form-field">
            <span class="form-label">市场</span>
            <AppSelect
              v-model="form.asset_type"
              :options="assetTypeOptions"
              size="md"
              aria-label="市场"
            />
          </div>

          <div v-if="activeTab === 'off_exchange'" class="form-field">
            <span class="form-label">跟踪指数</span>
            <AppInput
              v-model="form.tracked_index"
              placeholder="e.g. 000300"
              size="md"
            />
          </div>

          <div class="form-field">
            <span class="form-label">成本价 (元/份)</span>
            <AppInput
              type="number"
              v-model.number="form.avg_cost"
              placeholder="默认自动填入当前价"
              :min="0"
              :step="0.001"
              size="md"
            />
          </div>

          <div class="form-field">
            <span class="form-label">持有份额/股数</span>
            <AppInput
              type="number"
              v-model.number="form.shares_held"
              placeholder="可选"
              :min="0"
              :step="1"
              size="md"
            />
            <!-- R66: 录了成本价但未录份额 → 提示按目标权重估算 -->
            <p v-if="form.avg_cost != null && form.avg_cost > 0 && (form.shares_held == null || form.shares_held === 0)" class="field-hint">
              未填份额，累计盈亏将按目标权重估算
            </p>
          </div>

          <div class="form-field form-field--weight">
            <div class="weight-control">
              <label class="weight-label">
                权重 {{ form.weight }}%
                <input type="range" v-model.number="form.weight" min="0" max="100" step="5" class="slider" />
              </label>
            </div>
          </div>
        </div>

        <div class="form-actions">
          <div v-if="formError" class="form-error">{{ formError }}</div>
          <AppButton type="submit" variant="primary" :disabled="!form.symbol" :loading="adding">
            <span class="btn-icon" aria-hidden="true">➕</span>
            {{ adding ? '添加中...' : '添加' }}
          </AppButton>
        </div>
      </form>
    </section>

    <!-- Capital & PnL Bar -->
    <section class="card capital-bar" v-if="currentEtfs.length">
      <div class="capital-inputs">
        <label class="input-group">
          <span class="input-label">估算仓位</span>
          <AppInput
            type="number"
            v-model.number="pnlCapital"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            size="md"
            aria-label="估算仓位金额"
          />
        </label>
        <AppButton variant="secondary" @click="refreshPnl" :loading="pnlLoading">
          <span class="btn-icon" aria-hidden="true">↻</span>
          刷新收益
        </AppButton>
      </div>

      <div class="pnl-summary" v-if="pnlSummary.total_amount > 0">
        <span class="pnl-label">合计</span>
        <span class="pnl-amount" :class="changeClass(pnlSummary.total_pnl)">
          ¥{{ formatNum(pnlSummary.total_pnl) }}
        </span>
        <span class="pnl-pct" :class="changeClass(pnlSummary.weighted_change_pct)">
          ({{ pnlSummary.weighted_change_pct >= 0 ? '+' : '' }}{{ pnlSummary.weighted_change_pct.toFixed(2) }}%)
        </span>
      </div>
      <div v-else-if="marketDataUnavailable" class="pnl-summary pnl-summary--unavailable">
        <span class="text-muted">行情数据暂不可用</span>
      </div>
    </section>

    <!-- ETF List -->
    <section class="card etf-list-card">
      <div class="card-header">
        <h2 class="card-title">
          <span class="card-title-icon" aria-hidden="true">{{ activeTab === 'on_exchange' ? '🏢' : '🏦' }}</span>
          {{ activeTab === 'on_exchange' ? '场内' : '场外' }} ETF 列表
        </h2>
        <div class="card-meta" v-if="currentWeightSum !== 1">
          <span class="weight-sum" :class="Math.abs(currentWeightSum - 1) > 0.01 ? 'warn' : ''">
            权重合计: {{ (currentWeightSum * 100).toFixed(1) }}%
            <span v-if="Math.abs(currentWeightSum - 1) > 0.01" class="warn-text"> (不等于 100%)</span>
          </span>
        </div>
        <div class="card-actions">
          <AppButton variant="ghost" size="sm" class="btn-auto-weight" @click="autoDistributeWeights">
            <span class="btn-icon" aria-hidden="true">⚖️</span>
            均分权重
          </AppButton>
          <AppButton variant="ghost" size="sm" @click="exportPortfolio" :loading="exportLoading">
            <span class="btn-icon" aria-hidden="true">📤</span>
            导出
          </AppButton>
          <AppButton variant="ghost" size="sm" @click="importFileClick">
            <span class="btn-icon" aria-hidden="true">📥</span>
            导入
          </AppButton>
          <AppButton variant="ghost" size="sm" @click="checkDrift" :loading="driftLoading">
            <span class="btn-icon" aria-hidden="true">⚖️</span>
            偏离检查
          </AppButton>
          <input type="file" ref="fileInput" accept=".csv" style="display: none" @change="onFileChange" />
        </div>
      </div>

      <!-- Tab Panel: aria-controls 指向此容器（R64 a11y: tab → tabpanel 关联） -->
      <div
        :id="`panel-${activeTab}`"
        role="tabpanel"
        :aria-labelledby="`tab-${activeTab}`"
      >
      <!-- Empty State -->
      <div v-if="!currentEtfs.length" class="empty-state">
        <div class="empty-icon" aria-hidden="true">📦</div>
        <h3 class="empty-title">还没有 ETF</h3>
        <p class="empty-description">在上方搜索并添加 ETF 到组合</p>
        <AppButton variant="secondary" @click="loadSampleData">
          <span class="btn-icon" aria-hidden="true">🧪</span>
          填充示例数据
        </AppButton>
      </div>

      <!-- Table -->
      <div v-else class="table-responsive">
        <!-- Loading overlay -->
        <div v-if="paginating" class="paginating-overlay">
          <div class="paginating-spinner"></div>
          <span>加载中...</span>
        </div>
        <table class="data-table" role="grid" :class="{ 'paginating': paginating }">
          <thead>
            <tr>
              <th scope="col">代码</th>
              <th scope="col">名称</th>
              <th scope="col">市场</th>
              <th scope="col">权重</th>
              <th scope="col">成本价</th>
              <th scope="col">份额</th>
              <th scope="col">现价</th>
              <th scope="col">涨跌幅</th>
              <th scope="col">当日盈亏</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
             <template v-for="etf in paginatedEtfs" :key="etf.symbol">
               <tr
                 :class="{ 'etf-row--selected': etf.symbol === props.selectedSymbol }"
                 :aria-selected="etf.symbol === props.selectedSymbol"
                 @click="emit('select', etf)"
               >
               <td>
                 <span v-if="etf.symbol === props.selectedSymbol" class="row-check" aria-hidden="true">✓</span>
                 <code>{{ etf.symbol }}</code>
               </td>
               <td>
                 <strong>{{ etf.name }}</strong>
                 <span class="exchange-badge" :class="etf.portfolio_type === 'on_exchange' ? 'on' : 'off'">
                   {{ etf.portfolio_type === 'on_exchange' ? '场内' : '场外' }}
                 </span>
               </td>
               <td><span class="type-badge" :class="etf.asset_type.toLowerCase()">{{ etf.asset_type }}</span></td>
              <td class="weight-cell">
                <div class="weight-control">
                  <input
                    type="range"
                    v-model.number="etf.editWeight"
                    :min="0"
                    :max="100"
                    step="5"
                    class="slider"
                    :aria-label="`${etf.name} 目标权重（当前 ${etf.editWeight != null ? etf.editWeight : (etf.target_weight * 100).toFixed(0)}%）`"
                    @input="etf.editWeight = Math.min(100, Math.max(0, etf.editWeight))"
                  />
                  <span class="weight-val">{{ etf.editWeight != null ? etf.editWeight : (etf.target_weight * 100).toFixed(0) }}%</span>
                </div>
              </td>
              <td class="cost-cell">
                <AppInput
                  v-if="etf.editCost !== undefined"
                  v-model.number="etf.editCost"
                  size="sm"
                  type="number"
                  :step="0.01"
                  :min="0"
                  @blur="saveCostBasis(etf)"
                  @keydown.enter="saveCostBasis(etf)"
                />
                <span v-else class="cost-value text-mono" @dblclick="startEditCost(etf)">
                  {{ etf.avg_cost != null ? '¥' + etf.avg_cost.toFixed(3) : '—' }}
                </span>
              </td>
              <td class="shares-cell">
                <!-- round19 P3-③: 「调整仓位（买卖）」——份额列 dblclick 进入
                     输入 delta 份额 + 成交价（默认现价），按加权平均重算成本 -->
                <div v-if="etf.adjustShares !== undefined" class="adjust-shares" @dblclick.stop>
                  <AppInput v-model.number="etf.adjustShares" size="sm" type="number"
                            :step="100" placeholder="±份额" aria-label="操作份额"
                            @keydown.enter="saveAdjustShares(etf)" />
                  <AppInput v-model.number="etf.adjustPrice" size="sm" type="number"
                            :step="0.01" :min="0" placeholder="成交价" aria-label="成交价"
                            @keydown.enter="saveAdjustShares(etf)" />
                  <AppButton size="sm" @click.stop="saveAdjustShares(etf)" title="确认调整">✓</AppButton>
                  <AppButton size="sm" variant="secondary" @click.stop="cancelAdjustShares(etf)" title="取消">✕</AppButton>
                </div>
                <AppInput
                  v-else-if="etf.editShares !== undefined"
                  v-model.number="etf.editShares"
                  size="sm"
                  type="number"
                  :step="1"
                  :min="0"
                  @blur="saveCostBasis(etf)"
                  @keydown.enter="saveCostBasis(etf)"
                />
                <span v-else class="shares-value text-mono" @dblclick="startAdjustShares(etf)" :title="etf.shares_held != null ? '双击调整仓位（买卖）' : '基于目标权重估算；双击调整仓位'">
                  {{ formatShares(etf.shares_held, etf) }}
                </span>
              </td>
              <td class="price-cell">
                <span v-if="pnlMap[etf.symbol]?.current_price" class="text-mono">¥{{ pnlMap[etf.symbol].current_price.toFixed(2) }}</span>
                <span v-else class="text-muted">—</span>
              </td>
              <td class="change-cell" :class="getChangeClass(pnlMap[etf.symbol]?.change_pct)">
                <span v-if="pnlMap[etf.symbol]" class="change-value">{{ formatChange(pnlMap[etf.symbol].change_pct) }}</span>
                <span v-else class="text-muted">—</span>
              </td>
              <td class="pnl-cell" :class="getChangeClass(pnlMap[etf.symbol]?.daily_pnl)">
                <span v-if="pnlMap[etf.symbol]" class="text-mono-lg">{{ formatChange(pnlMap[etf.symbol].daily_pnl, true) }}</span>
                <span v-else class="text-muted">—</span>
              </td>
              <td>
                 <div class="action-buttons">
                   <AppButton size="sm" variant="secondary" @click.stop="onUpdate(etf)" :disabled="etf.editWeight == null">
                     更新
                   </AppButton>
                   <AppButton size="sm" variant="danger" @click.stop="onRemove(etf.symbol)">
                     删除
                   </AppButton>
                 </div>
              </td>
            </tr>
            <tr v-if="etf.portfolio_type === 'off_exchange'" class="ta-expand">
              <td :colspan="9">
                 <div class="off-ta">
                   <button class="ta-toggle" @click.stop="toggleTa(etf)">
                    {{ taOpen[etf.symbol] ? '收起技术分析 ▲' : '查看技术分析 ▼' }}
                    <span class="ta-tracked">{{ taTarget(etf).assetType === 'index' ? '跟踪指数 ' + etf.tracked_index : '标的 ' + etf.symbol }}</span>
                  </button>
                  <div v-if="taOpen[etf.symbol]" class="ta-body">
                    <div v-if="taLoading[etf.symbol]" class="loading">加载技术指标...</div>
                    <template v-else-if="taData[etf.symbol]">
                      <div class="ind-grid">
                        <div class="ind-item"><span class="label">MA5</span><span>{{ fmt(taData[etf.symbol].indicators.ma5) }}</span></div>
                        <div class="ind-item"><span class="label">MA10</span><span>{{ fmt(taData[etf.symbol].indicators.ma10) }}</span></div>
                        <div class="ind-item"><span class="label">MA20</span><span>{{ fmt(taData[etf.symbol].indicators.ma20) }}</span></div>
                        <div class="ind-item"><span class="label">MA60</span><span>{{ fmt(taData[etf.symbol].indicators.ma60) }}</span></div>
                        <div class="ind-item"><span class="label">RSI(14)</span><span>{{ fmt(taData[etf.symbol].indicators.rsi) }}</span></div>
                        <div class="ind-item"><span class="label">MACD</span><span>{{ fmt(taData[etf.symbol].indicators.macd?.macd) }}</span></div>
                        <div class="ind-item"><span class="label">KDJ-K</span><span>{{ fmt(taData[etf.symbol].indicators.kdj?.k) }}</span></div>
                        <div class="ind-item"><span class="label">BOLL上</span><span>{{ fmt(taData[etf.symbol].indicators.bollinger?.upper) }}</span></div>
                        <div class="ind-item"><span class="label">BOLL下</span><span>{{ fmt(taData[etf.symbol].indicators.bollinger?.lower) }}</span></div>
                      </div>
                      <div class="signal-row" v-if="taData[etf.symbol].signal">
                        <span class="signal-badge" :class="taData[etf.symbol].signal.signal">{{ sigText(taData[etf.symbol].signal.signal) }}</span>
                        <span class="score">评分: {{ taData[etf.symbol].signal.score }}</span>
                      </div>
                      <ul class="reasons" v-if="taData[etf.symbol].signal?.reasons?.length">
                        <li v-for="(r, i) in taData[etf.symbol].signal.reasons" :key="i">{{ r }}</li>
                      </ul>
                    </template>
                    <div v-else class="text-muted">暂无数据（该跟踪指数暂不支持技术分析）</div>
                  </div>
                </div>
              </td>
            </tr>
            </template>
          </tbody>
        </table>
        <!-- Pagination -->
        <div class="pagination-bar" v-if="totalPages > 1">
          <button class="page-btn" :disabled="currentPage <= 1 || paginating" @click="prevPage" aria-label="上一页">‹</button>
          <template v-for="p in totalPages" :key="p">
            <button
              v-if="p === 1 || p === totalPages || Math.abs(p - currentPage) <= 2"
              :class="['page-btn', { 'page-btn--active': p === currentPage }]"
              @click="goToPage(p)"
              :disabled="paginating"
            >{{ p }}</button>
            <span v-else-if="p === currentPage - 3 || p === currentPage + 3" class="page-ellipsis">…</span>
          </template>
          <button class="page-btn" :disabled="currentPage >= totalPages || paginating" @click="nextPage" aria-label="下一页">›</button>
          <span class="page-info">共 {{ currentEtfs.length }} 条，{{ totalPages }} 页</span>
        </div>
      </div>
      </div><!-- /tabpanel -->
    </section>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { usePortfolioStore } from '../stores/portfolio'
import { portfolioApi, marketApi } from '../api'
import { useToastStore } from '../stores/toast'
import { changeClass } from '../utils/changeClass'
import { resolveTaTarget } from '../utils/taTarget'
import AppButton from './ui/AppButton.vue'
import AppInput from './ui/AppInput.vue'
import AppSelect from './ui/AppSelect.vue'

const store = usePortfolioStore()
const { show: toast } = useToastStore()

// Props / emits (selection indicator driven by a parent, e.g. the merged view)
const props = defineProps({
  selectedSymbol: { type: String, default: '' },
})
const emit = defineEmits(['select'])

// State
const activeTab = ref('on_exchange')
const searchQuery = ref('')
const searchResults = ref([])
const searchIndex = ref(-1)
const showDropdown = ref(false)
const searchLoading = ref(false)
const searchRef = ref(null)
const form = ref({ symbol: '', name: '', asset_type: 'A', weight: 20, tracked_index: '' })
const formError = ref('')
const pnlCapital = ref(500000)
const pnlData = ref({ items: [] })
const pnlLoading = ref(false)
const adding = ref(false)

// Pagination（round19 P2-①: 移除 cachedEtfs 快照层——分页直接由响应式 currentEtfs 派生，
// 消除「store 已更新、快照未同步」整类问题；loadTab/refreshPnl 不再需要快照同步行）
const currentPage = ref(1)
const pageSize = ref(10)
const paginating = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(currentEtfs.value.length / pageSize.value)))

const paginatedEtfs = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return currentEtfs.value.slice(start, start + pageSize.value)
})

function goToPage(page) {
  if (page < 1 || page > totalPages.value || paginating.value) return
  currentPage.value = page
}
function nextPage() { goToPage(currentPage.value + 1) }
function prevPage() { goToPage(currentPage.value - 1) }

const tabs = [
  { value: 'on_exchange', label: '场内 ETF' },
  { value: 'off_exchange', label: '场外 ETF' }
]

const assetTypeOptions = [
  { value: 'A', label: 'A股' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' }
]

const hotEtfs = [
  { symbol: '510050', name: '上证50ETF', tag: 'A股' },
  { symbol: '510300', name: '沪深300ETF', tag: 'A股' },
  { symbol: '159915', name: '创业板ETF', tag: 'A股' },
  { symbol: '159338', name: '国泰A500ETF', tag: 'A股' },
  { symbol: '518880', name: '黄金ETF', tag: 'A股' },
  { symbol: '513100', name: '纳指ETF', tag: '美股' },
  { symbol: '513050', name: '中概互联ETF', tag: '港股' },
  { symbol: '511880', name: '银华日利ETF', tag: 'A股' },
]

const currentEtfs = computed(() => activeTab.value === 'on_exchange' ? store.onExchange : store.offExchange)

const pnlMap = computed(() => {
  const m = {}
  for (const item of pnlData.value.items || []) {
    m[item.symbol] = item
  }
  return m
})

const pnlSummary = computed(() => ({
  total_pnl: (pnlData.value.items || []).reduce((s, i) => s + (i.daily_pnl || 0), 0),
  total_amount: (pnlData.value.items || []).reduce((s, i) => s + (i.target_amount || 0), 0),
  weighted_change_pct: (() => {
    const items = pnlData.value.items || []
    const total = items.reduce((s, i) => s + (i.target_amount || 0), 0)
    if (!total) return 0
    return items.reduce((s, i) => s + (i.target_amount || 0) * (i.change_pct || 0), 0) / total
  })()
}))

const marketDataUnavailable = computed(() => currentEtfs.value.length > 0 && (!pnlData.value.items || pnlData.value.items.length === 0))

const currentWeightSum = computed(() => currentEtfs.value.reduce((s, e) => s + e.target_weight, 0))

const formatNum = (v) => Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const formatChange = (n, isAmount = false) => {
  const val = n || 0
  const prefix = val >= 0 && !isAmount ? '+' : ''
  const suffix = isAmount ? '' : '%'
  return `${prefix}${val.toFixed(2)}${suffix}`
}

const getChangeClass = (val) => val == null ? '' : val >= 0 ? 'text-up' : 'text-down'

function formatShares(shares, etf) {
  if (shares != null && shares > 0) {
    return shares.toLocaleString()
  }
  // 未输入实际持仓时，按目标分配估算
  if (etf && pnlCapital.value > 0 && etf.target_weight > 0) {
    const price = pnlMap.value[etf.symbol]?.current_price
    if (price > 0) {
      const estimated = Math.round((pnlCapital.value * etf.target_weight) / price)
      if (estimated > 0) return '≈' + estimated.toLocaleString()
    }
  }
  return 'N/A'
}

// Search
let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  searchIndex.value = -1
  if (!searchQuery.value) { searchResults.value = []; return }
  searchLoading.value = true
  searchTimer = setTimeout(async () => {
    try {
      const res = await marketApi.search(searchQuery.value)
      searchResults.value = res.data.slice(0, 10)
    } catch { searchResults.value = [] }
    finally { searchLoading.value = false }
  }, 300)
}

function onSearchKeydown(e) {
  if (!searchResults.value.length) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    searchIndex.value = Math.min(searchIndex.value + 1, searchResults.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    searchIndex.value = Math.max(searchIndex.value - 1, 0)
  } else if (e.key === 'Enter' && searchIndex.value >= 0) {
    e.preventDefault()
    selectSearch(searchResults.value[searchIndex.value])
  } else if (e.key === 'Escape') {
    searchResults.value = []
    showDropdown.value = false
  }
}

function onSearchBlur() {
  setTimeout(() => { showDropdown.value = false }, 200)
}

function selectSearch(r) {
  // round19 P3-②: 搜索选中自动填当前价即成本（搜索响应带 realtime.price，可编辑覆盖）
  const curPrice = r?.realtime?.price ?? null
  form.value = { symbol: r.symbol, name: r.name, asset_type: r.asset_type, weight: form.value.weight, tracked_index: form.value.tracked_index, avg_cost: curPrice, shares_held: null }
  searchQuery.value = `${r.symbol} ${r.name}`
  searchResults.value = []
  showDropdown.value = false
  formError.value = ''
}

function selectHotEtf(h) {
  form.value = { symbol: h.symbol, name: h.name, asset_type: h.tag === '美股' ? 'US' : h.tag === '港股' ? 'HK' : 'A', weight: form.value.weight, tracked_index: form.value.tracked_index }
  searchQuery.value = `${h.symbol} ${h.name}`
  showDropdown.value = false
  formError.value = ''
}

// Actions
async function onAdd() {
  if (adding.value) return
  // Form validation
  if (!form.value.symbol) {
    formError.value = '请搜索并选择一只 ETF'
    return
  }
  if (!form.value.name) {
    formError.value = '请从搜索结果中选择 ETF（名称不能为空）'
    return
  }
  if (form.value.weight <= 0 || form.value.weight > 100) {
    formError.value = '权重必须在 1%–100% 之间'
    return
  }
  formError.value = ''
  adding.value = true
  try {
    await store.addEtf({
      symbol: form.value.symbol, name: form.value.name,
      asset_type: form.value.asset_type, target_weight: form.value.weight / 100,
      portfolio_type: activeTab.value, tracked_index: form.value.tracked_index || undefined,
      avg_cost: form.value.avg_cost || undefined,
      shares_held: form.value.shares_held || undefined,
    })
    toast(`已添加 ${form.value.name}`, 'success')
    form.value = { symbol: '', name: '', asset_type: 'A', weight: 20, tracked_index: form.value.tracked_index, avg_cost: null, shares_held: null }
    searchQuery.value = ''
    // round19 P2-①: 增删后同步 PnL 数据（列表响应式自动更新；PnL 需重新拉取）
    await loadTab()
  } finally {
    adding.value = false
  }
}

async function onUpdate(etf) {
  const w = etf.editWeight != null ? etf.editWeight / 100 : etf.target_weight
  await store.updateEtf(etf.symbol, { 
    target_weight: w,
    avg_cost: etf.avg_cost,
    shares_held: etf.shares_held,
  })
  toast(`${etf.name} 权重已更新`, 'success')
  etf.editWeight = null
  await loadTab()
}

async function onRemove(symbol) {
  await store.removeEtf(symbol)
  toast('ETF 已删除', 'info')
  // round19 P2-①: 增删后同步 PnL 数据
  await loadTab()
}

async function autoDistributeWeights() {
  const list = currentEtfs.value
  if (!list.length) return
  const equalWeight = 1 / list.length
  for (const etf of list) {
    try {
      await store.updateEtf(etf.symbol, { target_weight: equalWeight })
    } catch { /* skip */ }
  }
  toast(`已均分 ${list.length} 只 ETF 权重`, 'success')
  await loadTab()
}

// 场外标的技术分析：通过 tracked_index（跟踪指数）复用行情接口（日线及以上）
const taOpen = ref({})
const taLoading = ref({})
const taData = ref({})

function sigText(s) {
  return ({ buy: '买入', sell: '卖出', hold: '持有' })[s] || s || '—'
}
function fmt(v) {
  if (v == null || (typeof v === 'number' && Number.isNaN(v))) return '--'
  return typeof v === 'number' ? v.toFixed(2) : v
}
function taTarget(etf) {
  // R5-2-11: 统一走 resolveTaTarget——场外 tracked_index 为场内 ETF 代码时
  // 查 ETF 自身 K 线（assetType='A'），仅真实指数代码才用 'index'（旧逻辑全走 index）。
  return resolveTaTarget(etf)
}
async function loadTa(etf) {
  const t = taTarget(etf)
  if (!t.sym) return
  taLoading.value[etf.symbol] = true
  try {
    const [indRes, sigRes] = await Promise.all([
      marketApi.indicators(t.sym, t.assetType),
      marketApi.signal(t.sym, t.assetType),
    ])
    taData.value[etf.symbol] = {
      indicators: indRes.data || indRes,
      signal: sigRes.data || sigRes,
    }
  } catch {
    taData.value[etf.symbol] = null
  } finally {
    taLoading.value[etf.symbol] = false
  }
}
function toggleTa(etf) {
  const open = !taOpen.value[etf.symbol]
  taOpen.value[etf.symbol] = open
  if (open && !taData.value[etf.symbol] && !taLoading.value[etf.symbol]) loadTa(etf)
}

async function refreshPnl() {
  pnlLoading.value = true
  try {
    const res = await portfolioApi.dailyPnl(pnlCapital.value, activeTab.value)
    pnlData.value = res.data || { items: [] }
  } catch { pnlData.value = { items: [] } }
  finally { pnlLoading.value = false }
  if (currentPage.value > totalPages.value) currentPage.value = 1
}

async function loadTab() {
  paginating.value = true
  // Retry up to 2 times with 2s gap, in case backend just started
  for (let attempt = 0; attempt <= 2; attempt++) {
    try {
      await store.fetchEtfs(activeTab.value)
      if (currentPage.value > totalPages.value) currentPage.value = 1
      break
    } catch (e) {
      if (attempt < 2) {
        await new Promise(r => setTimeout(r, 2000))
      } else {
        toast('Loading portfolio failed, check backend', 'error')
      }
    }
  }
  await refreshPnl()
  paginating.value = false
}

async function loadSampleData() {
  const samples = [
    { symbol: '510050', name: '上证50ETF', asset_type: 'A', target_weight: 0.25, portfolio_type: 'on_exchange' },
    { symbol: '510300', name: '沪深300ETF', asset_type: 'A', target_weight: 0.25, portfolio_type: 'on_exchange' },
    { symbol: '159915', name: '创业板ETF', asset_type: 'A', target_weight: 0.2, portfolio_type: 'on_exchange' },
    { symbol: '518880', name: '黄金ETF', asset_type: 'A', target_weight: 0.15, portfolio_type: 'on_exchange' },
    { symbol: '511880', name: '银华日利ETF', asset_type: 'A', target_weight: 0.15, portfolio_type: 'on_exchange' },
  ]
  let count = 0
  for (const s of samples) {
    try { await store.addEtf(s); count++ } catch {}
  }
  toast(`已填充 ${count} 只示例 ETF`, 'success')
}

// Export/Import
const exportLoading = ref(false)
const importFile = ref(null)
const importLoading = ref(false)

async function exportPortfolio() {
  exportLoading.value = true
  try {
    const res = await portfolioApi.export(activeTab.value, 'csv')
    // Create download
    const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `portfolio_${activeTab.value}_${new Date().toISOString().split('T')[0]}.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    toast('导出成功', 'success')
  } catch (e) {
    toast('导出失败', 'error')
  } finally {
    exportLoading.value = false
  }
}

function onFileChange(e) {
  importFile.value = e.target.files[0]
}

async function importPortfolio() {
  if (!importFile.value) return
  importLoading.value = true
  try {
    const formData = new FormData()
    formData.append('file', importFile.value)
    formData.append('portfolio_type', activeTab.value)
    formData.append('mode', 'merge')
    formData.append('skip_invalid', 'true')
    
    const res = await portfolioApi.import(importFile.value, activeTab.value, 'merge', true)
    toast(`已导入 ${res.data.imported} 只，跳过 ${res.data.skipped} 只`, 'success')
    if (res.data.errors?.length) {
      console.warn('Import errors:', res.data.errors)
    }
    importFile.value = null
    await loadTab()
  } catch (e) {
    toast('导入失败', 'error')
  } finally {
    importLoading.value = false
  }
}

// Drift Check
const driftCheck = ref(null)
const driftLoading = ref(false)

async function checkDrift() {
  driftLoading.value = true
  try {
    const res = await portfolioApi.getDriftCheck(activeTab.value)
    driftCheck.value = res.data
    toast('偏离检查完成', 'success')
  } catch (e) {
    toast('偏离检查失败', 'error')
  } finally {
    driftLoading.value = false
  }
}

// Cost basis inline editing
function startEditCost(etf) {
  etf.editCost = etf.avg_cost
}

function startEditShares(etf) {
  etf.editShares = etf.shares_held
}

// round19 P3-③: 「调整仓位（买卖）」——份额列 dblclick 进入（非直接改值）
function startAdjustShares(etf) {
  etf.adjustShares = 0
  etf.adjustPrice = pnlMap.value[etf.symbol]?.current_price ?? etf.avg_cost ?? null
  delete etf.editShares
}

function cancelAdjustShares(etf) {
  delete etf.adjustShares
  delete etf.adjustPrice
}

async function saveAdjustShares(etf) {
  const delta = Number(etf.adjustShares)
  if (!delta || Number.isNaN(delta)) {
    toast('请输入操作份额（正=增持 / 负=减持）', 'warning')
    return
  }
  const price = Number(etf.adjustPrice)
  if (!price || price <= 0) {
    toast('成交价缺失/无效（请填成交价）', 'error')
    return
  }
  try {
    const res = await store.updateEtf(etf.symbol, { delta_shares: delta, price })
    const d = res || {}
    const side = d.trade?.side === 'sell' ? '减持' : '增持'
    let msg = `${side}成功：新成本 ¥${Number(d.avg_cost ?? etf.avg_cost).toFixed(3)}`
    if (d.realized_pnl != null && d.realized_pnl !== 0) {
      msg += `，已实现盈亏 ${d.realized_pnl >= 0 ? '+' : ''}¥${Number(d.realized_pnl).toFixed(2)}`
    }
    if (d.target_weight != null) {
      msg += `，权重联动至 ${(Number(d.target_weight) * 100).toFixed(1)}%`
    }
    toast(msg, 'success')
    delete etf.adjustShares
    delete etf.adjustPrice
    await loadTab()
  } catch (e) {
    toast('调整失败：' + (e?.response?.data?.detail || e?.message || '请检查输入'), 'error')
  }
}

async function saveCostBasis(etf) {
  const updates = {}
  if (etf.editCost !== undefined) updates.avg_cost = etf.editCost
  if (etf.editShares !== undefined) updates.shares_held = etf.editShares
  
  if (Object.keys(updates).length === 0) {
    // Just cancel editing
    delete etf.editCost
    delete etf.editShares
    return
  }
  
  try {
    await store.updateEtf(etf.symbol, updates)
    toast('成本基数已更新', 'success')
    etf.avg_cost = updates.avg_cost ?? etf.avg_cost
    etf.shares_held = updates.shares_held ?? etf.shares_held
  } catch (e) {
    toast('更新失败', 'error')
  } finally {
    delete etf.editCost
    delete etf.editShares
  }
}

watch(activeTab, loadTab)
onMounted(loadTab)
</script>

<style scoped>
/* ==========================================
   Portfolio Manager Styles
   ========================================== */
.portfolio-manager {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* Page Header */
.page-header { margin-bottom: var(--space-2); }
.page-title { font-size: var(--font-size-2xl); font-weight: var(--font-weight-bold); line-height: var(--line-height-tight); color: var(--color-text-primary); letter-spacing: var(--letter-spacing-tight); }
.page-description { margin-top: var(--space-1); font-size: var(--font-size-base); color: var(--color-text-secondary); line-height: var(--line-height-relaxed); }

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
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  border-radius: var(--radius-md);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: var(--transition-fast);
  white-space: nowrap;
}
.tab:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }
.tab--active { color: var(--color-brand-600); background: var(--color-bg-brand-subtle); }
.tab:focus-visible { outline: none; box-shadow: var(--shadow-focus); }

/* Card */
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: hidden; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); flex-wrap: wrap; }
.card-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.card-title-icon { font-size: var(--font-size-xl); line-height: 1; }
.card-meta { display: flex; align-items: center; gap: var(--space-4); margin-left: auto; }

/* Add Form */
.add-form { }
.add-form .card-header { padding-bottom: var(--space-3); }

.form { padding: var(--space-5); }
.form-row { display: flex; gap: var(--space-4); align-items: flex-end; flex-wrap: wrap; margin-top: var(--space-4); }
.form-field { display: flex; flex-direction: column; gap: var(--space-1); font-size: var(--font-size-xs); color: var(--color-text-tertiary); min-width: 0; }
.form-field--search { flex: 1; min-width: 280px; }
.form-field--weight { flex: 0 0 180px; }
.form-label { font-weight: var(--font-weight-medium); color: var(--color-text-secondary); }
.field-hint { margin: var(--space-1) 0 0; font-size: var(--text-xs); color: var(--color-warning, #b45309); }

.search-wrap { position: relative; width: 100%; }
.search-dropdown { position: absolute; top: calc(100% + var(--space-1)); left: 0; right: 0; max-height: 280px; overflow-y: auto; background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: var(--z-index-dropdown); list-style: none; padding: var(--space-1); }
.search-dropdown li { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast); }
.search-dropdown li:hover, .search-dropdown li.active { background: var(--color-surface-hover); }
.result-symbol { font-family: var(--font-family-mono); font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); min-width: 80px; }
.result-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.result-tag { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); padding: var(--space-0.5) var(--space-1.5); border-radius: var(--radius-full); background: var(--color-surface-tertiary); color: var(--color-text-tertiary); }

/* Hot ETFs */
.hot-header { padding: var(--space-2) var(--space-3); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); color: var(--color-text-tertiary); border-bottom: 1px solid var(--color-border-light); }
.hot-etf-item { display: flex; align-items: center; gap: var(--space-2); width: 100%; padding: var(--space-2) var(--space-3); border: none; background: transparent; font-family: inherit; font-size: inherit; text-align: left; cursor: pointer; transition: var(--transition-fast); border-radius: var(--radius-md); }
.hot-etf-item:hover { background: var(--color-surface-hover); }
.hot-etf-item:focus-visible { outline: none; box-shadow: var(--shadow-focus); }

/* Form error */
.form-error { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); }

.weight-control { width: 100%; }
.weight-label { display: block; font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); margin-bottom: var(--space-1); }
.slider { width: 100%; height: 6px; -webkit-appearance: none; appearance: none; background: var(--color-border-medium); border-radius: var(--radius-full); outline: none; cursor: pointer; }
.slider::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: var(--radius-full); background: var(--color-brand-600); box-shadow: var(--shadow-sm); transition: var(--transition-fast); }
.slider::-webkit-slider-thumb:hover { background: var(--color-brand-700); transform: scale(1.1); }
.slider::-moz-range-thumb { width: 18px; height: 18px; border-radius: var(--radius-full); background: var(--color-brand-600); border: none; box-shadow: var(--shadow-sm); }
.weight-val { display: inline-block; margin-left: var(--space-2); font-family: var(--font-family-mono); font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-brand-600); min-width: 48px; text-align: right; }

.form-actions { display: flex; justify-content: flex-end; align-items: center; gap: var(--space-3); padding-top: var(--space-4); margin-top: var(--space-4); border-top: 1px solid var(--color-border-light); }

/* Capital Bar */
.capital-bar { padding: var(--space-4) var(--space-5); }
.capital-inputs { display: flex; align-items: center; gap: var(--space-4); flex-wrap: wrap; margin-bottom: var(--space-3); }
.capital-inputs .input-group { display: inline-flex; align-items: center; gap: var(--space-2); flex: 1; min-width: 200px; }
.input-label { font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); white-space: nowrap; }

.pnl-summary { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); background: var(--color-surface-secondary); border-radius: var(--radius-lg); }
.pnl-label { font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); }
.pnl-amount { font-family: var(--font-family-mono); font-size: var(--font-size-lg); font-weight: var(--font-weight-bold); }
.pnl-pct { font-family: var(--font-family-mono); font-size: var(--font-size-base); font-weight: var(--font-weight-semibold); }

/* ETF List Card */
.etf-list-card { }
.etf-list-card .card-header { flex-wrap: wrap; }

.weight-sum { display: inline-flex; align-items: center; gap: var(--space-1); font-family: var(--font-family-mono); font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-brand-700); background: var(--color-bg-brand-subtle); padding: var(--space-1) var(--space-3); border-radius: var(--radius-full); }
.weight-sum.warn { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); }
.warn-text { font-weight: var(--font-weight-bold); color: var(--color-warning-800); }

/* Empty State */
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: var(--space-12) var(--space-6); text-align: center; background: var(--color-surface-secondary); border: 2px dashed var(--color-border-medium); border-radius: var(--radius-xl); }
.empty-icon { font-size: var(--font-size-5xl); line-height: 1; margin-bottom: var(--space-4); }
.empty-title { margin: 0 0 var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.empty-description { margin: 0 0 var(--space-6); font-size: var(--font-size-base); color: var(--color-text-secondary); max-width: 300px; }

/* Table */
.table-responsive { overflow-x: auto; padding: var(--space-4) var(--space-5); -webkit-overflow-scrolling: touch; }
.data-table { width: 100%; border-collapse: collapse; font-size: var(--font-size-sm); }
.data-table th, .data-table td { padding: var(--space-3) var(--space-4); text-align: left; vertical-align: middle; border-bottom: 1px solid var(--color-border-light); }
.data-table th { font-weight: var(--font-weight-semibold); color: var(--color-text-secondary); background: var(--color-surface-secondary); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
.data-table tbody tr { transition: var(--transition-fast); }
.data-table tbody tr:hover { background: var(--color-surface-hover); }
.data-table td code { font-family: var(--font-family-mono); font-size: var(--font-size-xs); background: var(--color-surface-tertiary); padding: var(--space-0.5) var(--space-1); border-radius: var(--radius-sm); }

.type-badge { display: inline-flex; align-items: center; padding: var(--space-0.5) var(--space-2); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); border-radius: var(--radius-full); text-transform: uppercase; }
.type-badge.a { color: var(--color-info-700); background: var(--color-bg-info-subtle); }
.type-badge.hk { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); }
.type-badge.us { color: var(--color-success-700); background: var(--color-bg-success-subtle); }

/* --- Selection indicator (Feature 3) --- */
.data-table tbody tr { cursor: pointer; transition: background var(--transition-fast), box-shadow var(--transition-fast); border-left: 3px solid transparent; }
.data-table tbody tr:hover { background: var(--color-surface-tertiary); }
.etf-row--selected {
  background: var(--color-bg-brand-subtle) !important;
  border-left: 3px solid var(--color-brand-600);
  box-shadow: inset 0 0 0 1px var(--color-brand-200);
}
.row-check { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; margin-right: 4px; border-radius: 50%; background: var(--color-brand-600); color: #fff; font-size: 11px; font-weight: 700; }
.exchange-badge { display: inline-flex; align-items: center; margin-left: var(--space-2); padding: 2px var(--space-2); font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); border-radius: var(--radius-full); vertical-align: middle; }
/* R64 (round28): 对比度修复——旧 on=#1d6fe0 off=#b8860b 在浅色背景上 <4.5:1（Lighthouse a11y 82）。改深一档（brand-700/warning-700）达标。 */
.exchange-badge.on { color: var(--color-brand-700); background: rgba(29, 78, 216, 0.12); }
.exchange-badge.off { color: var(--color-warning-700); background: rgba(180, 83, 9, 0.14); }

.weight-cell { min-width: 120px; }
.weight-control { width: 100%; }
.slider { width: 100%; height: 6px; -webkit-appearance: none; appearance: none; background: var(--color-border-medium); border-radius: var(--radius-full); outline: none; cursor: pointer; }
.slider::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: var(--radius-full); background: var(--color-brand-600); box-shadow: var(--shadow-sm); transition: var(--transition-fast); }
.slider::-webkit-slider-thumb:hover { background: var(--color-brand-700); transform: scale(1.1); }
.slider::-moz-range-thumb { width: 18px; height: 18px; border-radius: var(--radius-full); background: var(--color-brand-600); border: none; box-shadow: var(--shadow-sm); }
.weight-val { display: inline-block; margin-left: var(--space-2); font-family: var(--font-family-mono); font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-brand-600); min-width: 48px; text-align: right; }

.price-cell { font-family: var(--font-family-mono); font-weight: var(--font-weight-medium); }
.change-cell, .pnl-cell { font-family: var(--font-family-mono); font-weight: var(--font-weight-semibold); white-space: nowrap; }
.change-value { }
.text-mono-lg { font-family: var(--font-family-mono); font-size: var(--font-size-base); font-weight: var(--font-weight-medium); }
.text-muted { color: var(--color-text-tertiary); }

.action-buttons { display: flex; gap: var(--space-2); }
/* round19 P3-③: 「调整仓位（买卖）」内联编辑（份额 + 成交价） */
.adjust-shares { display: flex; align-items: center; gap: var(--space-1); flex-wrap: wrap; }
.adjust-shares :deep(.app-input) { width: 84px; }

/* Pagination */
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  padding: var(--space-4) 0 0;
  flex-wrap: wrap;
}
.page-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  font: var(--text-body-sm);
  cursor: pointer;
  transition: var(--transition-fast);
}
.page-btn:hover:not(:disabled) { border-color: var(--color-brand-500); color: var(--color-brand-600); }
.page-btn--active { background: var(--color-brand-600); color: #fff; border-color: var(--color-brand-600); }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-ellipsis { color: var(--color-text-tertiary); padding: 0 var(--space-1); }
.page-info { margin-left: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); }

/* Paginating overlay */
.paginating-overlay {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-6);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
.paginating-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-border-light);
  border-top-color: var(--color-brand-500);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
.data-table.paginating { opacity: 0.5; pointer-events: none; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Animations */
.dropdown-enter-active, .dropdown-leave-active { transition: all var(--duration-fast) var(--ease-out); }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateY(-8px); }

/* Text Color Utilities — uses Chinese convention: red = up/gain, green = down/loss */
.text-warning { color: var(--color-text-warning) !important; }

/* Focus Visible */
*:focus-visible { outline: none; box-shadow: var(--shadow-focus); }

/* Responsive */
@media (max-width: 768px) {
  .form-row { flex-direction: column; align-items: stretch; }
  .form-field--search { min-width: 0; }
  .form-field--weight { width: 100%; }
  .capital-inputs { flex-direction: column; align-items: stretch; }
  .capital-inputs .input-group { width: 100%; }
  .table-responsive { padding: var(--space-3); }
  .data-table th, .data-table td { padding: var(--space-2) var(--space-3); }
  .card-header { flex-direction: column; align-items: flex-start; gap: var(--space-3); }
  .card-meta { margin-left: 0; width: 100%; justify-content: space-between; }
}

@media (max-width: 640px) {
  .tabs { flex-direction: column; }
  .tab { text-align: center; }
  .action-buttons { flex-direction: column; }
  .action-buttons .btn { width: 100%; justify-content: center; }
}

/* 场外标的展开式技术分析 */
.ta-expand td { background: var(--bg-tertiary); padding: var(--space-3) var(--space-4) !important; }
.off-ta { display: flex; flex-direction: column; gap: var(--space-3); }
.ta-toggle {
  display: inline-flex; align-items: center; gap: var(--space-2);
  background: var(--bg-card); color: var(--text-primary);
  border: 1px solid var(--border-color); border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-3); font-size: var(--text-sm); cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}
.ta-toggle:hover { border-color: var(--accent); background: var(--bg-hover); }
.ta-tracked { color: var(--text-secondary); font-size: var(--text-xs); }
.ta-body { border-top: 1px dashed var(--border-color); padding-top: var(--space-3); }
.ind-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--space-2); margin-bottom: var(--space-3);
}
.ind-item {
  display: flex; flex-direction: column; gap: 2px;
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: var(--radius-sm); padding: var(--space-2) var(--space-3);
}
.ind-item .label { font-size: var(--text-xs); color: var(--text-secondary); }
.ind-item span:last-child { font-size: var(--text-sm); font-weight: 600; font-family: var(--font-mono); }
.signal-row { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2); }
.signal-badge {
  display: inline-block; padding: 2px var(--space-3); border-radius: var(--radius-sm);
  font-size: var(--text-sm); font-weight: 700; color: #fff;
}
.signal-badge.buy { background: var(--up-color); }
.signal-badge.sell { background: var(--down-color); }
.signal-badge.hold { background: var(--text-muted); }
.score { font-size: var(--text-sm); color: var(--text-secondary); }
.reasons { margin: 0; padding-left: var(--space-5); display: flex; flex-direction: column; gap: 4px; }
.reasons li { font-size: var(--text-sm); color: var(--text-secondary); list-style: disc; }
.loading { font-size: var(--text-sm); color: var(--text-muted); }
</style>