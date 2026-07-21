<template>
  <AppCard variant="default" :padding="false" class="design-result">
    <template #header>
      <div class="design-result__header">
        <h2 class="design-result__title">
          <span class="design-result__icon" aria-hidden="true">📁</span>
          <span>智能组合设计结果</span>
        </h2>
        <div v-if="isHistory && createdAt" class="design-result__badge">
          <span aria-hidden="true">🕐</span>
          <span>历史方案（{{ formatDate(createdAt) }}）</span>
        </div>
      </div>
    </template>

    <template #default>
      <AppTabs v-model="tab" :tabs="tabs" variant="line" full-width />

      <!-- Report tab -->
      <div v-if="tab === 'report'" class="design-result__panel">
        <AppCard variant="filled" :padding="false" class="report-panel">
          <div v-if="!designText && !reportError && !reportStale" class="report-waiting">
            <AppSpinner size="lg" />
            <p class="waiting-text">AI 报告生成中...</p>
            <p class="waiting-hint">报告由 DeepSeek 根据实时行情撰写，预计 10-30 秒完成</p>
          </div>
          <div v-else-if="!designText && !reportError && reportStale" class="report-stale">
            <AppBadge variant="warning" class="stale-badge">报告暂不可用</AppBadge>
            <p class="error-detail">该方案生成时 LLM 报告未能完成（可能因接口超时或连接异常），但方案数据和入选理由已保存，您仍可参考策略分配。</p>
            <AppButton variant="ghost" size="sm" @click="$emit('retry-report')">重新生成报告</AppButton>
          </div>
          <div v-else-if="reportError" class="report-error">
            <AppBadge variant="danger" class="error-badge">生成失败</AppBadge>
            <p class="error-detail">{{ reportError }}</p>
            <AppButton variant="primary" size="sm" @click="$emit('retry-report')">重新生成报告</AppButton>
          </div>
          <div v-else class="markdown-body" v-html="reportHtml"></div>
        </AppCard>

        <div class="design-result__footer">
          <AppButton variant="ghost" @click="$emit('regenerate')">重新生成方案</AppButton>
          <AppButton variant="ghost" @click="$emit('close')">返回</AppButton>
        </div>
      </div>

      <!-- Cards tab -->
      <div v-else-if="tab === 'cards'" class="design-result__panel">
        <p class="result-hint">共生成 {{ plans.length }} 个方案，点击卡片展开详情</p>

        <div class="plans-grid">
          <AppCard
            v-for="pf in plans"
            :key="pf.style"
            variant="outlined"
            hoverable
            clickable
            class="plan-card"
            :class="{ 'plan-card--expanded': expandedPlan === pf.style }"
            @click="togglePlanExpand(pf)"
          >
            <template #header>
              <div class="plan-header">
                <span class="plan-icon" :class="'plan-icon--' + planStyleKey(pf.style)">{{ planIcon(pf.style) }}</span>
                <div class="plan-header-text">
                  <span class="plan-style-name">{{ pf.style || pf.style_label }}</span>
                  <span class="plan-pf-name">{{ pf.portfolio_name || '' }}</span>
                </div>
                <span class="plan-dot" :style="{ background: planColor(pf.style) }"></span>
              </div>
            </template>

            <div class="plan-pos">{{ pf.positioning }}</div>

            <div class="layer-bars" v-if="pf.allocations">
              <div class="layer-bar-section">
                <div
                  v-for="layer in [1,2,3,4]"
                  :key="layer"
                  class="layer-bar"
                >
                  <div
                    class="layer-fill"
                    :style="{ width: layerWeight(layer, pf) + '%', background: layerColor(layer) }"
                  ></div>
                  <span class="layer-label" v-if="layerWeight(layer, pf) > 0">
                    L{{ layer }}: {{ layerWeight(layer, pf) }}%
                  </span>
                </div>
              </div>
            </div>

            <div v-if="expandedPlan === pf.style" class="plan-detail">
              <AppBadge
                v-for="r in riskMetrics(pf)"
                :key="r.label"
                variant="outline"
                :color="r.color"
                class="metric-badge"
              >
                {{ r.label }}: {{ r.value }}
              </AppBadge>

              <div class="detail-section">
                <h4 class="detail-title">核心持仓</h4>
                <div class="alloc-list">
                  <div
                    v-for="e in pf.allocations"
                    :key="e.symbol"
                    class="alloc-item"
                  >
                    <div class="alloc-symbol">
                      <code>{{ e.symbol }}</code>
                      <span>{{ e.name }}</span>
                    </div>
                    <div class="alloc-info">
                      <span class="alloc-layer">{{ e.layer }}</span>
                      <span class="alloc-weight">{{ (e.target_weight * 100).toFixed(1) }}%</span>
                    </div>
                    <p class="alloc-rationale" v-if="e.selection_rationale">{{ e.selection_rationale }}</p>
                  </div>
                </div>
              </div>

              <div class="detail-section">
                <h4 class="detail-title">入选理由</h4>
                <div class="rationale-tags">
                  <AppBadge
                    v-for="e in pf.allocations"
                    :key="e.symbol"
                    variant="outline"
                    size="sm"
                    :color="planColor(pf.style)"
                  >
                    {{ e.symbol }}: {{ e.selection_rationale }}
                  </AppBadge>
                </div>
              </div>

              <div class="detail-actions">
                <AppButton
                  variant="primary"
                  :loading="applyingPlan === pf.style"
                  @click="applyPlan(pf)"
                  :disabled="!!applyingPlan"
                >
                  应用该方案
                </AppButton>
              </div>
            </div>
          </AppCard>
        </div>
      </div>
    </template>
  </AppCard>
</template>

<script setup>
import { computed, ref } from 'vue'
import { marked } from 'marked'
import { formatDate } from '@/utils/formatDate'
import { AppCard, AppTabs, AppButton, AppBadge, AppSpinner } from '@/components'

const props = defineProps({
  plans: { type: Array, default: () => [] },
  designText: { type: String, default: '' },
  isHistory: { type: Boolean, default: false },
  createdAt: String,
  reportError: String,
  reportStale: { type: Boolean, default: false }
})

const emit = defineEmits(['apply', 'regenerate', 'close', 'retry-report'])

const tab = ref('cards')
const expandedPlan = ref(null)
const applyingPlan = ref(null)

const tabs = [
  { value: 'cards', label: '方案卡片', icon: '📋' },
  { value: 'report', label: '完整报告', icon: '📄' }
]

const reportHtml = computed(() => {
  if (!props.designText) return ''
  return marked.parse(props.designText)
})

const planColors = {
  aggressive: '#ef4444',
  balanced: '#f59e0b',
  defensive: '#22c55e'
}

function planStyleKey(style) {
  if (!style) return 'aggressive'
  const s = style.toLowerCase()
  if (s.includes('进攻') || s.includes('aggressive')) return 'aggressive'
  if (s.includes('平衡') || s.includes('balanced')) return 'balanced'
  if (s.includes('防御') || s.includes('defensive')) return 'defensive'
  return 'aggressive'
}

function planColor(style) {
  return planColors[planStyleKey(style)]
}

function planIcon(style) {
  const key = planStyleKey(style)
  return key === 'aggressive' ? '🚀' : key === 'balanced' ? '⚖️' : '🛡️'
}

function layerWeight(layer, pf) {
  if (!pf.allocations) return 0
  const sum = pf.allocations
    .filter(e => e.layer === layer)
    .reduce((a, e) => a + (e.target_weight || 0), 0)
  return Math.round(sum * 100)
}

function layerColor(layer) {
  const colors = ['#3b82f6', '#60a5fa', '#93c5fd', '#bfdbfe']
  return colors[layer - 1] || colors[0]
}

function riskMetrics(pf) {
  const metrics = []
  if (pf.expected_return != null) {
    metrics.push({ label: '预期年化', value: (pf.expected_return * 100).toFixed(1) + '%', color: planColor(pf.style) })
  }
  if (pf.max_drawdown != null) {
    metrics.push({ label: '最大回撤', value: (pf.max_drawdown * 100).toFixed(1) + '%', color: '#ef4444' })
  }
  if (pf.sharpe_ratio != null) {
    metrics.push({ label: '夏普比率', value: pf.sharpe_ratio.toFixed(2), color: '#3b82f6' })
  }
  return metrics
}

function togglePlanExpand(pf) {
  expandedPlan.value = expandedPlan.value === pf.style ? null : pf.style
}

async function applyPlan(pf) {
  if (applyingPlan.value) return
  applyingPlan.value = pf.style
  emit('apply', pf)
  applyingPlan.value = null
}
</script>

<style scoped>
.design-result {
  max-width: 900px;
  margin: 0 auto;
}

.design-result__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.design-result__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  font: var(--text-h3);
  color: var(--color-text-primary);
}

.design-result__icon {
  font-size: var(--font-size-xl);
}

.design-result__badge {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-full);
}

.design-result__panel {
  animation: panel-fade var(--duration-normal) var(--ease-out);
}

@keyframes panel-fade {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.report-panel {
  max-width: 800px;
}

.report-waiting,
.report-stale,
.report-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-10) var(--space-6);
}

.waiting-text {
  margin: 0;
  font: var(--text-h4);
  color: var(--color-text-primary);
}

.waiting-hint {
  margin: 0;
  font: var(--text-body-sm);
  color: var(--color-text-tertiary);
}

.stale-badge,
.error-badge {
  margin-bottom: var(--space-2);
}

.error-detail {
  margin: 0 0 var(--space-4);
  font: var(--text-body);
  color: var(--color-text-secondary);
  max-width: 400px;
}

.markdown-body {
  padding: var(--space-6);
  max-width: 800px;
  margin: 0 auto;
  font: var(--text-body);
  line-height: var(--line-height-relaxed);
  color: var(--color-text-primary);
}

.markdown-body h1, .markdown-body h2, .markdown-body h3 {
  font-family: var(--font-family-display);
  font-weight: var(--font-weight-bold);
  line-height: var(--line-height-tight);
  color: var(--color-text-primary);
  margin-top: var(--space-6);
  margin-bottom: var(--space-3);
}

.markdown-body h1 { font-size: var(--font-size-2xl); }
.markdown-body h2 { font-size: var(--font-size-xl); }
.markdown-body h3 { font-size: var(--font-size-lg); }

.markdown-body p { margin-bottom: var(--space-4); }
.markdown-body ul, .markdown-body ol { margin-bottom: var(--space-4); padding-left: var(--space-6); }
.markdown-body li { margin-bottom: var(--space-2); }
.markdown-body table { width: 100%; border-collapse: collapse; margin-bottom: var(--space-4); }
.markdown-body th, .markdown-body td { padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border-light); text-align: left; }
.markdown-body th { background: var(--color-surface-secondary); font-weight: var(--font-weight-semibold); }
.markdown-body code { font-family: var(--font-family-mono); background: var(--color-surface-tertiary); padding: 0.125rem 0.375rem; border-radius: var(--radius-sm); }
.markdown-body pre { background: var(--color-neutral-900); color: var(--color-neutral-100); padding: var(--space-4); border-radius: var(--radius-lg); overflow-x: auto; }
.markdown-body pre code { background: none; padding: 0; color: inherit; }

.design-result__footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--card-padding);
  border-top: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}

.result-hint {
  margin: 0 0 var(--space-4);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  padding: 0 var(--card-padding);
}

.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: var(--space-4);
}

.plan-card {
  overflow: hidden;
  transition: var(--transition-normal);
}

.plan-card--expanded {
  box-shadow: var(--shadow-lg);
  border-color: var(--color-brand-400);
}

.plan-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.plan-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  font-size: var(--font-size-lg);
  flex-shrink: 0;
}

.plan-icon--aggressive { background: var(--color-bg-danger-subtle); }
.plan-icon--balanced { background: var(--color-bg-warning-subtle); }
.plan-icon--defensive { background: var(--color-bg-success-subtle); }

.plan-header-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-half);
}

.plan-style-name {
  font: var(--text-h4);
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.plan-pf-name {
  font: var(--text-body-sm);
  color: var(--color-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.plan-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.plan-pos {
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-4);
}

.layer-bars {
  margin-bottom: var(--space-3);
}

.layer-bar-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.layer-bar {
  height: 8px;
  background: var(--color-surface-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
}

.layer-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width var(--duration-normal) var(--ease-out);
}

.layer-label {
  position: absolute;
  right: var(--space-2);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: white;
  text-shadow: 0 1px 2px rgba(0,0,0,0.3);
  white-space: nowrap;
}

.plan-detail {
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
  animation: detail-expand var(--duration-fast) var(--ease-out);
}

@keyframes detail-expand {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.metric-badge {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
}

.detail-section {
  margin-top: var(--space-4);
}

.detail-title {
  margin: 0 0 var(--space-2);
  font: var(--text-h4);
  color: var(--color-text-primary);
}

.alloc-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.alloc-item {
  padding: var(--space-3);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
}

.alloc-symbol {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  font: var(--text-body-sm);
  color: var(--color-text-primary);
}

.alloc-symbol code {
  font: var(--text-mono);
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
  padding: var(--space-half) var(--space-1);
  border-radius: var(--radius-sm);
}

.alloc-info {
  display: flex;
  gap: var(--space-3);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.alloc-layer {
  padding: var(--space-half) var(--space-2);
  background: var(--color-brand-100);
  color: var(--color-brand-700);
  border-radius: var(--radius-sm);
  font-weight: var(--font-weight-medium);
}

.alloc-weight {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.alloc-rationale {
  margin: var(--space-2) 0 0;
  font: var(--text-body-sm);
  color: var(--color-text-tertiary);
  line-height: var(--line-height-normal);
}

.rationale-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.detail-actions {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border-light);
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .plans-grid {
    grid-template-columns: 1fr;
  }
}
</style>