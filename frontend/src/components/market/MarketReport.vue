<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">
        <span class="section-icon" aria-hidden="true">📊</span>
        市场综合研判
      </h2>
      <p class="section-desc">基于实时行情与宏观数据的 AI 市场环境分析</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="action-row">
          <AppButton
            variant="primary"
            @click="generateMarketReport"
            :loading="marketLoading"
            :disabled="marketLoading"
          >
            <span class="btn-icon" aria-hidden="true" v-if="!marketLoading">🤖</span>
            <span class="animate-spin" v-else aria-hidden="true">⏳</span>
            {{ marketLoading ? '分析中...' : '生成市场研判' }}
          </AppButton>
        </div>

        <div v-if="marketLoading" class="loading-state">
          <div class="loading-spinner" aria-hidden="true"></div>
          <p>正在调用 DeepSeek 分析市场环境...</p>
        </div>

        <div v-if="marketError" class="alert alert--error" role="alert">
          <span class="alert-icon" aria-hidden="true">⚠️</span>
          <span>{{ marketError }}</span>
        </div>

        <div v-if="marketReport" class="report-container">
          <div class="report-content" v-html="renderMarkdown(marketReport)"></div>
          <div class="report-disclaimer">
            <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
            <span>本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负</span>
          </div>
        </div>

        <div v-if="!marketReport && !marketLoading && !marketError" class="empty-prompt">
          <span class="prompt-icon" aria-hidden="true">💡</span>
          <p>点击上方按钮生成当前市场环境研判报告</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useLLMStream } from '../../composables/useLLMStream'

defineProps({ marketTab: { type: String, default: 'A' } })

const marketReport = ref('')
const marketLoading = ref(false)
const marketError = ref('')

const { streaming: marketStreaming, fullText: marketStreamText, error: marketStreamError, disclaimer: marketStreamDisclaimer, start: startMarketStream, stop: stopMarketStream } = useLLMStream()

async function generateMarketReport() {
  marketLoading.value = true
  marketReport.value = ''
  marketError.value = ''
  try {
    const result = await startMarketStream('/llm-report/stream', { symbols: null }, (token) => {
      marketReport.value += token
    })
    if (result?.disclaimer) {
      marketStreamDisclaimer.value = result.disclaimer
    }
  } catch (e) {
    marketError.value = '生成失败：' + (e?.message || '网络错误')
  } finally {
    marketLoading.value = false
  }
}
</script>

<style scoped>
.section-header { margin-bottom: var(--space-4); }
.section-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--space-1);
}
.section-icon { font-size: var(--font-size-2xl); line-height: 1; }
.section-desc { margin: 0; font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.action-row { display: flex; gap: var(--space-3); flex-wrap: wrap; margin-bottom: var(--space-4); }
.loading-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.loading-spinner { width: 24px; height: 24px; border: 3px solid var(--color-border-light); border-top-color: var(--color-brand-600); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.alert { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-radius: var(--radius-lg); font-size: var(--font-size-sm); }
.alert--error { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border: 1px solid var(--color-danger-200); }
.report-container { margin-top: var(--space-4); }
.report-content { line-height: 1.8; }
.report-content :deep(h1), .report-content :deep(h2), .report-content :deep(h3) { margin-top: var(--space-6); margin-bottom: var(--space-3); }
.report-content :deep(p) { margin: var(--space-2) 0; }
.report-content :deep(ul), .report-content :deep(ol) { padding-left: var(--space-6); margin: var(--space-2) 0; }
.report-disclaimer { margin-top: var(--space-4); padding: var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); background: var(--color-surface-secondary); border-radius: var(--radius-md); display: flex; gap: var(--space-2); align-items: flex-start; }
.empty-prompt { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); padding: var(--space-8); text-align: center; color: var(--color-text-secondary); }
.prompt-icon { font-size: var(--font-size-3xl); }
</style>
