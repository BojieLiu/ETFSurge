<template>
  <section class="card indicators-section" v-if="indicatorData && !loading">
    <div class="card-header">
      <h2 class="card-title"><span class="card-title-icon" aria-hidden="true">📋</span>最新指标值</h2>
    </div>
    <div class="indicators-grid">
      <div class="indicator-item" v-for="ind in indicatorItems" :key="ind.key">
        <span class="indicator-label">{{ ind.label }}</span>
        <span class="indicator-value" :class="ind.class">{{ ind.value }}</span>
      </div>
    </div>
  </section>
  <section class="card signal-section" v-if="signal && !loading">
    <div class="card-header"><h2 class="card-title">🎯 综合信号</h2></div>
    <div class="signal-content">
      <div :class="['signal-badge', signal.signal]" role="status">
        <span class="signal-icon">{{ signalIcon }}</span>
        <span class="signal-text">{{ signalText }}</span>
      </div>
      <div class="signal-score">评分: <strong>{{ signal.score }}</strong></div>
      <ul class="signal-reasons" v-if="signal.reasons?.length">
        <li v-for="(r, i) in signal.reasons" :key="i">{{ r }}</li>
      </ul>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ indicatorData: Object, signal: Object, loading: Boolean })

const signalText = computed(() => ({ buy: '买入', sell: '卖出', hold: '持有' })[props.signal?.signal] || '')
const signalIcon = computed(() => ({ buy: '⬆️', sell: '⬇️', hold: '➡️' })[props.signal?.signal] || '')

const indicatorItems = computed(() => {
  if (!props.indicatorData) return []
  const d = props.indicatorData
  return [
    { key: 'ma5', label: 'MA5', value: d.ma5?.toFixed(2) ?? '--', class: '' },
    { key: 'ma10', label: 'MA10', value: d.ma10?.toFixed(2) ?? '--', class: '' },
    { key: 'ma20', label: 'MA20', value: d.ma20?.toFixed(2) ?? '--', class: '' },
    { key: 'ma60', label: 'MA60', value: d.ma60?.toFixed(2) ?? '--', class: '' },
    { key: 'rsi', label: 'RSI(14)', value: d.rsi?.toFixed(2) ?? '--', class: d.rsi >= 70 ? 'text-danger' : d.rsi <= 30 ? 'text-success' : '' },
    { key: 'macd', label: 'MACD', value: d.macd?.macd?.toFixed(4) ?? '--', class: (d.macd?.macd || 0) >= 0 ? 'text-success' : 'text-danger' },
    { key: 'kdj', label: 'KDJ-K', value: d.kdj?.k?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-upper', label: 'BOLL上轨', value: d.bollinger?.upper?.toFixed(2) ?? '--', class: '' },
    { key: 'boll-lower', label: 'BOLL下轨', value: d.bollinger?.lower?.toFixed(2) ?? '--', class: '' },
  ]
})
</script>

<style scoped>
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); overflow: hidden; margin-bottom: var(--space-4); }
.card-header { display: flex; align-items: center; justify-content: space-between; padding: var(--space-4) var(--space-5); border-bottom: 1px solid var(--color-border-light); }
.card-title { font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.card-title-icon { font-size: var(--font-size-xl); line-height: 1; }
.indicators-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--space-3); padding: var(--space-4); }
.indicator-item { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-3); background: var(--color-surface-secondary); border: 1px solid var(--color-border-light); border-radius: var(--radius-lg); }
.indicator-label { font-size: var(--font-size-xs); font-weight: var(--font-weight-medium); color: var(--color-text-tertiary); text-transform: uppercase; }
.indicator-value { font-family: var(--font-family-mono); font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); }
.text-success { color: var(--color-text-success); }
.text-danger { color: var(--color-text-danger); }
.signal-content { display: flex; flex-direction: column; align-items: center; gap: var(--space-4); padding: var(--space-5); text-align: center; }
.signal-badge { display: inline-flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-6); font-size: var(--font-size-xl); font-weight: var(--font-weight-bold); border-radius: var(--radius-full); }
.signal-badge.buy { color: var(--color-success-700); background: var(--color-bg-success-subtle); border: 2px solid var(--color-success-300); }
.signal-badge.sell { color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border: 2px solid var(--color-danger-300); }
.signal-badge.hold { color: var(--color-warning-700); background: var(--color-bg-warning-subtle); border: 2px solid var(--color-warning-300); }
.signal-icon { font-size: var(--font-size-2xl); }
.signal-score { font-size: var(--font-size-base); color: var(--color-text-secondary); }
.signal-reasons { list-style: none; padding: 0; margin: var(--space-4) 0 0; display: flex; flex-direction: column; gap: var(--space-2); width: 100%; max-width: 400px; }
.signal-reasons li { padding: var(--space-2) var(--space-3); font-size: var(--font-size-sm); color: var(--color-text-secondary); background: var(--color-surface-secondary); border: 1px solid var(--color-border-light); border-radius: var(--radius-md); text-align: left; }
</style>
