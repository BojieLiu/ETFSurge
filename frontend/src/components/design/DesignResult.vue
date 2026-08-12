<template>
  <div class="panel-body design-result">
    <div v-if="isHistory && createdAt" class="history-badge">
      &#128214; 历史方案（{{ formatDate(createdAt) }}）
    </div>

    <!-- P2-8 (round17): 数据源冷却告警——degradation **实际降级**（mode≠normal 或
         pool_degraded）时显式提示（非静默降级）；Z11 正常路径也返回
         degradation={mode:'normal'} → 不渲染（不误报，负向断言覆盖） -->
    <div v-if="degradation && (degradation.mode !== 'normal' || degradation.pool_degraded)" class="degradation-banner" role="alert">
      <span class="degradation-icon">⚠️</span>
      <div class="degradation-body">
        <span class="degradation-title">数据源冷却，部分标的为降级数据</span>
        <span v-if="degradation.mode" class="degradation-detail">
          （{{ degradation.mode }}<template v-if="degradation.pool_degraded"> · 候选池降级</template>）
        </span>
      </div>
    </div>

    <AppTabs :tabs="appTabs" v-model="tab" variant="line" size="sm" ariaLabel="设计结果" class="design-result-tabs">
      <template #report>
        <div class="design-report">
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
      </template>

      <template #cards>
        <div class="design-cards">
          <p class="result-hint">共生成 {{ plans.length }} 个方案，点击卡片展开详情</p>
          <div class="plans-grid">
            <article v-for="pf in plans" :key="pf.style"
              :class="['plan-card', { expanded: expandedPlan === pf.style }]"
              @click="togglePlanExpand(pf)"
            >
              <div class="plan-header">
                <div :class="['plan-icon', 'plan-icon--' + planStyleKey(pf.style)]" aria-hidden="true">
                  {{ planIcon(pf.style) }}
                </div>
                <div class="plan-meta">
                  <h3 class="plan-name">{{ pf.style || pf.name }}方案</h3>
                  <div class="plan-stats">
                    <span class="stat-item">{{ etfCount(pf.allocations) }} 只 ETF</span>
                    <span class="stat-divider">·</span>
                    <span class="stat-item">核心 {{ calcLayerWeight(pf.allocations, 'core').toFixed(0) }}%</span>
                    <span class="stat-divider">·</span>
                    <span class="stat-item">卫星 {{ calcLayerWeight(pf.allocations, 'satellite').toFixed(0) }}%</span>
                    <span class="stat-divider">·</span>
                    <span class="stat-item">防御 {{ calcLayerWeight(pf.allocations, 'defense').toFixed(0) }}%</span>
                    <!-- round14 P2-V: 现金仓位显性化（引擎表格已有汇总行，卡片 header 同步展示） -->
                    <span v-if="cashWeight(pf.allocations) > 0" class="stat-divider">·</span>
                    <span v-if="cashWeight(pf.allocations) > 0" class="stat-item">现金 {{ cashWeight(pf.allocations).toFixed(0) }}%</span>
                  </div>
                </div>
                <AppButton variant="primary" size="sm" @click.stop="applyPlan(pf)" :loading="applying">应用此方案</AppButton>
              </div>

              <div v-if="expandedPlan === pf.style" class="plan-detail">
                <div class="plan-allocation">
                  <table class="alloc-table">
                    <thead>
                      <tr>
                        <th>代码</th>
                        <th>名称</th>
                        <th>权重</th>
                        <th>层</th>
                        <th>今日涨跌<template v-if="fetchedAtLabel"> <span class="fetched-at">{{ fetchedAtLabel }}</span></template></th>
                        <th><span class="factor-col-head" title="因子综合分（区别于技术信号，基于 33 维因子模型）">因子分</span></th>
                        <th>入选理由</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="a in pf.allocations" :key="a.symbol">
                        <td><code>{{ a.symbol }}</code></td>
                        <td>{{ a.name }}</td>
                        <td>{{ (a.target_weight * 100).toFixed(1) }}%</td>
                        <td><span class="layer-badge" :class="a.layer || 'satellite'">{{ layerLabel(a.layer) }}</span></td>
                        <td>
                          <!-- round14 P2-W: 缺失原因显性化——dcp=null 显示「数据源不可用」
                               而非可能误读为 0% 的「—」；CASH 行无涨跌幅语义，整行跳过 -->
                          <template v-if="a.symbol !== 'CASH'">
                            <span v-if="a.daily_change_pct != null" :class="a.daily_change_pct >= 0 ? 'text-up' : 'text-down'">
                              {{ a.daily_change_pct >= 0 ? '+' : '' }}{{ a.daily_change_pct.toFixed(2) }}%
                            </span>
                            <span v-else class="muted data-unavailable">数据源不可用</span>
                          </template>
                          <span v-else class="muted">—</span>
                        </td>
                        <td>
                          <!-- P2-6 (round17): 因子综合分连续值（可为负，如 -0.17 中性）——
                               区别于技术信号（buy/hold/sell），列头 tooltip 已注明口径 -->
                          <span v-if="a.factor_score != null" :class="a.factor_score >= 0 ? 'text-up' : 'text-down'">
                            {{ a.factor_score >= 0 ? '+' : '' }}{{ a.factor_score.toFixed(2) }}
                          </span>
                          <span v-else class="muted">—</span>
                        </td>
                        <td class="rationale-cell">{{ a.rationale || '—' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div v-if="pf.risk_factors && pf.risk_factors.length" class="plan-risk">
                  <h4 class="risk-title">&#9888;&#65039; 风险因素</h4>
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
      </template>
    </AppTabs>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { formatDate } from '../../utils/formatDate'
import { renderMarkdown } from '../../utils/markdown'
import AppButton from '../ui/AppButton.vue'
import AppTabs from '../ui/AppTabs.vue'

const props = defineProps({
  plans: { type: Array, default: () => [] },
  designText: { type: String, default: '' },
  isHistory: { type: Boolean, default: false },
  createdAt: { type: String, default: '' },
  reportQuality: { type: String, default: 'pending' },
  reportError: { type: String, default: '' },
  // round10 P2-D: 行情数据采集时刻（market_context.data_fetched_at，后端 P0-9 注入）——
  // 表头「今日涨跌」后标注「截至 HH:MM」，盘中值可追溯、不被误读为收盘
  dataFetchedAt: { type: String, default: '' },
  // P2-8 (round17): 数据源降级标记（get_design 顶层透传 / market_context.degradation）——
  // 存在时顶部显示冷却提示；undefined/null 不渲染（不误报）
  degradation: { type: Object, default: null },
})

const emit = defineEmits(['apply', 'regenerate', 'close', 'retry-report'])

const tab = ref('cards')

const appTabs = [
  { value: 'report', label: '完整报告' },
  { value: 'cards', label: '方案卡片' }
]

const applying = ref(false)
const expandedPlan = ref(null)

const reportHtml = computed(() => props.designText ? renderMarkdown(props.designText) : '')

// round10 P2-D: data_fetched_at → 「截至 HH:MM」标注（非当日显示完整日期）
const fetchedAtLabel = computed(() => {
  if (!props.dataFetchedAt) return ''
  try {
    const d = new Date(props.dataFetchedAt)
    if (Number.isNaN(d.getTime())) return ''
    const now = new Date()
    const sameDay = d.getFullYear() === now.getFullYear()
      && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate()
    const hhmm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    return sameDay ? `截至 ${hhmm}` : `截至 ${d.getMonth() + 1}/${d.getDate()} ${hhmm}`
  } catch {
    return ''
  }
})

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

// round14 P2-V: ETF 计数排除 CASH（CASH 是现金仓位非 ETF，旧实现计入导致
// 「10 只 ETF」实为 9 ETF + 1 CASH）；现金仓位单独展示
function etfCount(allocations) {
  if (!allocations) return 0
  return allocations.filter(a => a.symbol !== 'CASH').length
}
function cashWeight(allocations) {
  if (!allocations) return 0
  const cash = allocations.find(a => a.symbol === 'CASH')
  return cash ? (cash.target_weight || 0) * 100 : 0
}

function togglePlanExpand(pf) { expandedPlan.value = expandedPlan.value === pf.style ? null : pf.style }
function applyPlan(pf) {
  applying.value = true
  emit('apply', pf)
}
</script>

<style scoped>
.panel-body { padding: var(--space-4) 0; }
.design-result-tabs { margin-bottom: var(--space-4); }

.history-badge { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3); background: #fff3e0; border: 1px solid #ffcc80; border-radius: var(--radius-md); font-size: var(--font-size-sm); color: #e65100; font-weight: var(--font-weight-medium); }

/* P2-8 (round17): 数据源冷却告警条——黄色警示（不阻断查看方案，仅显式标注降级） */
.degradation-banner { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3); background: #fff8e1; border: 1px solid #ffe082; border-radius: var(--radius-md); font-size: var(--font-size-sm); color: #8d6e00; }
.degradation-icon { font-size: var(--font-size-base); }
.degradation-body { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); }
.degradation-title { font-weight: var(--font-weight-medium); }
.degradation-detail { font-size: var(--font-size-xs); color: #a0820a; }

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
.plan-meta { flex: 1; min-width: 0; }
.plan-name { margin: 0; font-size: var(--font-size-base); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.plan-stats { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); margin-top: var(--space-1); font-size: var(--font-size-xs); color: var(--color-text-secondary); }
.stat-divider { color: var(--color-text-tertiary); }

.plan-detail { margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--color-border-light); }
.alloc-table { width: 100%; border-collapse: collapse; font-size: var(--font-size-xs); }
.alloc-table th, .alloc-table td { padding: var(--space-2) var(--space-3); text-align: left; border-bottom: 1px solid var(--color-border-light); }
.alloc-table th { font-weight: var(--font-weight-semibold); color: var(--color-text-secondary); background: var(--color-surface-secondary); white-space: nowrap; }
.alloc-table th .fetched-at { font-weight: var(--font-weight-regular); font-size: 0.85em; color: var(--color-text-tertiary, #999); }
.alloc-table td code { font-family: var(--font-family-mono); background: var(--color-surface-tertiary); padding: 1px 4px; border-radius: var(--radius-sm); }
.rationale-cell { max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-text-secondary); font-size: 0.9em; }
.layer-badge { display: inline-flex; align-items: center; padding: var(--space-0.5) var(--space-2); font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); border-radius: var(--radius-full); }
.layer-badge.core { color: #c62828; background: #ffebee; }
.layer-badge.satellite { color: #1565c0; background: #e3f2fd; }
.layer-badge.defense { color: #2e7d32; background: #e8f5e9; }

.plan-risk { margin-top: var(--space-3); }
.risk-title { margin: 0 0 var(--space-2); font-size: var(--font-size-sm); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.risk-list { margin: 0; padding-left: var(--space-4); font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.risk-list li { margin-bottom: var(--space-1); }

.markdown-body { font-size: var(--font-size-sm); line-height: 1.8; color: var(--color-text-primary); }

/* Headings */
.markdown-body h1 { font-size: 1.4em; margin: var(--space-5) 0 var(--space-3); padding-bottom: var(--space-2); border-bottom: 2px solid var(--color-primary); color: var(--color-text-primary); font-weight: var(--font-weight-bold); }
.markdown-body h2 { font-size: 1.2em; margin: var(--space-5) 0 var(--space-3); padding-bottom: var(--space-1); border-bottom: 1px solid var(--color-border); color: var(--color-text-primary); font-weight: var(--font-weight-semibold); }
.markdown-body h3 { font-size: 1.1em; margin: var(--space-4) 0 var(--space-2); color: var(--color-text-primary); font-weight: var(--font-weight-semibold); }
.markdown-body h4 { font-size: 1em; margin: var(--space-3) 0 var(--space-2); color: var(--color-text-secondary); font-weight: var(--font-weight-semibold); }

/* Paragraphs */
.markdown-body p { margin: var(--space-2) 0; line-height: 1.8; }

/* Emphasis */
.markdown-body strong { font-weight: var(--font-weight-bold); color: var(--color-text-primary); }
.markdown-body em { font-style: italic; color: var(--color-text-secondary); }

/* Lists */
.markdown-body ul, .markdown-body ol { padding-left: var(--space-5); margin: var(--space-2) 0; }
.markdown-body li { margin: var(--space-1) 0; line-height: 1.7; }
.markdown-body li > p { margin: 0; }
.markdown-body ul ul, .markdown-body ol ol, .markdown-body ul ol, .markdown-body ol ul { margin: 0; }

/* Inline code */
.markdown-body code { background: var(--color-bg-tertiary); padding: 2px 6px; border-radius: var(--radius-sm); font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace; font-size: 0.88em; color: var(--color-primary); }

/* Code blocks */
.markdown-body pre { background: #1e1e2e; color: #cdd6f4; padding: var(--space-4); border-radius: var(--radius-md); overflow-x: auto; margin: var(--space-4) 0; font-size: 0.88em; line-height: 1.6; }
.markdown-body pre code { background: transparent; padding: 0; border-radius: 0; color: inherit; font-size: inherit; }

/* Tables - Comprehensive styling */
.markdown-body table { width: 100%; border-collapse: collapse; margin: var(--space-4) 0; font-size: 0.92em; display: block; overflow-x: auto; }
.markdown-body thead { background: var(--color-surface-secondary); }
.markdown-body th { padding: var(--space-2) var(--space-3); text-align: left; font-weight: var(--font-weight-semibold); color: var(--color-text-primary); border-bottom: 2px solid var(--color-primary); white-space: nowrap; }
.markdown-body td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border-light); color: var(--color-text-primary); }
.markdown-body tbody tr:hover { background: var(--color-bg-tertiary); }
.markdown-body tbody tr:nth-child(even) { background: rgba(0,0,0,0.02); }
.markdown-body tbody tr:nth-child(even):hover { background: var(--color-bg-tertiary); }

/* Blockquotes */
.markdown-body blockquote { margin: var(--space-3) 0; padding: var(--space-3) var(--space-4); border-left: 4px solid var(--color-primary); background: var(--color-bg-tertiary); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; color: var(--color-text-secondary); }
.markdown-body blockquote p { margin: var(--space-1) 0; }

/* Horizontal rule */
.markdown-body hr { border: none; border-top: 1px solid var(--color-border); margin: var(--space-5) 0; }

/* Images */
.markdown-body img { max-width: 100%; height: auto; border-radius: var(--radius-md); margin: var(--space-3) 0; }

/* First element reset */
.markdown-body > *:first-child { margin-top: 0; }

/* Last element reset */
.markdown-body > *:last-child { margin-bottom: 0; }
</style>
