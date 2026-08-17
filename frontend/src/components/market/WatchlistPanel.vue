<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">⭐ 自选/关注列表</h2>
      <p class="section-desc">快速查看自选标的的实时行情，支持添加/移除/备注</p>
    </div>

    <div class="card">
      <div class="card-header">
        <h3 class="card-title">📋 自选标的</h3>
        <button class="btn-ghost" @click="showAddModal = true">➕ 添加自选</button>
      </div>

      <div class="card-body">
        <!-- Add Modal -->
        <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
          <div class="modal-dialog">
            <div class="modal-header">
              <h4>添加自选标的</h4>
              <button class="modal-close" @click="showAddModal = false">×</button>
            </div>
            <div class="modal-body">
              <div class="form-group">
                <label class="form-label">标的代码/名称</label>
                <div class="search-wrap">
                  <input
                    type="text"
                    v-model="form.symbol"
                    :placeholder="placeholderText"
                    class="text-input"
                    @keydown.enter="addItem"
                    @input="doSearch"
                  />
                  <ul v-if="suggestions.length" class="search-dropdown">
                    <li
                      v-for="(s, i) in suggestions" :key="s.symbol"
                      :class="{ active: i === suggestIndex }"
                      @click="selectSuggestion(s)"
                      @mouseenter="suggestIndex = i"
                    >
                      <span class="s-symbol">{{ s.symbol }}</span>
                      <span class="s-name">{{ s.name }}</span>
                    </li>
                  </ul>
                </div>
              </div>
              <div class="form-group">
                <label class="form-label">资产类型</label>
                <!-- P2-L: 特定市场 tab（A/HK/US）时下拉改为只读「市场：xxx」标签——无需用户再选；
                     global tab 保留下拉（跨市场需确认或依赖搜索选中自动设）。 -->
                <div v-if="marketTab !== 'global'" class="readonly-market-tag">{{ marketTabLabel }}</div>
                <select v-else v-model="form.asset_type" class="select-input">
                  <option v-for="opt in assetTypes" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">备注（可选）</label>
                <textarea v-model="form.notes" placeholder="如: 长期跟踪, 短线关注" class="text-input textarea" rows="2"></textarea>
              </div>
            </div>
            <div class="modal-footer">
              <button class="btn-ghost" @click="showAddModal = false">取消</button>
              <button class="btn-primary" @click="addItem" :disabled="adding">{{ adding ? '添加中...' : '添加' }}</button>
            </div>
            <div v-if="addError" class="modal-error">{{ addError }}</div>
          </div>
        </div>

        <!-- Edit Notes Modal -->
        <div v-if="showEditModal" class="modal-overlay" @click.self="showEditModal = false">
          <div class="modal-dialog">
            <div class="modal-header">
              <h4>编辑备注</h4>
              <button class="modal-close" @click="showEditModal = false">×</button>
            </div>
            <div class="modal-body">
              <div class="form-group">
                <label class="form-label">备注（{{ editingItem?.symbol }}）</label>
                <textarea v-model="editValue" placeholder="如: 长期跟踪, 短线关注" class="text-input textarea" rows="3"></textarea>
              </div>
            </div>
            <div class="modal-footer">
              <button class="btn-ghost" @click="showEditModal = false">取消</button>
              <button class="btn-primary" @click="saveEdit">保存</button>
            </div>
          </div>
        </div>

        <!-- Filter -->
        <div v-if="!loading && displayList.length" class="filter-bar">
          <input
            type="text"
            v-model="filterQuery"
            placeholder="🔍 搜索名称或代码过滤..."
            class="text-input filter-input"
          />
          <span class="filter-count">{{ filtered.length }}/{{ displayList.length }} 项</span>
        </div>

        <!-- Loading -->
        <div v-if="loading" class="loading-state">
          <div class="spinner"></div>
          <p>加载自选列表中...</p>
        </div>

        <!-- Empty -->
        <div v-else-if="!displayList.length" class="empty-state">
          <div class="empty-icon">⭐</div>
          <p class="empty-title">暂无自选标的</p>
          <p class="empty-desc">点击"添加自选"开始关注</p>
          <button class="btn-primary" @click="showAddModal = true">➕ 添加第一个自选</button>
        </div>

        <!-- Table -->
        <div v-else class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>代码</th><th>名称</th><th>类型</th><th>最新价</th><th>涨跌幅</th><th>成交量</th><th>备注</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in filtered" :key="item.id" class="watch-row" @click="selectItem(item)">
                <td><code>{{ item.symbol }}</code></td>
                <td><strong>{{ item.name }}</strong></td>
                <td><span class="type-badge" :class="item.asset_type.toLowerCase()">{{ item.asset_type }}</span></td>
                <td v-if="item.realtime?.price != null" class="mono">
                  {{ item.realtime.price.toFixed(2) }}
                  <!-- round24 R20: 实时不可用时的 T-1 收盘兜底（is_estimated）——显式
                       标「估」，杜绝静默当作实时价（用户误以为「没波动」） -->
                  <span v-if="item.realtime.is_estimated" class="estimated-badge" title="实时行情不可用，显示最近收盘价（估）">估</span>
                </td>
                <!-- round24 R20: 美股/HK 实时不可用显式标注「暂无实时」（非静默 null）——
                     旧实现 <td v-else> 显示「行情加载中」，用户无法分辨「没波动」vs「没数据」 -->
                <td v-else-if="item.realtime_unavailable" class="muted" :title="item.realtime_note || '该市场暂无实时行情'">
                  <span class="unavailable-text">暂无实时</span>
                </td>
                <!-- P0-3 (round20 §五 P0-3): 后端 _degraded=true 为永久降级（批量 realtime 失败），
                     显示「行情暂不可用」而非「加载中」——加载态另有 loading 分支，语义不混淆 -->
                <!-- R45 (round27): 三层全失败（realtime+收盘兜底+last-good 全无）→
                     诚实标注「维护中」+ 显式时间戳，区分「没波动」vs「没数据」，
                     杜绝空白冒充「行情加载中」。 -->
                <td v-else-if="item.data_unavailable_since" class="muted" :title="'数据源维护中，最后可用时间：' + item.data_unavailable_since"><span class="maintenance-text">非交易时段无行情（数据源维护中）</span></td>
                <td v-else-if="item._degraded" class="muted" title="行情暂不可用（数据源弱）"><span class="degraded-text">行情暂不可用</span></td>
                <td v-else class="muted" title="行情加载中（数据源弱）"><span class="loading-text">行情加载中</span></td>
                <td v-if="item.realtime?.change_pct != null" :class="item.realtime.change_pct >= 0 ? 'up' : 'down'">
                  {{ formatPct(item.realtime.change_pct) }}
                </td>
                <td v-else-if="item.realtime?.is_estimated" class="muted" title="收盘价，无实时涨跌幅">—</td>
                <td v-else-if="item.realtime_unavailable" class="muted" :title="item.realtime_note || '该市场暂无实时行情'"><span class="unavailable-text">暂无实时</span></td>
                <!-- R45 (round27): 三层全失败（realtime+收盘兜底+last-good 全无）→
                     诚实标注「维护中」+ 显式时间戳，区分「没波动」vs「没数据」，
                     杜绝空白冒充「行情加载中」。 -->
                <td v-else-if="item.data_unavailable_since" class="muted" :title="'数据源维护中，最后可用时间：' + item.data_unavailable_since"><span class="maintenance-text">非交易时段无行情（数据源维护中）</span></td>
                <td v-else-if="item._degraded" class="muted" title="行情暂不可用（数据源弱）"><span class="degraded-text">行情暂不可用</span></td>
                <td v-else class="muted" title="行情加载中（数据源弱）"><span class="loading-text">行情加载中</span></td>
                <td v-if="item.realtime?.volume != null" class="mono small">{{ formatVol(item.realtime.volume) }}</td>
                <td v-else-if="item.realtime?.is_estimated" class="muted small">—</td>
                <td v-else-if="item.realtime_unavailable" class="muted small" :title="item.realtime_note || '该市场暂无实时行情'"><span class="unavailable-text">暂无实时</span></td>
                <!-- R45 (round27): 三层全失败（realtime+收盘兜底+last-good 全无）→
                     诚实标注「维护中」+ 显式时间戳，区分「没波动」vs「没数据」，
                     杜绝空白冒充「行情加载中」。 -->
                <td v-else-if="item.data_unavailable_since" class="muted" :title="'数据源维护中，最后可用时间：' + item.data_unavailable_since"><span class="maintenance-text">非交易时段无行情（数据源维护中）</span></td>
                <td v-else-if="item._degraded" class="muted" title="行情暂不可用（数据源弱）"><span class="degraded-text">行情暂不可用</span></td>
                <td v-else class="muted" title="行情加载中（数据源弱）"><span class="loading-text">行情加载中</span></td>
                <td class="notes-cell">
                  <span v-if="item.notes" class="notes-text">{{ item.notes }}</span>
                  <span v-else class="muted">—</span>
                </td>
                <td>
                  <div class="row-actions">
                    <!-- P1-6 (round16 3.17): 行内技术分析 + AI 分析按钮——复用
                         SectorHeatMap 双按钮模式（assetType 按 item.asset_type 推断，
                         A/HK/US 混合自选必须）；AI 经 emit analyze 交给上层 UnifiedAnalysis -->
                    <button class="btn-icon-only" @click.stop="openTechnical(item)" title="技术分析">📈</button>
                    <button class="btn-icon-only" @click.stop="emit('analyze', { mode: 'symbol', query: item.symbol, name: item.name })" title="AI 分析">🤖</button>
                    <button class="btn-icon-only" @click.stop="editItem(item)" title="编辑备注">✏️</button>
                    <button class="btn-icon-only danger" @click.stop="removeItem(item)" title="移除">🗑️</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- P1-6 (round16 3.17): 自选行技术分析弹窗（复用 SectorHeatMap 模式） -->
    <TechnicalAnalysisModal
      v-if="techModal"
      :symbol="techModal.symbol"
      :name="techModal.name"
      :asset-type="techModal.assetType || 'A'"
      @close="techModal = null"
      @ai="(p) => { techModal = null; emit('analyze', { mode: 'symbol', query: p.symbol, name: p.name }) }"
    />
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { marketApi } from '../../api'
import { useMarketStore } from '../../stores/market'
import TechnicalAnalysisModal from './TechnicalAnalysisModal.vue'

const props = defineProps({ marketTab: { type: String, default: 'A' } })
const emit = defineEmits(['select-symbol', 'analyze'])

const store = useMarketStore()

// P1-6: 技术分析弹窗状态
const techModal = ref(null)

// P1-6: 技术分析入口——assetType 按 item.asset_type/market 推断（A/HK/US 混合）
function openTechnical(item) {
  const mkt = (item.asset_type || item.market || props.marketTab || 'A').toUpperCase()
  const assetType = mkt === 'HK' || mkt === 'US' ? mkt : 'A'
  techModal.value = { symbol: item.symbol, name: item.name, assetType }
}

// State
const items = ref([])
const loading = ref(false)
const showAddModal = ref(false)
const form = ref({ symbol: '', asset_type: 'A', notes: '', name: '' })
const adding = ref(false)
const addError = ref('')
const suggestions = ref([])
const suggestIndex = ref(-1)
let searchTimer = null
const filterQuery = ref('')
const showEditModal = ref(false)
const editingItem = ref(null)
const editValue = ref('')

const assetTypes = [
  { value: 'A', label: 'A股 ETF/股票' },
  { value: 'HK', label: '港股 ETF/股票' },
  { value: 'US', label: '美股 ETF/股票' },
  { value: 'index', label: '指数' },
]

// P2-L: 市场标签只读展示（A/HK/US tab 添加框不再让用户选资产类型）
const marketTabLabel = computed(() => {
  const map = { A: '市场：A股', HK: '市场：港股', US: '市场：美股', global: '市场：跨市场' }
  return map[props.marketTab] || '市场：A股'
})

// Computed
// P2-L10 (round10 §5.2 用户反馈): placeholder 示例随市场 tab 动态化
const placeholderText = computed(() => {
  const examples = {
    A: '搜索代码或名称，如 510050、贵州茅台...',
    HK: '搜索代码或名称，如 00700、腾讯控股...',
    US: '搜索代码或名称，如 AAPL、Apple...',
    global: '搜索代码或名称（跨市场）...',
  }
  return examples[props.marketTab] || examples.global
})

const displayList = computed(() => {
  if (!items.value.length) return []
  if (props.marketTab === 'global') return items.value
  return items.value.filter(i => i.asset_type === props.marketTab)
})

const filtered = computed(() => {
  const q = filterQuery.value.trim().toLowerCase()
  if (!q) return displayList.value
  return displayList.value.filter(i =>
    (i.symbol && i.symbol.toLowerCase().includes(q)) ||
    (i.name && i.name.toLowerCase().includes(q)) ||
    (i.notes && i.notes.toLowerCase().includes(q))
  )
})

// Methods
function formatPct(pct) {
  if (pct == null) return '—'
  const s = pct >= 0 ? '+' : ''
  return s + pct.toFixed(2) + '%'
}

function formatVol(v) {
  if (v == null) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString()
}

function selectItem(item) {
  emit('select-symbol', item.symbol)
}

async function fetchItems() {
  loading.value = true
  try {
    await store.fetchWatchlist()
    items.value = store.watchlist
  } catch (e) {
    console.error('Failed to fetch watchlist:', e)
  } finally {
    loading.value = false
  }
}

// Search suggestions
function doSearch() {
  clearTimeout(searchTimer)
  const kw = form.value.symbol.trim()
  if (!kw) { suggestions.value = []; return }
  searchTimer = setTimeout(async () => {
    try {
      // Z29: 默认跨市场模式混入个股（AAPL/00700 等），自选可添加个股
      // round9 §7 用户反馈：marketTab 非 global 时按 tab 过滤补全（HK tab 不再
      // 混入 A 股标的）；global tab 保持跨市场（Z29 原语义）。
      const res = await marketApi.search(kw, {
        include_stocks: true,
        market: props.marketTab === 'global' ? undefined : props.marketTab,
      })
      suggestions.value = (res.data || []).slice(0, 10)
    } catch { suggestions.value = [] }
  }, 300)
}

function selectSuggestion(s) {
  // 输入框显示「代码 + 名称」：选中建议后回填 "510050 上证50ETF华夏"，
  // 便于确认选中的标的（名称存 form.name，addItem 提交前解析纯代码）。
  form.value.symbol = s.name && s.name !== s.symbol ? `${s.symbol} ${s.name}` : s.symbol
  // R28: 选中项真实名称存入 form——入库优先用它（realtime 失败时不 422）
  form.value.name = s.name || s.symbol
  // Z29: HK/US 结果回填市场类型；A 股结果回落 'A'
  // （否则先选 AAPL(US) 再选 A 股标的，会用错误市场类型入库、拿不到行情）
  if (s.market === 'HK' || s.market === 'US') {
    form.value.asset_type = s.market
  } else if (s.market === 'A') {
    form.value.asset_type = 'A'
  }
  suggestions.value = []
  suggestIndex.value = -1
}

async function addItem() {
  if (!form.value.symbol || adding.value) return
  adding.value = true
  addError.value = ''
  try {
    // 输入框可能为「代码 + 名称」格式（selectSuggestion 回填），提交前解析纯代码
    const symbol = String(form.value.symbol).trim().split(/\s+/)[0]
    await store.addWatchlist(symbol, form.value.asset_type, form.value.notes, form.value.name)
    // O27 (round7 §7 P27①): 添加后主动 fetchItems——旧实现依赖 store 乐观插入
    // （改 store.watchlist），组件本地 items 副本（fetchItems 内的浅拷贝）不响应 →
    // 列表不出现新条目需手动刷新。主动拉取同时拿到批量 realtime（P12：新条目
    // 后三列不再因单条 realtime 冷却为 null 而显示「—」）。
    await fetchItems()
    showAddModal.value = false
    form.value = { symbol: '', asset_type: 'A', notes: '', name: '' }
  } catch (e) {
    addError.value = '添加失败: ' + (e?.response?.data?.detail || e?.message || '网络错误')
  } finally {
    adding.value = false
  }
}

async function removeItem(item) {
  if (!confirm('确定要移除该自选吗？')) return
  try {
    await store.removeWatchlist(item.id)
    await fetchItems()
  } catch (e) { console.error('Remove failed:', e) }
}

function editItem(item) {
  editingItem.value = item
  editValue.value = item.notes || ''
  showEditModal.value = true
}

async function saveEdit() {
  if (!editingItem.value) return
  try {
    await store.updateWatchlist(editingItem.value.id, { notes: editValue.value })
    showEditModal.value = false
    editingItem.value = null
    await fetchItems()
  } catch (e) { console.error('Edit failed:', e) }
}

onMounted(fetchItems)
</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-1); color: var(--color-text-primary); }
.section-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0; }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); }
.card-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); }
.card-title { font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); margin: 0; }
.card-body { padding: var(--space-5); }

/* Buttons */
.btn-ghost {
  padding: var(--space-1) var(--space-3);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: var(--transition-fast);
}
.btn-ghost:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }

.btn-primary {
  padding: var(--space-2) var(--space-5);
  font: var(--text-body);
  color: white;
  background: var(--color-brand-600);
  border: none;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: background var(--transition-fast);
}
.btn-primary:hover { background: var(--color-brand-700); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-icon-only {
  padding: var(--space-1) var(--space-1);
  font-size: var(--font-size-sm);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition-fast);
}
.btn-icon-only:hover { background: var(--color-surface-hover); }
.btn-icon-only.danger:hover { background: var(--color-bg-danger-subtle); }

/* Inputs */
.text-input {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-base);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-lg);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color var(--transition-fast);
  box-sizing: border-box;
}
.text-input:focus { border-color: var(--color-brand-500); box-shadow: 0 0 0 3px var(--color-brand-100); }
.text-input::placeholder { color: var(--color-text-tertiary); }
.textarea { resize: vertical; min-height: 60px; font-family: inherit; }

.select-input {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-base);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-lg);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  outline: none;
  cursor: pointer;
}
.select-input:focus { border-color: var(--color-brand-500); }

/* Modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100; display: flex; align-items: center; justify-content: center; }
.modal-dialog { background: var(--color-surface-primary); border-radius: var(--radius-xl); box-shadow: var(--shadow-2xl); width: 100%; max-width: 480px; max-height: 90vh; overflow-y: auto; }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); }
.modal-header h4 { margin: 0; font-size: var(--font-size-lg); }
.modal-close { font-size: var(--font-size-xl); color: var(--color-text-tertiary); background: none; border: none; cursor: pointer; padding: 0; }
.modal-close:hover { color: var(--color-text-primary); }
.modal-body { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.modal-footer { display: flex; justify-content: flex-end; gap: var(--space-2); padding: var(--space-4) var(--space-5); border-top: 1px solid var(--color-border-light); }
.modal-error { padding: var(--space-2) var(--space-4); font-size: var(--font-size-sm); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); }

.form-group { display: flex; flex-direction: column; gap: var(--space-1); }
.form-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.search-wrap { position: relative; }
.search-dropdown { position: absolute; top: 100%; left: 0; right: 0; max-height: 300px; overflow-y: auto; background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: 10; list-style: none; padding: var(--space-1); margin: var(--space-1) 0 0; }
.search-dropdown li { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; }
.search-dropdown li:hover, .search-dropdown li.active { background: var(--color-surface-hover); }
.s-symbol { font-family: monospace; font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); min-width: 80px; }
.s-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-secondary); }

/* Filter */
.filter-bar { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) 0; }
.filter-input { flex: 1; }
.filter-count { font-size: var(--font-size-xs); color: var(--color-text-tertiary); white-space: nowrap; }

/* Loading/Empty */
.loading-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.spinner { width: 24px; height: 24px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; }
.empty-icon { font-size: 48px; }
.empty-title { font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.empty-desc { color: var(--color-text-secondary); margin: 0; }

/* Table */
.table-wrap { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: var(--font-size-sm); }
.data-table th { text-align: left; padding: var(--space-2) var(--space-3); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; border-bottom: 2px solid var(--color-border-light); white-space: nowrap; }
.data-table td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border-light); }
.watch-row { cursor: pointer; transition: var(--transition-fast); }
.watch-row:hover { background: var(--color-surface-hover); }
.type-badge { display: inline-block; padding: 1px 8px; border-radius: var(--radius-full); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); }
.type-badge.a { color: var(--color-brand-700); background: var(--color-bg-brand-subtle); }
.type-badge.hk { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); }
.type-badge.us { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); }
.type-badge.index { color: var(--color-success-700); background: var(--color-bg-success-subtle); }
.mono { font-family: monospace; }
.small { font-size: var(--font-size-xs); }
.muted { color: var(--color-text-tertiary); }
.loading-text { font-size: var(--text-xs); color: var(--color-text-tertiary); }
/* round24 R20: 实时不可用显式标注——黄色警示（区别于「加载中」灰色，语义=数据源不可用
   而非仍在加载）；「估」徽标 = T-1 收盘价兜底 */
.unavailable-text { font-size: var(--text-xs); color: var(--color-warning-700); font-weight: var(--font-weight-medium); }
.estimated-badge { display: inline-block; margin-left: 4px; padding: 0 4px; border-radius: var(--radius-full); font-size: var(--font-size-xs); color: var(--color-warning-700); background: var(--color-bg-warning-subtle); border: 1px solid var(--color-warning-300); }
.up { color: var(--color-text-up); font-weight: var(--font-weight-semibold); }
.down { color: var(--color-text-down); font-weight: var(--font-weight-semibold); }
.notes-cell { max-width: 160px; }
.notes-text { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row-actions { display: flex; gap: var(--space-1); }
</style>
