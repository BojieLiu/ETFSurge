<template>
  <section class="card control-panel">
    <div class="control-row">
      <div class="control-group control-group--primary">
        <label class="control-label" for="etf-select">分析标的</label>
        <div class="control-field">
          <AppSelect id="etf-select" :model-value="selected" :options="etfOptions" placeholder="选择 ETF 或指数..." size="md" @update:model-value="$emit('update:selected', $event)" />
        </div>
      </div>
      <div class="control-group">
        <label class="control-label" for="period-select">周期</label>
        <AppSelect id="period-select" :model-value="period" :options="periodOptions" size="md" @update:model-value="$emit('update:period', $event); $emit('refresh')" />
      </div>
      <div class="control-group">
        <label class="control-label">图表类型</label>
        <div class="chart-mode-toggle" role="radiogroup">
          <button :class="['mode-btn', { 'mode-btn--active': chartMode === 'kline' }]" @click="$emit('update:chartMode', 'kline')">📊 K线</button>
          <button :class="['mode-btn', { 'mode-btn--active': chartMode === 'intraday' }]" @click="$emit('update:chartMode', 'intraday')">📈 分时</button>
        </div>
      </div>
      <div class="control-group control-group--info" v-if="chartData">
        <div class="control-field">
          <span class="data-count">{{ chartData.dates?.length || 0 }} 条数据</span>
        </div>
      </div>
    </div>
    <div class="indicator-toggles" v-if="chartData" role="group">
      <span class="toggles-label">叠加指标:</span>
      <div class="toggles-grid">
        <label class="toggle-item" v-for="ind in indicatorToggles" :key="ind.key">
          <input type="checkbox" v-model="ind.model" @change="$emit('refresh')" />
          <span class="toggle-name">{{ ind.label }}</span>
        </label>
      </div>
    </div>
  </section>
</template>

<script setup>
import AppSelect from '../ui/AppSelect.vue'

defineProps({
  selected: String,
  period: String,
  chartMode: String,
  chartData: Object,
  etfOptions: Array,
  periodOptions: Array,
  indicatorToggles: Array,
})
defineEmits(['update:selected', 'update:period', 'update:chartMode', 'refresh'])
</script>

<style scoped>
.control-panel { padding: var(--space-5); }
.control-row { display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: flex-end; margin-bottom: var(--space-4); }
.control-group { display: flex; flex-direction: column; gap: var(--space-1.5); }
.control-group--primary { flex: 1; min-width: 280px; }
.control-group--action { flex-shrink: 0; }
.control-group--info { flex: 1; min-width: 120px; margin-left: auto; }
.control-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: var(--letter-spacing-wide); }
.control-field { width: 100%; }
.chart-mode-toggle { display: inline-flex; background: var(--color-surface-tertiary); border-radius: var(--radius-md); padding: var(--space-1); gap: var(--space-1); }
.mode-btn { padding: var(--space-1.5) var(--space-3); font-size: var(--font-size-sm); font-weight: var(--font-weight-medium); color: var(--color-text-secondary); border-radius: var(--radius-sm); background: transparent; border: none; cursor: pointer; transition: var(--transition-fast); }
.mode-btn:hover { color: var(--color-text-primary); background: var(--color-surface-hover); }
.mode-btn--active { color: var(--color-brand-600); background: var(--color-bg-brand-subtle); }
.indicator-toggles { padding-top: var(--space-4); border-top: 1px solid var(--color-border-light); margin-top: var(--space-4); }
.toggles-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); margin-right: var(--space-3); }
.toggles-grid { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.toggle-item { display: inline-flex; align-items: center; gap: var(--space-1); font-size: var(--font-size-sm); cursor: pointer; }
.toggle-name { color: var(--color-text-secondary); }
.data-count { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
</style>
