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
          <!-- O26 (round7 §7 P26): 模式按钮 aria-pressed 选中态——旧实现仅颜色差异，
               视觉区分弱（用户反馈「没有标记展示当前选中哪个」） -->
          <button :class="['mode-btn', { 'mode-btn--active': chartMode === 'kline' }]"
                  :aria-pressed="chartMode === 'kline'" @click="$emit('update:chartMode', 'kline')">📊 K线</button>
          <button :class="['mode-btn', { 'mode-btn--active': chartMode === 'intraday' }]"
                  :aria-pressed="chartMode === 'intraday'" @click="$emit('update:chartMode', 'intraday')">📈 分时</button>
        </div>
      </div>
      <div class="control-group control-group--info" v-if="chartData">
        <div class="control-field">
          <!-- 美化轮: 数据量从裸文本 → chip 徽章（与全站状态 chip 同语言） -->
          <span class="data-count-chip">📊 {{ chartData.dates?.length || 0 }} 条数据</span>
        </div>
      </div>
    </div>
    <div class="indicator-toggles" v-if="chartData" role="group">
      <span class="toggles-label">叠加指标:</span>
      <div class="toggles-grid">
        <label class="toggle-item" v-for="ind in indicatorToggles" :key="ind.key">
          <!-- F14 (round6 §16.2): 显式 ref .value 读写——v-model="ind.model" 对 ref 对象
               不写回 .value（模板解包陷阱），开关状态与图表不同步 -->
          <input type="checkbox" :data-testid="'toggle-' + ind.key"
                 :checked="ind.model && ind.model.value === true"
                 @change="ind.model.value = $event.target.checked; $emit('refresh')" />
          <span class="toggle-name">{{ ind.label }}</span>
        </label>
      </div>
      <!-- round19 P5-②: 指标副图三选一单选组（默认 MACD）——原 macd/kdj/rsi checkbox 移除 -->
      <div class="indicator-radio-group" v-if="indicatorOptions && indicatorOptions.length" role="radiogroup" aria-label="指标副图">
        <span class="toggles-label">副图指标:</span>
        <label class="toggle-item" v-for="opt in indicatorOptions" :key="opt.key">
          <input type="radio" name="active-indicator" :data-testid="'indicator-' + opt.key"
                 :checked="activeIndicator === opt.key"
                 @change="activeIndicator === opt.key || $emit('update:active-indicator', opt.key); $emit('refresh')" />
          <span class="toggle-name">{{ opt.label }}</span>
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
  // round19 P5-②: 指标副图单选组
  indicatorOptions: Array,
  activeIndicator: String,
})
defineEmits(['update:selected', 'update:period', 'update:chartMode', 'update:active-indicator', 'refresh'])
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
/* 美化轮（2026-09-06）: 数据量 chip + 指标 toggle 药丸化——控制面板从「表单感」到「仪表感」 */
.data-count-chip {
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: var(--space-1) var(--space-3);
  font-size: var(--font-size-xs); font-family: var(--font-family-mono);
  color: var(--color-brand-700); background: var(--color-bg-brand-subtle);
  border: 1px solid var(--color-brand-200);
  border-radius: var(--radius-full);
}
/* 叠加指标 checkbox → 药丸 toggle（原生 checkbox 藏起，选中态品牌底） */
.toggles-grid .toggle-item, .indicator-radio-group .toggle-item {
  padding: var(--space-1) var(--space-3);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  transition: var(--transition-fast);
  user-select: none;
}
.toggles-grid .toggle-item:hover, .indicator-radio-group .toggle-item:hover {
  border-color: var(--color-brand-300);
  background: var(--color-surface-hover);
}
.toggles-grid .toggle-item input, .indicator-radio-group .toggle-item input {
  accent-color: var(--color-brand-600);
  margin: 0;
}
.toggles-grid .toggle-item:has(input:checked), .indicator-radio-group .toggle-item:has(input:checked) {
  background: var(--color-bg-brand-subtle);
  border-color: var(--color-brand-500);
}
.toggles-grid .toggle-item:has(input:checked) .toggle-name,
.indicator-radio-group .toggle-item:has(input:checked) .toggle-name {
  color: var(--color-brand-700); font-weight: var(--font-weight-semibold);
}
</style>
