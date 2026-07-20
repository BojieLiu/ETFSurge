<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">
        <span class="section-icon" aria-hidden="true">⭐</span>
        自选/关注列表
      </h2>
      <p class="section-desc">快速查看自选标的的实时行情，支持添加/移除/备注</p>
    </div>

    <div class="card">
      <div class="card-header">
        <h3 class="card-title">
          <span class="card-title-icon" aria-hidden="true">📋</span>
          自选标的
        </h3>
        <div class="card-actions">
          <AppButton variant="ghost" size="sm" @click="showAddWatchlist = true">
            <span class="btn-icon" aria-hidden="true">➕</span>
            添加自选
          </AppButton>
        </div>
      </div>

      <div class="card-body">
        <!-- Add Watchlist Modal -->
        <div v-if="showAddWatchlist" class="modal-overlay" @click.self="showAddWatchlist = false">
          <div class="modal-dialog">
            <div class="modal-header">
              <h4>添加自选标的</h4>
              <button class="modal-close" @click="showAddWatchlist = false" aria-label="关闭">×</button>
            </div>
            <div class="modal-body">
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
                <label class="form-label" for="wl-notes">备注 (可选)</label>
                <AppInput
                  id="wl-notes"
                  v-model="watchlistForm.notes"
                  placeholder="如: 长期跟踪, 短线关注"
                  type="textarea"
                  :rows="2"
                />
              </div>
            </div>
            <div class="modal-footer">
              <AppButton variant="ghost" @click="showAddWatchlist = false">取消</AppButton>
              <AppButton variant="primary" @click="addWatchlist" :loading="watchlistAdding">{{ watchlistAdding ? '添加中...' : '添加' }}</AppButton>
            </div>
          </div>
        </div>

        <!-- Watchlist Loading/Empty -->
        <div v-if="watchlistLoading" class="loading-state">
          <div class="loading-spinner" aria-hidden="true"></div>
          <p>加载自选列表中...</p>
        </div>

        <div v-else-if="!filteredWatchlist.length" class="empty-state">
          <div class="empty-icon" aria-hidden="true">⭐</div>
          <p class="empty-title">暂无自选标的</p>
          <p class="empty-desc">点击"添加自选"开始关注您感兴趣的标的</p>
          <AppButton variant="primary" @click="showAddWatchlist = true" class="mt-3">
            <span class="btn-icon" aria-hidden="true">➕</span>
            添加第一个自选
          </AppButton>
        </div>

        <!-- Watchlist Table -->
        <div v-else class="watchlist-table-wrapper">
          <table class="data-table watchlist-table" role="grid">
            <thead>
              <tr>
                <th scope="col">代码</th>
                <th scope="col">名称</th>
                <th scope="col">类型</th>
                <th scope="col">最新价</th>
                <th scope="col">涨跌幅</th>
                <th scope="col">成交量</th>
                <th scope="col">备注</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in filteredWatchlist" :key="item.id" class="watchlist-row" @click="selectSymbol(item)">
                <td><code>{{ item.symbol }}</code></td>
                <td><strong>{{ item.name }}</strong></td>
                <td><span class="type-badge" :class="item.asset_type.toLowerCase()">{{ item.asset_type }}</span></td>
                <td v-if="item.realtime" class="price-cell text-mono">¥{{ item.realtime.price?.toFixed(2) }}</td>
                <td v-else class="text-muted">—</td>
                <td v-if="item.realtime" class="change-cell" :class="getChangeClass(item.realtime.change_pct)">
                  <span class="change-value">{{ formatChange(item.realtime.change_pct) }}</span>
                </td>
                <td v-else class="text-muted">—</td>
                <td v-if="item.realtime" class="volume-cell text-mono">{{ formatVolume(item.realtime.volume) }}</td>
                <td v-else class="text-muted">—</td>
                <td class="notes-cell">
                  <span v-if="item.notes" class="notes-text">{{ item.notes }}</span>
                  <span v-else class="text-muted">—</span>
                </td>
                <td>
                  <div class="action-buttons">
                    <AppButton size="xs" variant="ghost" @click.stop="editWatchlist(item)" title="编辑备注">✏️</AppButton>
                    <AppButton size="xs" variant="danger" @click.stop="removeWatchlist(item)" title="移除">🗑️</AppButton>
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
import { ref, computed, onMounted, nextTick } from 'vue'
import { marketApi } from '../../api'
import { useMarketStore } from '../../stores/market'

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
  } else if (e.key === 'Enter' && searchSuggestionIndex.value >= 0) {
    e.preventDefault(); selectSuggestion(searchSuggestions.value[searchSuggestionIndex.value])
  } else if (e.key === 'Escape') { searchSuggestions.value = []; searchSuggestionIndex.value = -1 }
}

function selectSuggestion(s) {
  watchlistForm.value.symbol = s.symbol; searchSuggestions.value = []; searchSuggestionIndex.value = -1
}

async function addWatchlist() {
  if (!watchlistForm.value.symbol || watchlistAdding.value) return
  watchlistAdding.value = true
  try {
    const store = useMarketStore()
    await store.addWatchlist(watchlistForm.value.symbol, watchlistForm.value.asset_type, watchlistForm.value.notes)
    showAddWatchlist.value = false
    watchlistForm.value = { symbol: '', asset_type: 'A', notes: '' }
    fetchWatchlist()
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

onMounted(fetchWatchlist)
</script>

<style scoped>
.section-header { margin-bottom: var(--space-4); }
.section-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0 0 var(--space-1); }
.section-icon { font-size: var(--font-size-2xl); line-height: 1; }
.section-desc { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: visible; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); flex-wrap: wrap; }
.card-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.card-title-icon { font-size: var(--font-size-xl); line-height: 1; }
.card-body { padding: var(--space-5); }
.card-actions { display: flex; gap: var(--space-2); }
.loading-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.loading-spinner { width: 24px; height: 24px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; }
.empty-icon { font-size: var(--font-size-4xl); }
.empty-title { font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.empty-desc { color: var(--color-text-secondary); }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: var(--z-index-modal); display: flex; align-items: center; justify-content: center; }
.modal-dialog { background: var(--color-surface-primary); border-radius: var(--radius-xl); box-shadow: var(--shadow-2xl); width: 100%; max-width: 480px; max-height: 90vh; overflow-y: auto; }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); }
.modal-body { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.modal-footer { display: flex; justify-content: flex-end; gap: var(--space-2); padding: var(--space-4) var(--space-5); border-top: 1px solid var(--color-border-light); }
.form-group { display: flex; flex-direction: column; gap: var(--space-1.5); }
.form-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.search-wrap { position: relative; }
.search-dropdown { position: absolute; top: calc(100% + var(--space-1)); left: 0; right: auto; min-width: 340px; max-width: min(480px, 92vw); max-height: 420px; overflow-y: auto; background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: var(--z-index-dropdown); list-style: none; padding: var(--space-1); }
.search-dropdown li { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast); }
.search-dropdown li:hover, .search-dropdown li.active { background: var(--color-surface-hover); }
.suggestion-symbol { font-family: var(--font-family-mono); font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); min-width: 80px; }
.suggestion-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.watchlist-table-wrapper { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: var(--font-size-sm); }
.data-table th { text-align: left; padding: var(--space-2) var(--space-3); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); border-bottom: 2px solid var(--color-border-light); white-space: nowrap; }
.data-table td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border-light); }
.watchlist-row { cursor: pointer; transition: var(--transition-fast); }
.watchlist-row:hover { background: var(--color-surface-hover); }
.text-muted { color: var(--color-text-tertiary); }
.text-mono { font-family: var(--font-family-mono); }
.text-up { color: var(--color-text-up); }
.text-down { color: var(--color-text-down); }
.type-badge { display: inline-block; padding: var(--space-0) var(--space-2); border-radius: var(--radius-full); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); }
.type-badge.a { color: var(--color-brand-700); background: var(--color-bg-brand-subtle); }
.type-badge.hk { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); }
.type-badge.us { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); }
.type-badge.index { color: var(--color-success-700); background: var(--color-bg-success-subtle); }
.change-cell { font-weight: var(--font-weight-semibold); }
.volume-cell { font-size: var(--font-size-xs); }
.notes-cell { max-width: 160px; }
.notes-text { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.action-buttons { display: flex; gap: var(--space-1); }
</style>
