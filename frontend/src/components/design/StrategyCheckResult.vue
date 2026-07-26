<template>
  <div class="panel-body">
    <!-- Loading state -->
    <div v-if="loading" class="loading-state">
      <div class="loading-header">
        <button class="sr-back" @click="$emit('close')">← 返回</button>
      </div>
      <TaskProgress
        :taskStatus="taskStatus"
        :taskProgress="taskProgress"
        :taskStage="taskStage"
        :errorMessage="error"
        @retry="$emit('close')"
        @cancel="$emit('close')"
      />
    </div>

    <!-- Error state -->
    <div v-else-if="error && !result" class="error-state">
      <p class="error-text">❌ {{ error }}</p>
      <AppButton variant="ghost" @click="$emit('close')">返回</AppButton>
    </div>

    <!-- Result -->
    <div v-else-if="result" class="strategy-result">
      <!-- header -->
      <div class="sr-header">
        <button class="sr-back" @click="$emit('close')">← 返回</button>
        <h3>策略检查结果</h3>
        <span class="regime-badge" :class="'regime-' + (result.market_regime || 'unknown')">
          {{ regimeLabel(result.market_regime) }}
        </span>
        <button class="sr-close" @click="$emit('close')">&times;</button>
      </div>

      <!-- summary -->
      <div class="sr-summary">{{ result.summary }}</div>

      <!-- risk warnings -->
      <div v-if="result.risk_warnings?.length" class="sr-section">
        <h4>&#9888; 风险预警</h4>
        <div v-for="w in result.risk_warnings" :key="w.type + w.severity"
             class="risk-item" :class="'risk-' + (w.severity || 'medium')">
          <span class="risk-type">{{ riskTypeLabel(w.type) }}</span>
          <span>{{ w.description }}</span>
        </div>
      </div>

      <!-- suggestions -->
      <div v-if="result.suggestions?.length" class="sr-section">
        <h4>&#128200; 操作建议</h4>
        <div v-for="s in result.suggestions" :key="s.symbol + s.action" class="suggestion-card">
          <div class="sc-header">
            <span class="action-badge" :class="'action-' + s.action">
              {{ actionLabel(s.action) }}
            </span>
            <strong>{{ s.name }}</strong>
            <code>{{ s.symbol }}</code>
            <span v-if="s.current_weight !== undefined && s.suggested_weight !== undefined" class="weight-change">
              {{ (s.current_weight * 100).toFixed(0) }}% &rarr; {{ (s.suggested_weight * 100).toFixed(0) }}%
            </span>
          </div>
          <p class="sc-reason">{{ s.reason }}</p>
          <span class="confidence-tag" :class="'conf-' + (s.confidence || 'medium')">
            {{ confidenceLabel(s.confidence) }}
          </span>
        </div>
      </div>

      <!-- holdings analysis table -->
      <div v-if="result.holdings_analysis?.length" class="sr-section">
        <h4>&#128202; 持仓明细分析</h4>
        <table class="holdings-table">
          <thead>
            <tr>
              <th>标的</th>
              <th>代码</th>
              <th>因子评分</th>
              <th>技术信号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in result.holdings_analysis" :key="h.symbol">
              <td>{{ h.name }}</td>
              <td><code>{{ h.symbol }}</code></td>
              <td class="td-factor">{{ h.factor_summary }}</td>
              <td :class="'td-signal signal-' + signalClass(h.tech_signal)">
                {{ h.tech_signal }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="sr-actions">
        <AppButton variant="ghost" @click="$emit('close')">返回</AppButton>
      </div>
    </div>
  </div>
</template>

<script setup>
import AppButton from '../ui/AppButton.vue'
import TaskProgress from '../TaskProgress.vue'

const props = defineProps({
  result: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  taskStatus: { type: String, default: '' },
  taskProgress: { type: Number, default: 0 },
  taskStage: { type: String, default: '' }
})

defineEmits(['close'])

function regimeLabel(regime) {
  const labels = {
    bull_strong: '强牛市', bull_weakening: '牛市趋弱',
    range_bound: '震荡', correction: '回调',
    bear: '熊市', defensive_rotate: '防御轮动', panic: '恐慌',
  }
  return labels[regime] || regime || '未知'
}

function actionLabel(action) {
  return { increase: '增配', decrease: '减配', hold: '持有',
           add: '新增', remove: '剔除' }[action] || action
}

function confidenceLabel(c) {
  return { high: '高置信度', medium: '中置信度', low: '低置信度' }[c] || c
}

function riskTypeLabel(type) {
  const labels = {
    concentration: '集中度风险',
    weighting_deviation: '权重偏离',
    sector_risk: '行业风险',
    correlation_risk: '相关性风险',
    drawdown_risk: '回撤风险'
  }
  return labels[type] || type || '风险'
}

function signalClass(signal) {
  if (!signal) return 'neutral'
  if (signal.includes('买入') || signal.includes('看多') || signal.includes('positive')) return 'bullish'
  if (signal.includes('卖出') || signal.includes('看空') || signal.includes('negative')) return 'bearish'
  return 'neutral'
}
</script>

<style scoped>
.panel-body {
  padding: var(--space-4) 0;
}

.loading-state {
  padding: var(--space-4) 0;
}

.loading-header {
  display: flex;
  align-items: center;
  padding: 0 var(--space-4) var(--space-2);
}

.error-state {
  text-align: center;
  padding: var(--space-8) var(--space-4);
}

.error-text {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-4);
}

.strategy-result {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-secondary);
  overflow: hidden;
}

.sr-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-tertiary);
}

.sr-back {
  background: none;
  border: none;
  color: var(--color-primary);
  cursor: pointer;
  font-size: var(--font-size-sm);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  white-space: nowrap;
}

.sr-back:hover {
  background: var(--color-bg-tertiary);
}

.sr-header h3 {
  margin: 0;
  font: var(--text-h4);
  flex: 1;
}

.regime-badge {
  font-size: var(--font-size-2xs);
  padding: var(--space-0) var(--space-2);
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
}

.regime-bull_strong,
.regime-bull_weakening { background: #e8f5e9; color: #2e7d32; }
.regime-range_bound { background: #fff3e0; color: #e65100; }
.regime-correction { background: #ffebee; color: #c62828; }
.regime-bear { background: #fce4ec; color: #b71c1c; }
.regime-defensive_rotate { background: #e3f2fd; color: #1565c0; }
.regime-panic { background: #f3e5f5; color: #6a1b9a; }

.sr-close {
  border: none;
  background: none;
  font-size: 1.5em;
  cursor: pointer;
  color: var(--color-text-secondary);
  padding: var(--space-1);
  line-height: 1;
  border-radius: var(--radius-sm);
}

.sr-close:hover {
  background: var(--color-bg-secondary);
}

.sr-summary {
  padding: var(--space-4) var(--space-5);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  line-height: 1.6;
  border-bottom: 1px solid var(--color-border);
}

.sr-section {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.sr-section:last-of-type {
  border-bottom: none;
}

.sr-section h4 {
  margin: 0 0 var(--space-3);
  font: var(--text-body);
  color: var(--color-text-primary);
}

.risk-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-2);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  line-height: 1.4;
}

.risk-item:last-child { margin-bottom: 0; }

.risk-high { background: #ffebee; border-left: 3px solid #e53935; }
.risk-medium { background: #fff3e0; border-left: 3px solid #ff9800; }
.risk-low { background: #f5f5f5; border-left: 3px solid #9e9e9e; }

.risk-type {
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
  flex-shrink: 0;
}

.suggestion-card {
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
}

.suggestion-card:last-child { margin-bottom: 0; }

.sc-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  flex-wrap: wrap;
}

.action-badge {
  font-size: var(--font-size-2xs);
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.action-increase { background: #e8f5e9; color: #2e7d32; }
.action-decrease { background: #ffebee; color: #c62828; }
.action-hold { background: #e3f2fd; color: #1565c0; }
.action-add { background: #f3e5f5; color: #6a1b9a; }
.action-remove { background: #fce4ec; color: #b71c1c; }

.weight-change {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin-left: auto;
  font-weight: var(--font-weight-medium);
}

.sc-reason {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-2);
  line-height: 1.5;
}

.confidence-tag {
  font-size: var(--font-size-2xs);
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-medium);
}

.conf-high { background: #e8f5e9; color: #2e7d32; }
.conf-medium { background: #fff3e0; color: #e65100; }
.conf-low { background: #f5f5f5; color: #757575; }

/* Holdings table */
.holdings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.holdings-table th,
.holdings-table td {
  padding: var(--space-2) var(--space-3);
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.holdings-table th {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  white-space: nowrap;
  background: var(--color-bg-tertiary);
}

.td-factor {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.td-signal {
  font-weight: var(--font-weight-semibold);
}

.signal-bullish { color: #e53935; }
.signal-bearish { color: #43A047; }
.signal-neutral { color: var(--color-text-secondary); }

.sr-actions {
  padding: var(--space-4) var(--space-5);
  display: flex;
  justify-content: center;
  border-top: 1px solid var(--color-border);
}
</style>
