<template>
  <section class="card core-actions" :class="{ 'core-actions--collapsed': collapsed }">
    <div class="card-header" @click="toggleCollapse">
      <h2 class="card-title">
        <span class="card-title-icon" aria-hidden="true">&#9889;</span>
        AI 智能工具
      </h2>
      <div class="card-header-right">
        <span v-if="collapsed && activeCoreFeature" class="header-hint">
          {{ activeCoreFeature === 'design' ? '智能设计 - 点击展开' : '策略检查 - 点击展开' }}
        </span>
        <span v-else-if="collapsed" class="header-hint">点击展开工具</span>
        <button class="collapse-toggle" @click.stop="toggleCollapse" :aria-label="collapsed ? '展开AI工具' : '收起AI工具'" :title="collapsed ? '展开' : '收起'">
          <span class="collapse-icon" :class="{ 'collapse-icon--open': !collapsed }" aria-hidden="true">&#9662;</span>
        </button>
      </div>
    </div>

    <div v-show="!collapsed" class="core-actions-body">
      <!-- Feature Entrances -->
      <div v-if="!activeCoreFeature" class="core-actions-grid">
        <button class="core-action-btn" @click="enterDesignMode" :disabled="designStep === 'loading'" aria-label="智能设计 ETF 组合方案">
          <span class="action-icon" aria-hidden="true">&#10024;</span>
          <div class="action-content">
            <span class="action-title">智能设计ETF组合方案</span>
            <span class="action-desc">输入资金，一键生成进攻/平衡/防御三种风格组合</span>
          </div>
          <span v-if="designStep === 'loading'" class="action-loading" aria-hidden="true">&#9203;</span>
        </button>

        <button class="core-action-btn" @click="enterStrategyMode" :disabled="checkingStrategy">
          <span class="action-icon" aria-hidden="true">&#127919;</span>
          <div class="action-content">
            <span class="action-title">策略检查分析</span>
            <span class="action-desc">分析当前组合，优化权重与持仓</span>
          </div>
        </button>
      </div>

      <!-- Design Wizard -->
      <div v-else-if="activeCoreFeature === 'design' && designStep === 'wizard'" class="panel-body design-wizard">
        <div class="feature-card">
          <div class="feature-card-header">
            <span class="feature-card-icon" aria-hidden="true">&#10024;</span>
            <div>
              <h3 class="feature-card-title">智能组合设计</h3>
              <p class="feature-card-subtitle">输入资金，一键生成进攻/平衡/防御三种风格的 ETF 组合方案</p>
            </div>
          </div>

          <div class="feature-card-body">
            <div class="capital-input-section">
              <label class="capital-label">
                <span class="capital-currency">&#165;</span>
                <span>投资金额</span>
              </label>
              <div class="capital-input-wrapper">
                <AppInput type="number" v-model="designCapital" min="10000" step="10000" />
              </div>
              <p class="capital-hint">建议 10 万元以上以获得更好的分散效果</p>

              <div class="capital-presets">
                <button
                  v-for="amt in [100000, 500000, 1000000]"
                  :key="amt"
                  class="preset-btn"
                  :class="{ active: Number(designCapital) === amt }"
                  @click="designCapital = amt"
                >{{ (amt / 10000).toFixed(0) }}万</button>
              </div>
            </div>

            <div class="wizard-actions-center">
              <AppButton variant="primary" size="lg" @click="startDesign" :disabled="!designCapital || designCapital < 10000">
                &#10024; 开始设计
              </AppButton>
              <AppButton variant="ghost" @click="exitCoreFeature">取消</AppButton>
            </div>
          </div>

          <div class="feature-card-footer">
            <span>流程：扫描全市场 ETF &#8594; 三层筛选 &#8594; LLM 精选 &#8594; 三套方案</span>
          </div>
        </div>
      </div>

      <!-- Loading State -->
      <div v-else-if="designStep === 'loading'" class="panel-body design-loading">
        <div class="feature-card loading-card">
          <div class="loading-spinner"></div>
          <h3 class="loading-title">正在生成组合方案</h3>
          <p class="loading-text">{{ loadingText }}</p>
          <div class="loading-progress">
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: loadingProgress + '%' }"></div>
            </div>
            <span class="progress-percent">{{ loadingProgress }}%</span>
          </div>
          <div class="loading-steps">
            <div class="loading-step" :class="{ done: loadingProgress >= 30 }">
              <span class="step-dot"></span> 采集全市场数据
            </div>
            <div class="loading-step" :class="{ done: loadingProgress >= 60 }">
              <span class="step-dot"></span> 筛选候选标的
            </div>
            <div class="loading-step" :class="{ done: loadingProgress >= 90 }">
              <span class="step-dot"></span> 生成组合方案
            </div>
          </div>
        </div>
      </div>

      <!-- Result Step -->
      <div v-else-if="designStep === 'result' && designResult?.plans?.length" class="panel-body design-result">
        <div class="design-tabs">
          <button class="design-tab" :class="{ active: designTab === 'report' }" @click="designTab = 'report'">&#128196; 完整报告</button>
          <button class="design-tab" :class="{ active: designTab === 'cards' }" @click="designTab = 'cards'">&#128202; 方案卡片</button>
        </div>

        <!-- Tab: Report -->
        <div v-if="designTab === 'report'" class="design-report">
          <div class="markdown-body" v-html="designReportHtml"></div>
          <div class="panel-footer-actions">
            <AppButton variant="ghost" @click="resetDesign">重新生成</AppButton>
            <AppButton variant="ghost" @click="exitCoreFeature">完成</AppButton>
          </div>
        </div>

        <!-- Tab: Cards -->
        <div v-if="designTab === 'cards'" class="design-cards">
          <p class="result-hint">共生成 {{ designResult.plans.length }} 个方案，点击卡片展开详情</p>

          <div class="design-plans-grid">
            <article v-for="pf in designResult.plans" :key="pf.style"
              :class="['design-plan-card', { expanded: expandedPlan === pf.style }]"
              @click="togglePlanExpand(pf)">
              
              <!-- Card Header -->
              <div class="plan-header">
                <span class="plan-icon" :class="'plan-icon--' + planStyleKey(pf.style)">{{ planIcon(pf.style) }}</span>
                <div class="plan-header-text">
                  <span class="plan-style-name">{{ pf.style || pf.style_label }}</span>
                  <span class="plan-portfolio-name">{{ pf.portfolio_name || '' }}</span>
                </div>
                <span class="plan-color-dot" :style="{ background: planColor(pf.style) }"></span>
              </div>
              <div class="plan-positioning">{{ pf.positioning }}</div>

              <!-- Layer allocation bar -->
              <div class="plan-layer-bars" v-if="pf.allocations">
                <div class="layer-bar-section">
                  <div v-for="layer in ['core', 'satellite', 'defense']" :key="layer"
                    class="layer-bar" :class="'layer-bar--' + layer"
                    :style="{ width: calcLayerWeight(pf.allocations, layer) + '%' }"
                    :title="layerLabel(layer) + ': ' + calcLayerWeight(pf.allocations, layer).toFixed(0) + '%'">
                  </div>
                </div>
                <div class="layer-legend">
                  <span v-for="layer in ['core', 'satellite', 'defense']" :key="layer" class="layer-legend-item">
                    <span class="layer-dot" :class="'layer-dot--' + layer"></span>
                    {{ layerLabel(layer) }} {{ calcLayerWeight(pf.allocations, layer).toFixed(0) }}%
                  </span>
                </div>
              </div>

              <!-- Key Metrics -->
              <div class="plan-metrics" v-if="pf.expected_return != null || pf.max_drawdown != null || pf.sharpe_ratio != null">
                <div class="metric" v-if="pf.expected_return != null">
                  <span class="metric-label">预期年化</span>
                  <span class="metric-value text-up">{{ (pf.expected_return * 100).toFixed(1) }}%</span>
                </div>
                <div class="metric" v-if="pf.max_drawdown != null">
                  <span class="metric-label">最大回撤</span>
                  <span class="metric-value text-down">{{ (Math.abs(pf.max_drawdown) * 100).toFixed(1) }}%</span>
                </div>
                <div class="metric" v-if="pf.sharpe_ratio != null">
                  <span class="metric-label">夏普比率</span>
                  <span class="metric-value">{{ pf.sharpe_ratio.toFixed(2) }}</span>
                </div>
              </div>

              <!-- Top Holdings -->
              <div class="plan-holdings-preview" v-if="pf.allocations?.length">
                <div v-for="a in pf.allocations.slice(0, 5)" :key="a.symbol" class="holding-row">
                  <span class="holding-layer-dot" :class="'layer-dot--' + (a.layer || 'satellite')"></span>
                  <span class="holding-name">{{ a.name || a.symbol }}</span>
                  <span class="holding-weight">{{ (a.target_weight * 100).toFixed(1) }}%</span>
                </div>
                <div v-if="pf.allocations.length > 5" class="holding-row holding-more">+{{ pf.allocations.length - 5 }} 只更多</div>
              </div>

              <div class="plan-action">
                <AppButton variant="primary" size="md" @click.stop="applyPortfolioDesign(pf)" :disabled="applyingPlan === pf.style">
                  {{ applyingPlan === pf.style ? '应用加载中...' : '应用此方案' }}
                </AppButton>
              </div>

              <!-- Expandable Details -->
              <div v-if="expandedPlan === pf.style" class="plan-expanded-detail" @click.stop>
                <div class="detail-section" v-if="pf.allocations?.length">
                  <h4 class="detail-title">完整持仓明细</h4>
                  <div class="holdings-table-wrapper">
                    <table class="holdings-table">
                      <thead><tr><th>层</th><th>代码</th><th>名称</th><th>权重</th><th>配置逻辑</th></tr></thead>
                      <tbody>
                        <tr v-for="a in pf.allocations" :key="a.symbol">
                          <td><span class="layer-dot" :class="'layer-dot--' + (a.layer || 'satellite')"></span></td>
                          <td><code>{{ a.symbol }}</code></td>
                          <td>{{ a.name || '&mdash;' }}</td>
                          <td><span class="weight-badge">{{ (a.target_weight * 100).toFixed(1) }}%</span></td>
                          <td class="rationale-cell">{{ a.selection_rationale || '&mdash;' }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
                <div class="detail-section" v-if="pf.allocation_rationale">
                  <h4 class="detail-title">配置逻辑</h4>
                  <p class="rationale-text">{{ pf.allocation_rationale.asset_class_allocation || '&mdash;' }}</p>
                  <p class="rationale-text" v-if="pf.allocation_rationale.equity_style_tilt">风格倾向：{{ pf.allocation_rationale.equity_style_tilt }}</p>
                </div>
                <div class="detail-section" v-if="pf.risk_factors?.length">
                  <h4 class="detail-title">风险因素</h4>
                  <ul class="risk-list"><li v-for="rf in pf.risk_factors" :key="rf">{{ rf }}</li></ul>
                </div>
              </div>
            </article>
          </div>

          <div class="design-cards-actions">
            <AppButton variant="ghost" @click="resetDesign">重新生成</AppButton>
            <AppButton variant="ghost" @click="exitCoreFeature">完成</AppButton>
          </div>
        </div>
      </div>

      <!-- Strategy Check -->
      <div v-else-if="activeCoreFeature === 'strategy' && !checkingStrategy && !strategyResult" class="panel-body">
        <div class="feature-card">
          <div class="feature-card-header">
            <span class="feature-card-icon" aria-hidden="true">&#127919;</span>
            <div>
              <h3 class="feature-card-title">策略检查分析</h3>
              <p class="feature-card-subtitle">分析当前组合的权重偏离、行业集中度、风险暴露，提供优化建议</p>
            </div>
          </div>
          <div class="feature-card-body">
            <div class="strategy-check-info">
              <div class="info-row">
                <span class="info-icon">&#128200;</span>
                <span>权重偏离度检查 - 发现偏离目标权重的标的</span>
              </div>
              <div class="info-row">
                <span class="info-icon">&#128202;</span>
                <span>行业集中度分析 - 评估组合是否过度集中在某行业</span>
              </div>
              <div class="info-row">
                <span class="info-icon">&#9888;&#65039;</span>
                <span>风险暴露评估 - 识别潜在风险点</span>
              </div>
            </div>
            <div class="wizard-actions-center">
              <AppButton variant="primary" size="lg" @click="checkStrategy">
                &#127919; 开始检查
              </AppButton>
              <AppButton variant="ghost" @click="exitCoreFeature">取消</AppButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import { portfolioApi } from '../api'
import { usePortfolioStore } from '../stores/portfolio'
import { useToastStore } from '../stores/toast'
import AppButton from './ui/AppButton.vue'
import AppInput from './ui/AppInput.vue'

const emit = defineEmits(['applied'])
const store = usePortfolioStore()
const toast = useToastStore()

// State
const collapsed = ref(false)
const activeCoreFeature = ref(null)
const designStep = ref('wizard')
const designCapital = ref(500000)
const designResult = ref(null)
const designTab = ref('cards')
const expandedPlan = ref(null)
const applyingPlan = ref(null)
const loadingProgress = ref(0)
const loadingText = ref('正在采集数据...')
const checkingStrategy = ref(false)
const strategyResult = ref(null)

const designReportHtml = computed(() => {
  if (!designResult.value?.design_text) return ''
  return marked(designResult.value.design_text)
})

// Helpers
const planIcon = (style) => {
  const icons = { defensive: '\u{1F6E1}\uFE0F', balanced: '\u2696\uFE0F', aggressive: '\u2694\uFE0F' }
  return icons[planStyleKey(style)] || '\u{1F4CA}'
}

const planColor = (style) => {
  const colors = { defensive: '#43A047', balanced: '#1976D2', aggressive: '#E53935' }
  return colors[planStyleKey(style)] || '#888'
}

const planStyleKey = (style) => {
  if (!style) return 'balanced'
  const map = { '\u9632\u5fa1\u578b': 'defensive', '\u9632\u5fa1': 'defensive', defensive: 'defensive' }
  map['\u5e73\u8861\u578b'] = 'balanced'
  map['\u5e73\u8861'] = 'balanced'
  map['\u8fdb\u653b\u578b'] = 'aggressive'
  map['\u8fdb\u653b'] = 'aggressive'
  return map[style] || 'balanced'
}

const layerLabel = (layer) => {
  const labels = { core: '\u6838\u5fc3', satellite: '\u536b\u661f', defense: '\u9632\u5fa1' }
  return labels[layer] || layer
}

const calcLayerWeight = (allocations, layer) => {
  if (!allocations) return 0
  const total = allocations
    .filter(a => (a.layer || '').toLowerCase() === layer.toLowerCase())
    .reduce((sum, a) => sum + (a.target_weight || 0), 0)
  return Math.round(total * 100)
}

function generateDesignReport(plans) {
  if (!plans || !plans.length) return ''
  const ml = (v) => (v != null ? (v * 100).toFixed(0) + '%' : '—')
  let md = '# ETF 组合设计方案\n\n'
  md += '## 三方案概览\n\n'
  md += '| 维度 | ' + plans.map(p => p.style).join(' | ') + ' |\n'
  md += '|------|' + plans.map(() => '---|').join('') + '\n'
  md += '| 标的数量 | ' + plans.map(p => (p.allocations || []).length + '只').join(' | ') + ' |\n'
  md += '| 预期年化 | ' + plans.map(p => ml(p.expected_return)).join(' | ') + ' |\n'
  md += '| 最大回撤 | ' + plans.map(p => ml(p.max_drawdown)).join(' | ') + ' |\n'
  md += '| 夏普比率 | ' + plans.map(p => (p.sharpe_ratio != null ? p.sharpe_ratio.toFixed(2) : '—')).join(' | ') + ' |\n\n'
  plans.forEach(p => {
    md += '---\n\n'
    md += '## ' + p.style + '：' + (p.portfolio_name || '') + '\n\n'
    md += '**定位：**' + (p.positioning || '—') + '\n\n'
    md += '| 标的 | 代码 | 层级 | 权重 | 选择理由 |\n'
    md += '|------|------|------|------|---------|\n'
    ;(p.allocations || []).forEach(a => {
      md += '| ' + (a.name || '—') + ' | ' + a.symbol + ' | ' + layerLabel(a.layer) + ' | '
        + (a.target_weight != null ? (a.target_weight * 100).toFixed(1) + '%' : '—') + ' | '
        + (a.selection_rationale || '—') + ' |\n'
    })
    md += '\n'
  })
  md += '\n---\n*本报告由 ETF Surge 组合设计引擎自动生成*\n'
  return md
}

// Actions
function toggleCollapse() {
  collapsed.value = !collapsed.value
  if (collapsed.value) {
    activeCoreFeature.value = null
  }
}

function enterDesignMode() {
  activeCoreFeature.value = 'design'
  designStep.value = 'wizard'
  designCapital.value = 500000
  collapsed.value = false
}

function enterStrategyMode() {
  activeCoreFeature.value = 'strategy'
  collapsed.value = false
}

function exitCoreFeature() {
  activeCoreFeature.value = null
  // 取消时不收起工具区，直接返回工具列表
}

function resetDesign() {
  designResult.value = null
  designStep.value = 'wizard'
  designCapital.value = 500000
}

function togglePlanExpand(pf) {
  expandedPlan.value = expandedPlan.value === pf.style ? null : pf.style
}

async function startDesign() {
  designStep.value = 'loading'
  designResult.value = null
  loadingProgress.value = 10
  loadingText.value = '正在采集全市场数据...'

  try {
    loadingProgress.value = 30
    loadingText.value = '正在筛选候选标的...'

    loadingProgress.value = 50
    loadingText.value = '正在分析市场情绪...'

    loadingProgress.value = 70
    loadingText.value = '正在生成方案...'

    const res = await portfolioApi.design({
      capital: designCapital.value,
      mode: 'standard',
      constraints: { min_names: 8, max_names: 15 }
    })
    // Map backend response (strategies/etfs) to frontend format (plans/allocations)
    const data = res.data
    const plans = Array.isArray(data.strategies)
      ? data.strategies.map(s => ({
          style: s.label,
          style_label: s.label,
          portfolio_name: s.portfolio_name,
          positioning: s.positioning,
          expected_return: s.expected_return,
          max_drawdown: s.max_drawdown,
          sharpe_ratio: s.sharpe_ratio,
          risk_factors: [],
          rebalance_rules: '月度检视',
          allocations: Array.isArray(s.etfs)
            ? s.etfs.map(e => ({
                symbol: e.symbol,
                name: e.name,
                layer: e.layer,
                target_weight: e.weight,
                selection_rationale: e.selection_rationale || '',
                tracked_index: e.tracked_index || '',
                price: e.price,
                change_pct: e.change_pct,
              }))
            : [],
        }))
      : []
    designResult.value = {
      plans,
      design_text: generateDesignReport(plans),
      market_context: data.market_context || {},
      generated_at: data.generated_at,
    }
    loadingProgress.value = 100
    designStep.value = 'result'
    designTab.value = 'cards'
  } catch (e) {
    toast(e?.response?.data?.detail || '生成失败，请重试', 'error')
    designStep.value = 'wizard'
  }
}

async function applyPortfolioDesign(plan) {
  applyingPlan.value = plan.style
  try {
    const symbols = plan.allocations.map(a => a.symbol)
    const weights = {}
    plan.allocations.forEach(a => { weights[a.symbol] = a.target_weight })
    await portfolioApi.applyPortfolioDesign({ symbols, weights })
    toast('\u5e94\u7528\u6210\u529f\uff01', 'success')
    store.fetchEtfs()
    emit('applied')
  } catch (e) {
    toast('\u5e94\u7528\u5931\u8d25\uff1a' + (e?.response?.data?.detail || e.message), 'error')
  } finally {
    applyingPlan.value = null
  }
}

async function checkStrategy() {
  checkingStrategy.value = true
  try {
    const res = await portfolioApi.strategyCheck({ portfolio_type: 'on_exchange' })
    strategyResult.value = res.data
    toast('\u7b56\u7565\u68c0\u67e5\u5b8c\u6210', 'success')
  } catch (e) {
    toast('\u68c0\u67e5\u5931\u8d25\uff1a' + (e?.response?.data?.detail || e.message), 'error')
  } finally {
    checkingStrategy.value = false
  }
}
</script>

<style scoped>
.design-plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

@media (max-width: 1024px) {
  .design-plans-grid { grid-template-columns: 1fr; }
}

.design-plan-card {
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  cursor: pointer;
  transition: all var(--transition-normal);
  position: relative;
}

.design-plan-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.design-plan-card.expanded {
  grid-column: 1 / -1;
}

.plan-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.plan-icon {
  font-size: 1.8em;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
}

.plan-icon--defensive { background: #e8f5e9; }
.plan-icon--balanced { background: #e3f2fd; }
.plan-icon--aggressive { background: #ffebee; }

.plan-header-text {
  flex: 1;
}

.plan-style-name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  display: block;
}

.plan-portfolio-name {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.plan-color-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.plan-positioning {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-3);
  line-height: 1.4;
}

/* Layer allocation bar */
.plan-layer-bars {
  margin-bottom: var(--space-3);
}

.layer-bar-section {
  display: flex;
  height: 12px;
  border-radius: var(--radius-full);
  overflow: hidden;
  background: var(--color-bg-tertiary);
  gap: 2px;
}

.layer-bar--core { background: #1976D2; }
.layer-bar--satellite { background: #FF9800; }
.layer-bar--defense { background: #43A047; }

.layer-legend {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.layer-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}

.layer-dot--core { background: #1976D2; }
.layer-dot--satellite { background: #FF9800; }
.layer-dot--defense { background: #43A047; }

/* Key Metrics */
.plan-metrics {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-2) 0;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-3);
}

.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.metric-label {
  font-size: var(--font-size-2xs);
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
}

.metric-value {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
}

/* Holdings Preview */
.plan-holdings-preview {
  margin-bottom: var(--space-3);
}

.holding-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  font-size: var(--font-size-sm);
}

.holding-layer-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.holding-name {
  flex: 1;
  color: var(--color-text-primary);
}

.holding-weight {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.holding-more {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-xs);
}

.plan-action {
  margin-top: var(--space-2);
  display: flex;
  justify-content: flex-end;
}

/* Design tabs */
.design-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--color-border);
}

.design-tab {
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
  border: none;
  background: none;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  border-bottom: 2px solid transparent;
  transition: all var(--transition-normal);
}

.design-tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.design-card {
  padding: var(--space-4);
}

.card-header {
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  margin: 0;
}

.card-title-icon {
  margin-right: var(--space-2);
}

.core-actions-body {
  padding-top: var(--space-3);
}

.core-actions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-4);
}

.core-action-btn {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-6);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-normal);
  text-align: left;
  width: 100%;
  position: relative;
  overflow: hidden;
}

.core-action-btn::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--color-primary);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  opacity: 0;
  transition: opacity var(--transition-normal);
}

.core-action-btn:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-lg);
  transform: translateY(-1px);
}

.core-action-btn:hover::before {
  opacity: 1;
}

.action-icon {
  font-size: 2em;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
  flex-shrink: 0;
}

.action-content {
  flex: 1;
}

.action-title {
  display: block;
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.action-desc {
  display: block;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: 1.4;
}

.panel-body {
  padding: var(--space-4) 0;
}

/* Feature Card (Wizard / Loading / Strategy Check) */
.feature-card {
  max-width: 520px;
  margin: 0 auto;
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.feature-card-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-5) var(--space-3);
}

.feature-card-icon {
  font-size: 2em;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
  flex-shrink: 0;
}

.feature-card-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-1);
}

.feature-card-subtitle {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin: 0;
  line-height: 1.4;
}

.feature-card-body {
  padding: var(--space-3) var(--space-5) var(--space-5);
}

.capital-input-section {
  text-align: center;
  padding: var(--space-4) 0;
}

.capital-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  margin-bottom: var(--space-4);
}

.capital-currency {
  font-size: 1.5em;
  color: var(--color-primary);
}

.capital-input-wrapper {
  max-width: 240px;
  margin: 0 auto var(--space-3);
}

.capital-input-wrapper :deep(input) {
  text-align: center;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  padding: var(--space-3);
}

.capital-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin: 0 0 var(--space-4);
  text-align: center;
}

.capital-presets {
  display: flex;
  justify-content: center;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.preset-btn {
  padding: var(--space-1) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.preset-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.preset-btn.active {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
}

.wizard-actions-center {
  display: flex;
  justify-content: center;
  gap: var(--space-3);
}

.feature-card-footer {
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  font-size: var(--font-size-2xs);
  color: var(--color-text-tertiary);
  text-align: center;
}

/* Loading Card */
.loading-card {
  text-align: center;
  padding: var(--space-8);
}

.loading-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  margin: var(--space-4) 0 var(--space-2);
}

.loading-steps {
  margin-top: var(--space-5);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}

.loading-step {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

.loading-step.done {
  color: var(--color-primary);
  font-weight: var(--font-weight-medium);
}

.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-border);
}

.loading-step.done .step-dot {
  background: var(--color-primary);
}

/* Strategy Check Info */
.strategy-check-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) 0;
}

.info-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.info-icon {
  font-size: 1.2em;
  width: 28px;
  text-align: center;
  flex-shrink: 0;
}

.panel-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-4);
}

.capital-input-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.capital-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.wizard-actions {
  display: flex;
  gap: var(--space-3);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: var(--space-6) auto;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-text {
  text-align: center;
  color: var(--color-text-secondary);
  margin-bottom: var(--space-4);
}

.loading-progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--color-primary);
  border-radius: var(--radius-full);
  transition: width 0.3s ease;
}

.progress-percent {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  min-width: 30px;
  text-align: right;
}

.result-hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-3);
}

.holdings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.holdings-table th,
.holdings-table td {
  padding: var(--space-1) var(--space-2);
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.holdings-table th {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.weight-badge {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.text-up { color: #E53935; }
.text-down { color: #43A047; }

.panel-footer-actions,
.design-cards-actions {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-4);
  justify-content: center;
}
</style>
