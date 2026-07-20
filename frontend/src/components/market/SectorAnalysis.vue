<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">
        <span class="section-icon" aria-hidden="true">🏭</span>
        板块/概念分析
      </h2>
      <p class="section-desc">行业板块与热门概念的 AI 深度解读</p>
    </div>

    <div class="card">
      <div class="card-body">
        <!-- Sector Type Radio -->
        <div class="form-group">
          <label class="form-label">板块类型</label>
          <div class="radio-group" role="radiogroup" aria-label="板块类型">
            <label class="radio-item" v-for="type in sectorTypes" :key="type.value">
              <input type="radio" :value="type.value" v-model="sectorType" @change="onSectorTypeChange" />
              <span class="radio-label">{{ type.label }}</span>
            </label>
          </div>
        </div>

        <!-- Sector Search & Select -->
        <div class="form-group">
          <label class="form-label" for="sector-search">选择板块</label>
          <div class="search-combo" ref="sectorComboRef">
            <AppInput
              id="sector-search"
              v-model="sectorQuery"
              placeholder="搜索板块/概念名称..."
              :disabled="sectorLoadingList || !sectorList.length"
              :clearable="true"
              @focus="onSectorFocus"
              @blur="onSectorBlur"
              @keydown="onSectorKeydown"
            />
            <Transition name="dropdown">
              <ul v-if="sectorDropdownOpen && filteredSectors.length" class="search-dropdown" @mousedown.prevent>
                <li
                  v-for="(s, i) in filteredSectors"
                  :key="s.sector_code || s.plate_code"
                  :class="{ active: i === sectorActiveIndex }"
                  @click="selectSector(s)"
                  @mouseenter="sectorActiveIndex = i"
                >
                  <span class="result-name">{{ s.sector_name || s.plate_name }}</span>
                  <span class="result-code">{{ s.sector_code || s.plate_code }}</span>
                </li>
              </ul>
            </Transition>
          </div>
          <AppButton
            variant="primary"
            @click="analyzeSector"
            :loading="sectorLoading"
            :disabled="sectorLoading || !selectedSectorCode"
          >
            <span class="btn-icon" aria-hidden="true">🔍</span>
            AI 分析板块
          </AppButton>
        </div>

        <!-- Selected Sector Badge -->
        <div v-if="selectedSectorName" class="selected-badge">
          <span class="badge-text">{{ selectedSectorName }} ({{ selectedSectorCode }})</span>
          <AppButton variant="ghost" size="xs" @click="clearSector" aria-label="清除选择">×</AppButton>
        </div>

        <!-- Empty State -->
        <div v-if="!selectedSectorCode && !sectorLoading && !sectorError && !sectorReport" class="empty-prompt">
          <span class="prompt-icon" aria-hidden="true">💡</span>
          <p>选择板块开始分析</p>
        </div>

        <!-- Loading / Error / Report -->
        <div v-if="sectorLoading" class="loading-state">
          <div class="loading-spinner" aria-hidden="true"></div>
          <p>正在分析板块...</p>
        </div>

        <div v-if="sectorError" class="alert alert--error" role="alert">
          <span class="alert-icon" aria-hidden="true">⚠️</span>
          <span>{{ sectorError }}</span>
        </div>

        <div v-if="sectorReport" class="report-container">
          <div class="report-content" v-html="renderMarkdown(sectorReport)"></div>
          <div class="report-disclaimer">
            <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
            <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useLLMStream } from '../../composables/useLLMStream'
import { useSectorAnalysis } from '../../composables/useSectorAnalysis'

const props = defineProps({ marketTab: { type: String, default: 'A' } })
const emit = defineEmits(['select-sector'])

const { sectorTypes, sectorType, sectorList, selectedSectorCode, selectedSectorName,
  sectorLoadingList, sectorReport, sectorLoading, sectorError,
  sectorQuery, sectorDropdownOpen, sectorActiveIndex, sectorComboRef,
  filteredSectors, onSectorTypeChange, onSectorFocus, onSectorBlur,
  selectSector: selectSectorFromComposable, clearSector, onSectorKeydown } = useSectorAnalysis(computed(() => props.marketTab))

const { streaming: sectorStreaming, fullText: sectorStreamText, error: sectorStreamError, disclaimer: sectorStreamDisclaimer, start: startSectorStream } = useLLMStream()

async function analyzeSector() {
  if (!selectedSectorCode.value) return
  sectorLoading.value = true
  sectorReport.value = ''
  sectorError.value = ''
  sectorStreamDisclaimer.value = ''
  try {
    const result = await startSectorStream('/sector-analysis/stream', {
      sector_code: selectedSectorCode.value,
      sector_type: sectorType.value,
      sector_name: selectedSectorName.value,
    }, (token) => {
      sectorReport.value += token
    })
    if (result?.disclaimer) {
      sectorStreamDisclaimer.value = result.disclaimer
    }
  } catch (e) {
    sectorError.value = '分析失败：' + (e?.message || '网络错误')
  } finally {
    sectorLoading.value = false
  }
}
</script>

<style scoped>
.section-header { margin-bottom: var(--space-4); }
.section-title { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0 0 var(--space-1); }
.section-icon { font-size: var(--font-size-2xl); line-height: 1; }
.section-desc { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: visible; }
.card-body { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.form-group { display: flex; flex-direction: column; gap: var(--space-1.5); }
.form-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.radio-group { display: inline-flex; gap: var(--space-4); }
.radio-item { display: inline-flex; align-items: center; gap: var(--space-1.5); font-size: var(--font-size-sm); color: var(--color-text-secondary); cursor: pointer; }
.radio-item input { width: 16px; height: 16px; accent-color: var(--color-brand-600); }
.radio-label { font-weight: var(--font-weight-medium); }
.search-combo { position: relative; width: 100%; }
.search-dropdown { position: absolute; top: calc(100% + var(--space-1)); left: 0; right: auto; min-width: 340px; max-width: min(480px, 92vw); max-height: 420px; overflow-y: auto; background: var(--color-surface-primary); border: 1px solid var(--color-border-medium); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); z-index: var(--z-index-dropdown); list-style: none; padding: var(--space-1); }
.search-dropdown li { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); cursor: pointer; transition: var(--transition-fast); }
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
.report-content :deep(h1), .report-content :deep(h2), .report-content :deep(h3) { margin-top: var(--space-6); margin-bottom: var(--space-3); }
.report-content :deep(p) { margin: var(--space-2) 0; }
.report-content :deep(ul), .report-content :deep(ol) { padding-left: var(--space-6); margin: var(--space-2) 0; }
.report-disclaimer { margin-top: var(--space-4); padding: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); background: var(--color-surface-secondary); border-radius: var(--radius-md); display: flex; gap: var(--space-2); align-items: flex-start; }
.empty-prompt { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.prompt-icon { font-size: var(--font-size-3xl); }
.dropdown-enter-active, .dropdown-leave-active { transition: all var(--duration-fast) var(--ease-out); }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
