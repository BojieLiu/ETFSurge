<template>
  <div class="panel-body design-result">
    <div class="design-tabs">
      <button :class="['tab-btn', { active: tab === 'report' }]" @click="tab = 'report'">&#128214; 完整报告</button>
      <button :class="['tab-btn', { active: tab === 'cards' }]" @click="tab = 'cards'">&#128202; 方案卡片</button>
    </div>

    <div v-if="isHistory && createdAt" class="history-badge">
      &#128214; 历史方案（{{ formatDate(createdAt) }}）
    </div>

    <!-- Report tab -->
    <div v-if="tab === 'report'" class="design-report">
      <div v-if="!designText && !reportError && !reportStale" class="report-waiting">
        <div class="waiting-spinner"></div>
        <p class="waiting-text">⏳ AI 报告生成中...</p>
        <p class="waiting-hint">报告由 DeepSeek 根据实时行情撰写，预计 10-30 秒完成</p>
      </div>
      <div v-else-if="!designText && !reportError && reportStale" class="report-stale">
        <p class="error-text">📄 完整报告暂不可用</p>
        <p class="error-detail">该方案生成时 LLM 报告未能完成（可能因接口超时或连接异常），但方案数据和入选理由已保存，您仍可参考策略分配。</p>
        <AppButton variant="ghost" size="sm" @click="$emit('retry-report')">重新生成报告</AppButton>
      </div>
      <div v-else-if="reportError" class="report-error">
        <p class="error-text">❌ 报告生成失败</p>
        <p class="error-detail">{{ reportError }}</p>
        <AppButton variant="primary" size="sm" @click="$emit('retry-report')">重新生成报告</AppButton>
      </div>
      <div v-else class="markdown-body" v-html="reportHtml"></div>
      <div class="footer-actions">
        <AppButton variant="ghost" @click="$emit('regenerate')">重新生成方案</AppButton>
        <AppButton variant="ghost" @click="$emit('close')">返回</AppButton>
      </div>
    </div>

    <!-- Cards tab -->
    <div v-if="tab === 'cards'" class="design-cards">
      <p class="result-hint">共生成 {{ plans.length }} 个方案，点击卡片展开详情</p>
      <div class="plans-grid">
        <article v-for="pf in plans" :key="pf.style"
          :class="['plan-card', { expanded: expandedPlan === pf.style }]"
          @click="togglePlanExpand(pf)">
          <div class="plan-header">
            <span class="plan-icon" :class="'plan-icon--' + planStyleKey(pf.style)">{{ planIcon(pf.style) }}</span>
            <div class="plan-header-text">
              <span class="plan-style-name">{{ pf.style || pf.style_label }}</span>
              <span class="plan-pf-name">{{ pf.portfolio_name || '' }}</span>
            </div>
            <span class="plan-dot" :style="{ background: planColor(pf.style) }"></span>
          </div>
          <div class="plan-pos">{{ pf.positioning }}</div>

          <div class="layer-bars" v-if="pf.allocations">
            <div class="layer-bar-section">
              <div v-for="layer in ['core', 'satellite', 'defense']" :key="layer"
                class="lbar" :class="'lbar--' + layer"
                :style="{ width: calcLayerWeight(pf.allocations, layer) + '%' }"
                :title="layerLabel(layer) + ': ' + calcLayerWeight(pf.allocations, layer).toFixed(0) + '%'">
              </div>
            </div>
            <div class="layer-legend">
              <span v-for="layer in ['core', 'satellite', 'defense']" :key="layer" class="ll-item">
                <span class="ldot" :class="'ldot--' + layer"></span>
                {{ layerLabel(layer) }} {{ calcLayerWeight(pf.allocations, layer).toFixed(0) }}%
              </span>
            </div>
          </div>

          <div class="plan-metrics" v-if="pf.expected_return != null || pf.max_drawdown != null || pf.sharpe_ratio != null">
            <div class="metric" v-if="pf.expected_return != null">
              <span class="m-label">预期年化</span>
              <span class="m-val text-up">{{ (pf.expected_return * 100).toFixed(1) }}%</span>
            </div>
            <div class="metric" v-if="pf.max_drawdown != null">
              <span class="m-label">最大回撤</span>
              <span class="m-val text-down">{{ (Math.abs(pf.max_drawdown) * 100).toFixed(1) }}%</span>
            </div>
            <div class="metric" v-if="pf.sharpe_ratio != null">
              <span class="m-label">夏普比率</span>
              <span class="m-val">{{ pf.sharpe_ratio.toFixed(2) }}</span>
            </div>
          </div>

          <div class="plan-hld-preview" v-if="pf.allocations?.length && expandedPlan !== pf.style">
            <div v-for="a in pf.allocations.slice(0, 5)" :key="a.symbol" class="hld-row">
              <span class="hld-dot" :class="'ldot--' + (a.layer || 'satellite')"></span>
              <span class="hld-name">{{ a.name || a.symbol }}</span>
              <span class="hld-w">{{ (a.target_weight * 100).toFixed(1) }}%</span>
            </div>
            <div v-if="pf.allocations.length > 5" class="hld-row hld-more">+{{ pf.allocations.length - 5 }} 只更多，点击展开详情</div>
          </div>

          <div class="plan-action">
            <AppButton variant="primary" size="md" @click.stop="applyPlan(pf)">应用此方案</AppButton>
          </div>

          <div v-if="expandedPlan === pf.style" class="plan-expanded" @click.stop>
            <div class="detail-section" v-if="pf.allocations?.length">
              <h4 class="detail-title">完整持仓明细</h4>
              <table class="hld-table">
                <thead><tr><th>层</th><th>代码</th><th>名称</th><th>权重</th><th>配置逻辑</th></tr></thead>
                <tbody>
                  <tr v-for="a in pf.allocations" :key="a.symbol">
                    <td><span class="ldot" :class="'ldot--' + (a.layer || 'satellite')"></span><span class="ll-text">{{ layerLabel(a.layer || 'satellite') }}</span></td>
                    <td><code>{{ a.symbol }}</code></td>
                    <td>{{ a.name || '—' }}</td>
                    <td><span class="w-badge">{{ (a.target_weight * 100).toFixed(1) }}%</span></td>
                    <td class="rat-cell">{{ a.selection_rationale || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="detail-section" v-if="pf.allocation_rationale">
              <h4 class="detail-title">配置逻辑</h4>
              <p class="rat-text">{{ pf.allocation_rationale.asset_class_allocation || '—' }}</p>
              <p class="rat-text" v-if="pf.allocation_rationale.equity_style_tilt">风格倾向：{{ pf.allocation_rationale.equity_style_tilt }}</p>
            </div>
            <div class="detail-section" v-if="pf.risk_factors?.length">
              <h4 class="detail-title">风险因素</h4>
              <ul class="risk-list"><li v-for="rf in pf.risk_factors" :key="rf">{{ rf }}</li></ul>
            </div>
          </div>
        </article>
      </div>
      <div class="footer-actions">
        <AppButton variant="ghost" @click="$emit('regenerate')">重新生成</AppButton>
        <AppButton variant="ghost" @click="$emit('close')">返回</AppButton>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { formatDate } from '../../utils/formatDate'
import { renderMarkdown } from '../../utils/markdown'
import AppButton from '../ui/AppButton.vue'

const props = defineProps({
  plans: { type: Array, default: () => [] },
  designText: { type: String, default: '' },
  isHistory: { type: Boolean, default: false },
  createdAt: { type: String, default: '' },
  reportQuality: { type: String, default: 'pending' },
  reportError: { type: String, default: '' },
})

const emit = defineEmits(['apply', 'regenerate', 'close', 'retry-report'])

const tab = ref('cards')
const expandedPlan = ref(null)

const reportHtml = computed(() => props.designText ? renderMarkdown(props.designText) : '')

function planStyleKey(style) {
  if (!style) return 'balanced'
  const m = { '防御型': 'defensive', '防御': 'defensive', defensive: 'defensive', '平衡型': 'balanced', '平衡': 'balanced', '进攻型': 'aggressive', '进攻': 'aggressive' }
  return m[style] || 'balanced'
}
const planIcon = (style) => ({ defensive: '\u{1F6E1}\uFE0F', balanced: '\u2696\uFE0F', aggressive: '\u2694\uFE0F' })[planStyleKey(style)] || '\u{1F4CA}'
const planColor = (style) => ({ defensive: '#43A047', balanced: '#1976D2', aggressive: '#E53935' })[planStyleKey(style)] || '#888'
const layerLabel = (layer) => ({ core: '核心', satellite: '卫星', defense: '防御' })[layer] || layer

function calcLayerWeight(allocations, layer) {
  if (!allocations) return 0
  const total = allocations.reduce((s, a) => s + (a.target_weight || 0), 0)
  if (total === 0) return 0
  const sum = allocations.filter(a => (a.layer || 'satellite') === layer).reduce((s, a) => s + (a.target_weight || 0), 0)
  return (sum / total) * 100
}

function togglePlanExpand(pf) { expandedPlan.value = expandedPlan.value === pf.style ? null : pf.style }
function applyPlan(pf) { emit('apply', pf) }
</script>

<style scoped>
.panel-body { padding: var(--space-4) 0; }
.design-tabs { display: flex; gap: var(--space-1); margin-bottom: var(--space-4); background: var(--color-bg-tertiary); border-radius: var(--radius-md); padding: var(--space-1); }
.tab-btn { flex: 1; padding: var(--space-2) var(--space-4); border: none; background: transparent; font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); cursor: pointer; border-radius: var(--radius-sm); transition: all var(--transition-fast); }
.tab-btn.active { background: var(--color-surface-primary, #fff); color: var(--color-primary); box-shadow: var(--shadow-sm); }
.tab-btn:hover:not(.active) { color: var(--color-text-primary); }

.history-badge { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3); background: #fff3e0; border: 1px solid #ffcc80; border-radius: var(--radius-md); font-size: var(--font-size-sm); color: #e65100; font-weight: var(--font-weight-medium); }

.design-report { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.report-waiting { text-align: center; padding: var(--space-8) var(--space-4); }
.waiting-spinner { width: 40px; height: 40px; margin: 0 auto var(--space-4); border: 3px solid var(--color-bg-tertiary); border-top-color: var(--color-primary); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.waiting-text { font-size: var(--font-size-base); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0 0 var(--space-2); }
.waiting-hint { font-size: var(--font-size-sm); color: var(--color-text-tertiary); margin: 0; }
.report-stale, .report-error { text-align: center; padding: var(--space-6) var(--space-4); background: #fff8f0; border: 1px solid #ffe0b2; border-radius: var(--radius-md); }
.report-error { background: #ffebee; border-color: #ffcdd2; }
.error-text { font-size: var(--font-size-base); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-2); color: var(--color-text-primary); }
.error-detail { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0 0 var(--space-4); line-height: 1.5; }

.footer-actions { display: flex; gap: var(--space-3); margin-top: var(--space-4); justify-content: center; }

.result-hint { font-size: var(--font-size-sm); color: var(--color-text-tertiary); margin-bottom: var(--space-3); }
.plans-grid { display: flex; flex-direction: column; gap: var(--space-4); }

.plan-card { background: var(--color-surface-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-4); cursor: pointer; transition: all var(--transition-normal); }
.plan-card:hover { box-shadow: var(--shadow-md); }
.plan-card.expanded { border-color: var(--color-primary); box-shadow: var(--shadow-md); }

.plan-header { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2); }
.plan-icon { font-size: 1.5em; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; border-radius: var(--radius-md); background: var(--color-bg-tertiary); flex-shrink: 0; }
.plan-icon--defensive { background: #e8f5e9; }
.plan-icon--balanced { background: #e3f2fd; }
.plan-icon--aggressive { background: #ffebee; }
.plan-header-text { flex: 1; }
.plan-style-name { font-size: var(--font-size-lg); font-weight: var(--font-weight-bold); color: var(--color-text-primary); display: block; }
.plan-pf-name { font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.plan-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
.plan-pos { font-size: var(--font-size-sm); color: var(--color-text-tertiary); margin-bottom: var(--space-3); line-height: 1.4; }

.layer-bars { margin-bottom: var(--space-3); }
.layer-bar-section { display: flex; height: 12px; border-radius: var(--radius-full); overflow: hidden; background: var(--color-bg-tertiary); gap: 2px; }
.lbar--core { background: #1976D2; }
.lbar--satellite { background: #FF9800; }
.lbar--defense { background: #43A047; }
.layer-legend { display: flex; gap: var(--space-4); margin-top: var(--space-1); font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.ldot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.ldot--core { background: #1976D2; }
.ldot--satellite { background: #FF9800; }
.ldot--defense { background: #43A047; }

.plan-metrics { display: flex; gap: var(--space-4); padding: var(--space-2) 0; border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); margin-bottom: var(--space-3); }
.metric { display: flex; flex-direction: column; align-items: center; }
.m-label { font-size: var(--font-size-2xs); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.m-val { font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); }
.text-up { color: #E53935; }
.text-down { color: #43A047; }

.plan-hld-preview { margin-bottom: var(--space-3); }
.hld-row { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-1) 0; font-size: var(--font-size-sm); }
.hld-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.hld-name { flex: 1; color: var(--color-text-primary); }
.hld-w { font-weight: var(--font-weight-semibold); color: var(--color-text); }
.hld-more { color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.plan-action { margin-top: var(--space-2); display: flex; justify-content: flex-end; }

.plan-expanded { margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--color-border); }
.detail-section { margin-bottom: var(--space-4); }
.detail-title { font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-2); color: var(--color-text-primary); }

.hld-table { width: 100%; border-collapse: collapse; font-size: var(--font-size-sm); }
.hld-table th, .hld-table td { padding: var(--space-1) var(--space-2); text-align: left; border-bottom: 1px solid var(--color-border); }
.hld-table th { font-weight: var(--font-weight-semibold); color: var(--color-text-secondary); white-space: nowrap; }
.w-badge { font-weight: var(--font-weight-semibold); color: var(--color-text); }
.ll-text { margin-left: 4px; font-size: var(--font-size-xs); }
.rat-cell { font-size: var(--font-size-xs); color: var(--color-text-tertiary); max-width: 200px; }
.rat-text { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0 0 var(--space-1); line-height: 1.5; }
.risk-list { margin: 0; padding-left: var(--space-5); font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.risk-list li { margin-bottom: var(--space-1); line-height: 1.5; }
</style>

<!-- Non-scoped: styles for v-html rendered markdown content -->
<style>
.markdown-body { font-size: var(--font-size-sm); line-height: 1.7; color: var(--color-text-primary); padding: var(--space-3) 0; }
.markdown-body h1 { font-size: var(--font-size-xl); font-weight: var(--font-weight-bold); margin: var(--space-6) 0 var(--space-3); padding-bottom: var(--space-2); border-bottom: 2px solid var(--color-primary); color: var(--color-text-primary); }
.markdown-body h2 { font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); margin: var(--space-5) 0 var(--space-3); padding: var(--space-2) var(--space-3); background: var(--color-bg-tertiary); border-left: 3px solid var(--color-primary); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; color: var(--color-text-primary); }
.markdown-body h3 { font-size: var(--font-size-base); font-weight: var(--font-weight-semibold); margin: var(--space-4) 0 var(--space-2); color: var(--color-primary); }
.markdown-body table { width: 100%; border-collapse: collapse; margin: var(--space-3) 0 var(--space-4); font-size: var(--font-size-sm); }
.markdown-body th { background: var(--color-bg-tertiary); font-weight: var(--font-weight-semibold); padding: var(--space-2) var(--space-3); text-align: left; border: 1px solid var(--color-border); color: var(--color-text-primary); font-size: var(--font-size-sm); }
.markdown-body td { padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border); vertical-align: top; }
.markdown-body tr:nth-child(even) { background: var(--color-bg-secondary); }
.markdown-body tr:hover { background: var(--color-bg-tertiary); }
.markdown-body blockquote { margin: var(--space-3) 0; padding: var(--space-3) var(--space-4); background: var(--color-bg-tertiary); border-left: 4px solid var(--color-primary); border-radius: var(--radius-sm); color: var(--color-text-secondary); font-size: var(--font-size-sm); line-height: 1.6; }
.markdown-body ul { padding-left: var(--space-5); margin: var(--space-2) 0; }
.markdown-body li { margin-bottom: var(--space-1); line-height: 1.6; }
.markdown-body strong { font-weight: var(--font-weight-semibold); color: var(--color-text); }
.markdown-body code { background: var(--color-bg-tertiary); padding: 1px 4px; border-radius: 3px; font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace; font-size: 0.9em; color: var(--color-primary); }
.markdown-body hr { border: none; border-top: 1px solid var(--color-border); margin: var(--space-5) 0; }
.markdown-body p { margin: var(--space-2) 0; line-height: 1.7; }
.markdown-body > *:first-child { margin-top: 0; }
</style>
