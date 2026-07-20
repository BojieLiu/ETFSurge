<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">
        <span class="section-icon" aria-hidden="true">📊</span>
        指数分析
      </h2>
      <p class="section-desc">全球主要指数的实时行情与 AI 解读</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="form-group">
          <label class="form-label">选择指数</label>
          <div class="search-combo" ref="indexComboRef">
            <AppInput
              v-model="indexQuery"
              placeholder="搜索指数代码/名称..."
              :disabled="indexLoadingList"
              :clearable="true"
              @input="onIndexQueryInput"
              @focus="indexDropdownOpen = true"
              @blur="onIndexBlur"
              @keydown="onIndexKeydown"
            />
            <Transition name="dropdown">
              <ul v-if="indexDropdownOpen && filteredIndicesByTab.length" class="search-dropdown" @mousedown.prevent>
                <li
                  v-for="(idx, i) in filteredIndicesByTab"
                  :key="idx.symbol"
                  :class="{ active: i === indexActiveIndex }"
                  @click="selectIndex(idx)"
                  @mouseenter="indexActiveIndex = i"
                >
                  <span class="result-name">{{ idx.name }}</span>
                  <span class="result-code">{{ idx.symbol }}</span>
                </li>
              </ul>
            </Transition>
          </div>
          <AppButton
            variant="primary"
            @click="analyzeIndex"
            :loading="indexLoading"
            :disabled="indexLoading || !selectedIndexCode"
          >
            <span class="btn-icon" aria-hidden="true">🔍</span>
            AI 分析指数
          </AppButton>
        </div>

        <div v-if="selectedIndexName" class="selected-badge">
          <span class="badge-text">{{ selectedIndexName }} ({{ selectedIndexCode }})</span>
          <AppButton variant="ghost" size="xs" @click="clearIndex" aria-label="清除选择">×</AppButton>
        </div>

        <div v-if="!selectedIndexCode && !indexLoading && !indexError && !indexReport" class="empty-prompt">
          <span class="prompt-icon" aria-hidden="true">💡</span>
          <p>选择指数开始 AI 分析</p>
        </div>

        <div v-if="indexLoading" class="loading-state">
          <div class="loading-spinner"></div>
          <p>正在分析指数...</p>
        </div>

        <div v-if="indexError" class="alert alert--error" role="alert">
          <span class="alert-icon" aria-hidden="true">⚠️</span>
          <span>{{ indexError }}</span>
        </div>

        <div v-if="indexReport" class="report-container">
          <div class="report-content" v-html="renderMarkdown(indexReport)"></div>
          <div class="report-disclaimer">
            <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
            <span>本工具仅供个人研究，不构成任何投资建议</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { fetchJson } from '../../utils/fetchJson'
import { useLLMStream } from '../../composables/useLLMStream'

const props = defineProps({ marketTab: { type: String, default: 'A' } })

const indexQuery = ref('')
const indexDropdownOpen = ref(false)
const indexActiveIndex = ref(-1)
const indexComboRef = ref(null)
const indexList = ref([])
const filteredIndices = ref([])
const selectedIndexCode = ref('')
const selectedIndexName = ref('')
const indexLoading = ref(false)
const indexReport = ref('')
const indexError = ref('')
const indexLoadingList = ref(false)

const filteredIndicesByTab = computed(() => {
  const list = filteredIndices.value
  if (!list.length || props.marketTab === 'global') return list
  return list.filter(idx => idx.market === props.marketTab)
})

async function loadIndexMeta() {
  indexLoadingList.value = true
  try {
    const res = await fetchJson('/api/v1/market/indices/meta')
    const list = Array.isArray(res) ? res : (res.data || res.results || [])
    indexList.value = list
    filteredIndices.value = list
  } catch {
    indexList.value = []
    filteredIndices.value = []
  } finally {
    indexLoadingList.value = false
  }
}

let queryTimer = null

function onIndexQueryInput() {
  clearTimeout(queryTimer)
  const q = indexQuery.value.trim().toLowerCase()
  if (!q) {
    filteredIndices.value = indexList.value
    indexDropdownOpen.value = true
    indexActiveIndex.value = -1
    return
  }
  filteredIndices.value = indexList.value
    .filter(i => i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q))
    .slice(0, 50)
  indexDropdownOpen.value = filteredIndices.value.length > 0
  indexActiveIndex.value = -1
}

function onIndexBlur() {
  setTimeout(() => { indexDropdownOpen.value = false }, 200)
}

function selectIndex(idx) {
  selectedIndexCode.value = idx.symbol
  selectedIndexName.value = idx.name
  indexQuery.value = selectedIndexName.value
  indexDropdownOpen.value = false
  indexActiveIndex.value = -1
}

function clearIndex() {
  selectedIndexCode.value = ''
  selectedIndexName.value = ''
  indexQuery.value = ''
  indexDropdownOpen.value = false
  indexActiveIndex.value = -1
}

function onIndexKeydown(e) {
  const list = filteredIndicesByTab.value
  if (!indexDropdownOpen.value || !list.length) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    indexActiveIndex.value = (indexActiveIndex.value + 1) % list.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    indexActiveIndex.value = (indexActiveIndex.value - 1 + list.length) % list.length
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = list[indexActiveIndex.value] || list[0]
    if (item) selectIndex(item)
  } else if (e.key === 'Escape') {
    indexDropdownOpen.value = false
    indexActiveIndex.value = -1
  }
}

const { streaming: indexStreaming, fullText: indexStreamText, start: startIndexStream } = useLLMStream()

async function analyzeIndex() {
  if (!selectedIndexCode.value) return
  indexLoading.value = true
  indexReport.value = ''
  indexError.value = ''
  try {
    await startIndexStream('/symbol-analysis/stream', {
      symbol: selectedIndexCode.value,
      name: selectedIndexName.value,
      asset_type: 'index',
    }, (token) => {
      indexReport.value += token
    })
  } catch (e) {
    indexError.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    indexLoading.value = false
  }
}

onMounted(loadIndexMeta)
</script>

<style scoped>
.section-header { margin-bottom: var(--space-4); }
.section-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0 0 var(--space-1); }
.section-icon { font-size: var(--font-size-2xl); line-height: 1; }
.section-desc { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); }
.card-body { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.form-group { display: flex; flex-direction: column; gap: var(--space-1.5); }
.form-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.search-combo { position: relative; }
.search-dropdown { position: absolute; top: calc(100% + var(--space-1)); left: 0; min-width: 340px; max-width: 480px; max-height: 420px; overflow-y: auto; background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: var(--z-index-dropdown); list-style: none; padding: var(--space-1); }
.search-dropdown li { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; }
.search-dropdown li:hover, .search-dropdown li.active { background: var(--color-surface-hover); }
.result-name { flex: 1; font-size: var(--font-size-sm); color: var(--color-text-primary); }
.result-code { font-family: var(--font-family-mono); font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.selected-badge { display: inline-flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); background: var(--color-bg-brand-subtle); border: 1px solid var(--color-brand-200); border-radius: var(--radius-lg); }
.badge-text { font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-brand-700); }
.loading-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.loading-spinner { width: 24px; height: 24px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.alert { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-radius: var(--radius-lg); font-size: var(--font-size-sm); }
.alert--error { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border: 1px solid var(--color-danger-200); }
.report-container { margin-top: var(--space-4); }
.report-content :deep(p) { margin: var(--space-2) 0; }
.report-disclaimer { margin-top: var(--space-4); padding: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); background: var(--color-surface-secondary); border-radius: var(--radius-md); }
.empty-prompt { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.prompt-icon { font-size: var(--font-size-3xl); }
.dropdown-enter-active, .dropdown-leave-active { transition: all var(--duration-fast) var(--ease-out); }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
