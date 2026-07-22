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
                    placeholder="搜索代码或名称，如 510050、贵州茅台..."
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
                <select v-model="form.asset_type" class="select-input">
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
                <td v-if="item.realtime" class="mono">{{ item.realtime.price?.toFixed(2) }}</td>
                <td v-else class="muted">—</td>
                <td v-if="item.realtime" :class="item.realtime.change_pct >= 0 ? 'up' : 'down'">
                  {{ formatPct(item.realtime.change_pct) }}
                </td>
                <td v-else class="muted">—</td>
                <td v-if="item.realtime" class="mono small">{{ formatVol(item.realtime.volume) }}</td>
                <td v-else class="muted">—</td>
                <td class="notes-cell">
                  <span v-if="item.notes" class="notes-text">{{ item.notes }}</span>
                  <span v-else class="muted">—</span>
                </td>
                <td>
                  <div class="row-actions">
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
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { marketApi } from '../../api'
import { useMarketStore } from '../../stores/market'

const props = defineProps({ marketTab: { type: String, default: 'A' } })
const emit = defineEmits(['select-symbol'])

const store = useMarketStore()

// State
const items = ref([])
const loading = ref(false)
const showAddModal = ref(false)
const form = ref({ symbol: '', asset_type: 'A', notes: '' })
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

// Computed
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
  return s + (pct * 100).toFixed(2) + '%'
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
      const res = await marketApi.search(kw)
      suggestions.value = (res.data || []).slice(0, 10)
    } catch { suggestions.value = [] }
  }, 300)
}

function selectSuggestion(s) {
  form.value.symbol = s.symbol
  suggestions.value = []
  suggestIndex.value = -1
}

async function addItem() {
  if (!form.value.symbol || adding.value) return
  adding.value = true
  addError.value = ''
  try {
    await store.addWatchlist(form.value.symbol, form.value.asset_type, form.value.notes)
    showAddModal.value = false
    form.value = { symbol: '', asset_type: 'A', notes: '' }
    setTimeout(fetchItems, 500)
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
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
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
.up { color: var(--color-text-up); font-weight: var(--font-weight-semibold); }
.down { color: var(--color-text-down); font-weight: var(--font-weight-semibold); }
.notes-cell { max-width: 160px; }
.notes-text { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row-actions { display: flex; gap: var(--space-1); }
</style>
