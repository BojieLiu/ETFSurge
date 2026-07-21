<template>
  <AppCard variant="outlined" title="指数分析" description="全球主要指数实时行情与 AI 深度研报" icon="📈" class="index-analysis">
    <template #default>
      <!-- Index Search & Select -->
      <div class="index-search-section">
        <label class="form-label" for="index-search">选择指数</label>
        <div class="search-combo" ref="searchRef">
          <AppInput
            id="index-search"
            v-model="indexQuery"
            placeholder="搜索指数代码/名称..."
            :disabled="indexLoadingList || !indexList.length"
            :clearable="true"
            @focus="onIndexFocus"
            @blur="onIndexBlur"
            @keydown="onIndexKeydown"
            @input="onIndexQueryInput"
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

        <!-- Tab filter for index type -->
        <AppTabs
          v-model="indexTab"
          :tabs="indexTabOptions"
          variant="enclosed"
          full-width
          class="index-tabs"
        />

        <!-- Selected Index Badge -->
        <div v-if="selectedIndexName" class="selected-badge">
          <span class="badge-text">{{ selectedIndexName }} ({{ selectedIndexCode }})</span>
          <AppButton variant="ghost" size="xs" @click="clearIndex" aria-label="清除选择">×</AppButton>
        </div>

        <!-- Action Button -->
        <div class="action-row">
          <AppButton
            variant="primary"
            @click="analyzeIndex"
            :loading="indexLoading"
            :disabled="indexLoading || !selectedIndexCode"
          >
            <span class="btn-icon" aria-hidden="true" v-if="!indexLoading">🤖</span>
            <span class="animate-spin" v-else aria-hidden="true">⏳</span>
            {{ indexLoading ? '分析中...' : 'AI 分析指数' }}
          </AppButton>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="!selectedIndexCode && !indexLoading && !indexError && !indexReport" class="empty-prompt">
        <span class="prompt-icon" aria-hidden="true">💡</span>
        <p>搜索并选择一个指数开始分析</p>
      </div>

      <!-- Loading / Error / Report -->
      <AppSkeleton v-else-if="indexLoading" type="text" :rows="8" />

      <AppAlert v-else-if="indexError" variant="danger" :closable="false">
        <span class="alert-icon" aria-hidden="true">⚠️</span>
        <span>{{ indexError }}</span>
      </AppAlert>

      <div v-else-if="indexReport" class="report-container">
        <div class="report-content" v-html="renderMarkdown(indexReport)"></div>
        <AppAlert variant="warning" class="report-disclaimer" :closable="false">
          <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
          <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
        </AppAlert>
      </div>
    </template>
  </AppCard>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import { useLLMStream } from '@/composables/useLLMStream'
import { AppCard, AppButton, AppInput, AppTabs, AppSkeleton, AppAlert } from '@/components'

const props = defineProps({ marketTab: { type: String, default: 'A' } })

const indexList = ref([])
const indexLoadingList = ref(false)
let queryTimer = null

const indexQuery = ref('')
const indexDropdownOpen = ref(false)
const indexActiveIndex = ref(-1)
const searchRef = ref(null)

const selectedIndexCode = ref('')
const selectedIndexName = ref('')

const indexTab = ref('all')
const indexTabOptions = [
  { value: 'all', label: '全部' },
  { value: 'A', label: 'A股指数' },
  { value: 'HK', label: '港股指数' },
  { value: 'US', label: '美股指数' },
  { value: 'global', label: '全球指数' },
]

const indexLoading = ref(false)
const indexReport = ref('')
const indexError = ref('')

const { streaming: indexStreaming, fullText: indexStreamText, start: startIndexStream } = useLLMStream()

async function loadIndexMeta() {
  indexLoadingList.value = true
  try {
    const res = await fetch('/api/v1/market/indices')
    const data = await res.json()
    indexList.value = data || []
  } catch {
    indexList.value = []
  } finally {
    indexLoadingList.value = false
  }
}

const filteredIndicesByTab = computed(() => {
  const list = indexList.value
  if (indexTab.value === 'all') return list
  return list.filter(idx => idx.region === indexTab.value || idx.asset_type === indexTab.value)
})

function onIndexQueryInput() {
  clearTimeout(queryTimer)
  const q = indexQuery.value.trim().toLowerCase()
  if (!q) {
    indexDropdownOpen.value = true
    indexActiveIndex.value = -1
    return
  }
  indexDropdownOpen.value = filteredIndicesByTab.value.length > 0
  indexActiveIndex.value = -1
}

function onIndexFocus() {
  if (indexQuery.value.trim()) {
    indexDropdownOpen.value = filteredIndicesByTab.value.length > 0
  }
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
.index-analysis {
  /* AppCard handles layout */
}

.index-search-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.index-tabs {
  margin: var(--space-2) 0;
}

.form-label {
  display: block;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
  margin-bottom: var(--space-1);
}

.search-combo {
  position: relative;
  width: 100%;
}

.search-dropdown {
  position: absolute;
  top: calc(100% + var(--space-1));
  left: 0;
  right: auto;
  min-width: 340px;
  max-width: min(480px, 92vw);
  max-height: 420px;
  overflow-y: auto;
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-index-dropdown);
  list-style: none;
  padding: var(--space-1);
}

.search-dropdown li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: var(--transition-fast);
}

.search-dropdown li:hover,
.search-dropdown li.active {
  background: var(--color-surface-hover);
}

.result-name {
  flex: 1;
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-code {
  font: var(--text-mono);
  color: var(--color-text-tertiary);
  flex-shrink: 0;
}

.selected-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  background: var(--color-bg-brand-subtle);
  border: 1px solid var(--color-brand-200);
  border-radius: var(--radius-full);
  font-size: var(--font-size-sm);
  color: var(--color-brand-700);
}

.badge-text {
  font-weight: var(--font-weight-medium);
}

.action-row {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.empty-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-8);
  color: var(--color-text-tertiary);
}

.prompt-icon {
  font-size: 48px;
  opacity: 0.5;
}

.report-container {
  margin-top: var(--space-4);
}

.report-content {
  line-height: 1.8;
}

.report-content :deep(h1),
.report-content :deep(h2),
.report-content :deep(h3) {
  margin-top: var(--space-6);
  margin-bottom: var(--space-3);
}

.report-content :deep(p) {
  margin: var(--space-2) 0;
}

.report-content :deep(ul),
.report-content :deep(ol) {
  margin: var(--space-3) 0;
  padding-left: var(--space-6);
}

.report-content :deep(li) {
  margin: var(--space-1) 0;
}

.report-content :deep(code) {
  font-family: var(--font-family-mono);
  background: var(--color-neutral-100);
  padding: 0.125rem 0.375rem;
  border-radius: var(--radius-sm);
  font-size: 0.875em;
}

.report-content :deep(pre) {
  background: var(--color-neutral-900);
  color: var(--color-neutral-100);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  overflow-x: auto;
  margin: var(--space-4) 0;
}

.report-content :deep(pre code) {
  background: none;
  color: inherit;
  padding: 0;
  font-size: inherit;
}

.report-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: var(--space-4) 0;
}

.report-content :deep(th),
.report-content :deep(td) {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  text-align: left;
}

.report-content :deep(th) {
  background: var(--color-surface-secondary);
  font-weight: var(--font-weight-semibold);
}

.report-disclaimer {
  margin-top: var(--space-4);
}

.animate-spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>