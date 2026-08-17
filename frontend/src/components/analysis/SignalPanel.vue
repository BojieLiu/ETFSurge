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
    <div class="card-header">
      <h2 class="card-title">📈 技术信号</h2>
    </div>
    <p class="signal-caption">基于 K 线技术指标（RSI/KDJ/MACD/MA），不含因子与基本面</p>
    <div class="signal-content">
      <div :class="['signal-badge', signal.signal]" role="status">
        <span class="signal-icon">{{ signalIcon }}</span>
        <span class="signal-text">{{ signalText }}</span>
      </div>
      <div class="signal-score">评分: <strong>{{ signal.score }}</strong></div>
      <ul class="signal-reasons" v-if="signalReasons.length">
        <li v-for="(r, i) in signalReasons" :key="i">{{ r }}</li>
      </ul>
      <!-- round24 R25: calm 市下 RSI/KDJ 中性区补 info reason——caption 承诺 RSI/KDJ
           但旧实现极端区才 emit，中性区只显 MACD/MA（Q1 误导） -->
      <p v-else-if="neutralInfo" class="signal-neutral-info">{{ neutralInfo }}</p>
    </div>
  </section>
  <!-- round24 R25: 独立「综合信号」卡——技术+因子+基本面聚合决策（不替换技术信号）。
       降级门禁：因子缺失时 composite_decision.degraded=true，显式标「因子缺失」 -->
  <section class="card composite-section" v-if="compositeDecision && !loading">
    <div class="card-header">
      <h2 class="card-title">🧮 综合信号</h2>
    </div>
    <p class="signal-caption">技术 + 因子 + 基本面聚合（因子数据完整时）</p>
    <div class="signal-content">
      <template v-if="compositeDecision.degraded || compositeUnavailable">
        <div class="composite-degraded" role="alert">
          <span class="composite-icon">⚠️</span>
          <span class="composite-text">{{ compositeUnavailable ? '因子缺失，综合信号不可用' : (compositeDecision.reason || '因子数据缺失，综合信号不可用') }}</span>
        </div>
      </template>
      <template v-else>
        <div :class="['signal-badge', compositeDecision.signal]" role="status">
          <span class="signal-icon">{{ compositeIcon }}</span>
          <span class="signal-text">{{ compositeText }}</span>
        </div>
        <div class="signal-score">评分: <strong>{{ compositeDecision.score }}</strong></div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ indicatorData: Object, signal: Object, loading: Boolean, compositeDecision: Object })

const signalText = computed(() => ({ buy: '买入', sell: '卖出', hold: '持有' })[props.signal?.signal] || '')
const signalIcon = computed(() => ({ buy: '⬆️', sell: '⬇️', hold: '➡️' })[props.signal?.signal] || '')
const compositeText = computed(() => ({ buy: '买入', sell: '卖出', hold: '持有' })[props.compositeDecision?.signal] || '')
const compositeIcon = computed(() => ({ buy: '⬆️', sell: '⬇️', hold: '➡️' })[props.compositeDecision?.signal] || '')
// round27 R52: signal 为 null（分项覆盖率不足，门禁降级）→ 显示「因子缺失，综合信号不可用」，
// 不再把 null 误渲染为「持有」徽标
const compositeUnavailable = computed(() => props.compositeDecision?.signal === null)

// round24 R25: 中性区 info reason——calm 市（RSI 40-60、KDJ 中段）下 reasons 为空，
// 补「RSI=52 中性」info（消除 caption 承诺 RSI/KDJ 但 reason 只显 MACD/MA 的误导）。
const neutralInfo = computed(() => {
  const d = props.indicatorData
  if (!d || props.signal?.reasons?.length) return ''
  const rsi = d.rsi
  if (typeof rsi !== 'number' || rsi < 40 || rsi > 60) return ''
  const kdj = d.kdj || {}
  const k = typeof kdj.k === 'number' && typeof kdj.d === 'number' ? '、KDJ 中段' : ''
  return `RSI=${rsi.toFixed(1)} 中性${k}，无极端信号`
})

const signalReasons = computed(() => {
  const list = props.signal?.reasons || []
  // reasons 非空时用原列表；空时才显示中性 info
  return list.length ? list : []
})

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
.signal-caption { margin: 0; padding: 0 var(--space-5); font-size: var(--font-size-xs); color: var(--color-text-tertiary); text-align: center; }
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
.signal-neutral-info { margin: 0; padding: var(--space-2) var(--space-3); font-size: var(--font-size-xs); color: var(--color-text-tertiary); background: var(--color-surface-secondary); border-radius: var(--radius-md); }
.composite-degraded { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-radius: var(--radius-lg); font-size: var(--font-size-sm); color: var(--color-warning-700); background: var(--color-bg-warning-subtle); border: 1px solid var(--color-warning-300); }
.composite-icon { font-size: var(--font-size-base); }
.composite-text { font-weight: var(--font-weight-medium); }
</style>
