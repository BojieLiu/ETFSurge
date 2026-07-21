<template>
  <AppCard variant="outlined" title="自选/关注列表" description="快速查看自选标的的实时行情，支持添加/移除/备注" icon="⭐" class="watchlist-panel">
    <template #header-action>
      <AppButton variant="ghost" size="sm" @click="showAddWatchlist = true">
        <span class="btn-icon" aria-hidden="true">➕</span>
        添加自选
      </AppButton>
    </template>

    <!-- Add Watchlist Modal -->
    <AppModal
      v-model="showAddWatchlist"
      title="添加自选标的"
      size="md"
      @confirm="addWatchlist"
      @cancel="showAddWatchlist = false"
      :loading="watchlistAdding"
      confirm-text="添加"
    >
      <div class="watchlist-form">
        <div class="form-group">
          <label class="form-label" for="wl-symbol">标的代码</label>
          <div class="search-wrap">
            <AppInput
              id="wl-symbol"
              v-model="watchlistForm.symbol"
              placeholder="如: 510050, 000001"
              @keydown.enter="addWatchlist"
              @input="searchSymbols"
              @keydown="onWatchlistKeydown"
            />
            <ul v-if="searchSuggestions.length" class="search-dropdown" @mousedown.prevent>
              <li
                v-for="(s, i) in searchSuggestions"
                :key="s.symbol"
                :class="{ active: i === searchSuggestionIndex }"
                @click="selectSuggestion(s)"
                @mouseenter="searchSuggestionIndex = i"
              >
                <span class="suggestion-symbol">{{ s.symbol }}</span>
                <span class="suggestion-name">{{ s.name }}</span>
              </li>
            </ul>
          </div>
        </div>
        <div class="form-group">
          <label class="form-label" for="wl-asset-type">资产类型</label>
          <AppSelect
            id="wl-asset-type"
            v-model="watchlistForm.asset_type"
            :options="watchlistAssetTypes"
            placeholder="选择类型"
          />
        </div>
        <div class="form-group">
          <label class="form-label" for="wl-notes">备注</label>
          <AppInput
            id="wl-notes"
            v-model="watchlistForm.notes"
            placeholder="可选备注"
            type="textarea"
            rows="2"
          />
        </div>
      </div>
    </AppModal>

    <!-- Watchlist Table -->
    <AppSkeleton v-if="watchlistLoading" type="table" :rows="5" />

    <div v-else-if="filteredWatchlist.length === 0" class="empty-state">
      <span class="empty-icon" aria-hidden="true">📋</span>
      <p>暂无自选标的</p>
      <AppButton size="sm" variant="ghost" @click="showAddWatchlist = true">添加第一个</AppButton>
    </div>

    <AppTable
      v-else
      :columns="tableColumns"
      :data="filteredWatchlist"
      row-key="id"
      :striped="true"
      :hoverable="true"
      :selectable="true"
      @row-click="handleRowClick"
      density="comfortable"
    >
      <template #cell:price="{ row }">
        <span v-if="row.realtime" class="price-cell text-mono">¥{{ row.realtime.price?.toFixed(2) }}</span>
        <span v-else class="text-muted">—</span>
      </template>

      <template #cell:change="{ row }">
        <span v-if="row.realtime" class="change-cell" :class="getChangeClass(row.realtime.change_pct)">
          <span class="change-value">{{ formatChange(row.realtime.change_pct) }}</span>
        </span>
        <span v-else class="text-muted">—</span>
      </template>

      <template #cell:volume="{ row }">
        <span v-if="row.realtime" class="volume-cell text-mono">{{ formatVolume(row.realtime.volume) }}</span>
        <span v-else class="text-muted">—</span>
      </template>

      <template #cell:notes="{ row }">
        <span v-if="row.notes" class="notes-text">{{ row.notes }}</span>
        <span v-else class="text-muted">—</span>
      </template>

      <template #cell:actions="{ row }">
        <div class="action-buttons">
          <AppButton size="xs" variant="ghost" @click.stop="editWatchlist(row)" title="编辑备注">✏️</AppButton>
          <AppButton size="xs" variant="danger" @click.stop="removeWatchlist(row)" title="移除">🗑️</AppButton>
        </div>
      </template>
    </AppTable>
  </AppCard>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { marketApi } from '@/api'
import { useMarketStore } from '@/stores/market'
import { AppCard, AppButton, AppInput, AppSelect, AppModal, AppTable, AppSkeleton } from '@/components'

const props = defineProps({ marketTab: { type: String, default: 'A' } })
const emit = defineEmits(['select-symbol'])

// Watchlist state
const watchlist = ref([])
const watchlistLoading = ref(false)
const showAddWatchlist = ref(false)
const watchlistForm = ref({ symbol: '', asset_type: 'A', notes: '' })
const watchlistAdding = ref(false)
const searchSuggestions = ref([])
const searchSuggestionIndex = ref(-1)
let suggestionSearchTimer = null

const watchlistAssetTypes = [
  { value: 'A', label: 'A股 ETF/股票' },
  { value: 'HK', label: '港股 ETF/股票' },
  { value: 'US', label: '美股 ETF/股票' },
  { value: 'index', label: '指数' },
]

const filteredWatchlist = computed(() => {
  if (!watchlist.value.length) return []
  if (props.marketTab === 'global') return watchlist.value
  return watchlist.value.filter(item => item.asset_type === props.marketTab)
})

const tableColumns = [
  { key: 'symbol', label: '代码', width: '80px' },
  { key: 'name', label: '名称', width: '140px' },
  { key: 'asset_type', label: '类型', width: '100px' },
  { key: 'price', label: '最新价', width: '100px' },
  { key: 'change', label: '涨跌幅', width: '100px' },
  { key: 'volume', label: '成交量', width: '100px' },
  { key: 'notes', label: '备注', width: '140px' },
  { key: 'actions', label: '操作', width: '80px' },
]

function getChangeClass(pct) {
  if (pct == null) return ''
  return pct >= 0 ? 'text-up' : 'text-down'
}

function formatChange(pct) {
  if (pct == null) return '—'
  const s = pct >= 0 ? '+' : ''
  return s + (pct * 100).toFixed(2) + '%'
}

function formatVolume(v) {
  if (v == null) return '—'
  if (v >= 100000000) return (v / 100000000).toFixed(2) + '亿'
  if (v >= 10000) return (v / 10000).toFixed(2) + '万'
  return v.toLocaleString()
}

function selectSymbol(item) {
  emit('select-symbol', item.symbol)
}

async function fetchWatchlist() {
  watchlistLoading.value = true
  try {
    const store = useMarketStore()
    await store.fetchWatchlist()
    watchlist.value = store.watchlist
  } catch (e) {
    console.error('Failed to fetch watchlist:', e)
  } finally {
    watchlistLoading.value = false
  }
}

function searchSymbols() {
  clearTimeout(suggestionSearchTimer)
  const keyword = watchlistForm.value.symbol.trim()
  if (!keyword) { searchSuggestions.value = []; return }
  suggestionSearchTimer = setTimeout(async () => {
    try {
      const res = await marketApi.search(keyword)
      searchSuggestions.value = (res.data || []).slice(0, 10)
    } catch { searchSuggestions.value = [] }
  }, 300)
}

function onWatchlistKeydown(e) {
  if (!searchSuggestions.value.length) return
  if (e.key === 'ArrowDown') {
    e.preventDefault(); searchSuggestionIndex.value = (searchSuggestionIndex.value + 1) % searchSuggestions.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault(); searchSuggestionIndex.value = (searchSuggestionIndex.value - 1 + searchSuggestions.value.length) % searchSuggestions.value.length
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (searchSuggestions.value[searchSuggestionIndex.value]) {
      selectSuggestion(searchSuggestions.value[searchSuggestionIndex.value])
    }
  } else if (e.key === 'Escape') {
    searchSuggestions.value = []
  }
}

function selectSuggestion(s) {
  watchlistForm.value.symbol = s.symbol
  searchSuggestions.value = []
}

async function addWatchlist() {
  if (!watchlistForm.value.symbol || watchlistAdding.value) return
  watchlistAdding.value = true
  try {
    const store = useMarketStore()
    await store.addWatchlist(watchlistForm.value.symbol, watchlistForm.value.asset_type, watchlistForm.value.notes)
    showAddWatchlist.value = false
    watchlistForm.value = { symbol: '', asset_type: 'A', notes: '' }
    setTimeout(fetchWatchlist, 500)
  } catch (e) {
    console.error('Add watchlist failed:', e)
  } finally { watchlistAdding.value = false }
}

async function removeWatchlist(item) {
  if (!confirm('确定要移除该自选吗？')) return
  try {
    const store = useMarketStore()
    await store.removeWatchlist(item.id)
    await fetchWatchlist()
  } catch (e) { console.error('Remove failed:', e) }
}

async function editWatchlist(item) {
  const newNotes = prompt('编辑备注:', item.notes || '')
  if (newNotes !== null && newNotes !== item.notes) {
    const store = useMarketStore()
    store.updateWatchlist(item.id, { notes: newNotes })
    await fetchWatchlist()
  }
}

function handleRowClick(row) {
  selectSymbol(row)
}

onMounted(fetchWatchlist)
</script>

<style scoped>
.watchlist-panel {
  /* AppCard handles layout */
}

.watchlist-form .form-group {
  margin-bottom: var(--space-4);
}

.watchlist-form .form-label {
  display: block;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
}

.search-wrap {
  position: relative;
}

.search-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: var(--z-index-dropdown);
  max-height: 200px;
  overflow-y: auto;
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  list-style: none;
  padding: var(--space-1);
  margin: var(--space-1) 0 0 0;
}

.search-dropdown li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition-fast);
}

.search-dropdown li:hover,
.search-dropdown li.active {
  background: var(--color-surface-hover);
}

.suggestion-symbol {
  font: var(--text-mono);
  color: var(--color-brand-600);
  min-width: 80px;
}

.suggestion-name {
  color: var(--color-text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-4);
  padding: var(--space-8);
  color: var(--color-text-tertiary);
}

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

.price-cell,
.volume-cell {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-sm);
}

.change-cell {
  font-weight: var(--font-weight-semibold);
}

.change-value {
  font-family: var(--font-family-mono);
}

.text-muted {
  color: var(--color-text-tertiary);
}

.notes-text {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: middle;
}

.action-buttons {
  display: flex;
  gap: var(--space-1);
}

/* Type badge */
.type-badge {
  display: inline-block;
  padding: var(--space-half) var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-full);
  text-transform: uppercase;
}

.type-badge.a { background: var(--color-bg-brand-subtle); color: var(--color-brand-700); }
.type-badge.hk { background: var(--color-bg-warning-subtle); color: var(--color-warning-700); }
.type-badge.us { background: var(--color-bg-success-subtle); color: var(--color-success-700); }
.type-badge.index { background: var(--color-bg-info-subtle); color: var(--color-info-700); }
</style>