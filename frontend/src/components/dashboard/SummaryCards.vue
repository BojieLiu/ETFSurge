<template>
  <div class="summary-grid">
    <article class="card summary-card" v-if="activeTab === 'combined'">
      <div class="summary-icon" aria-hidden="true">💰</div>
      <div class="summary-content">
        <p class="summary-label">总仓位</p>
        <p class="summary-value" :class="loading ? 'skeleton' : ''" aria-live="polite">
          <Skeleton v-if="loading" type="text" width="120" />
          <span v-else>¥{{ formatNum(totalAll) }}</span>
        </p>
      </div>
    </article>

    <article class="card summary-card" v-if="activeTab !== 'off_exchange'">
      <div class="summary-icon" :class="pnlOn >= 0 ? 'positive' : 'negative'" aria-hidden="true">
        {{ pnlOn >= 0 ? '📈' : '📉' }}
      </div>
      <div class="summary-content">
        <p class="summary-label">场内当日盈亏</p>
        <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOn >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
          <Skeleton v-if="loading" type="text" width="120" />
          <span v-else>¥{{ formatNum(pnlOn) }}</span>
        </p>
      </div>
    </article>

    <article class="card summary-card" v-if="activeTab !== 'on_exchange'">
      <div class="summary-icon" :class="pnlOff >= 0 ? 'positive' : 'negative'" aria-hidden="true">
        {{ pnlOff >= 0 ? '📈' : '📉' }}
      </div>
      <div class="summary-content">
        <p class="summary-label">场外当日盈亏</p>
        <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOff >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
          <Skeleton v-if="loading" type="text" width="120" />
          <span v-else>¥{{ formatNum(pnlOff) }}</span>
        </p>
      </div>
    </article>

    <!-- Cumulative P&L loading skeletons -->
    <template v-if="pnlHistoryLoading">
      <article class="card summary-card" v-if="activeTab !== 'off_exchange'">
        <div class="summary-content">
          <p class="summary-label">场内累计盈亏</p>
          <Skeleton type="text" width="120" />
        </div>
      </article>
      <article class="card summary-card" v-if="activeTab !== 'on_exchange'">
        <div class="summary-content">
          <p class="summary-label">场外累计盈亏</p>
          <Skeleton type="text" width="120" />
        </div>
      </article>
      <article class="card summary-card" v-if="activeTab === 'combined'">
        <div class="summary-content">
          <p class="summary-label">总累计盈亏</p>
          <Skeleton type="text" width="120" />
        </div>
      </article>
    </template>

    <!-- Cumulative P&L cards -->
    <template v-else>
      <article class="card summary-card" v-if="activeTab !== 'off_exchange' && pnlHistory?.summary">
        <div class="summary-icon positive" aria-hidden="true">📊</div>
        <div class="summary-content">
          <p class="summary-label">场内累计盈亏</p>
          <p class="summary-value text-up" aria-live="polite">
            ¥{{ formatNum(findCumulativePnl('on_exchange')) }}
            <span class="pnl-pct">({{ findCumulativePnlPct('on_exchange') }}%)</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab !== 'on_exchange' && pnlHistory?.summary">
        <div class="summary-icon positive" aria-hidden="true">📊</div>
        <div class="summary-content">
          <p class="summary-label">场外累计盈亏</p>
          <p class="summary-value text-up" aria-live="polite">
            ¥{{ formatNum(findCumulativePnl('off_exchange')) }}
            <span class="pnl-pct">({{ findCumulativePnlPct('off_exchange') }}%)</span>
          </p>
        </div>
      </article>

      <article class="card summary-card" v-if="activeTab === 'combined' && pnlHistory?.summary">
        <div class="summary-icon positive" aria-hidden="true">📊</div>
        <div class="summary-content">
          <p class="summary-label">总累计盈亏</p>
          <p class="summary-value text-up" aria-live="polite">
            ¥{{ formatNum(pnlHistory.summary.total_cumulative_pnl) }}
            <span class="pnl-pct">({{ pnlHistory.summary.total_cumulative_pnl_pct.toFixed(2) }}%)</span>
          </p>
        </div>
      </article>
    </template>
  </div>
</template>

<script setup>
import Skeleton from '../ui/Skeleton.vue'

const props = defineProps({
  activeTab: { type: String, required: true },
  totalAll: { type: Number, required: true },
  pnlOn: { type: Number, required: true },
  pnlOff: { type: Number, required: true },
  pnlTotal: { type: Number, required: true },
  pnlHistory: { type: Object, default: null },
  pnlHistoryLoading: { type: Boolean, default: false },
  loading: { type: Boolean, default: true }
})

function formatNum(n) {
  const v = n || 0
  try {
    return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  } catch {
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }
}

function findCumulativePnl(type) {
  if (!props.pnlHistory?.holdings) return 0
  const h = props.pnlHistory.holdings.find(h => h.portfolio_type === type)
  return h?.cumulative_pnl || 0
}

function findCumulativePnlPct(type) {
  if (!props.pnlHistory?.holdings) return '0.00'
  const h = props.pnlHistory.holdings.find(h => h.portfolio_type === type)
  return (h?.cumulative_pnl_pct || 0).toFixed(2)
}
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-4);
}
.summary-card {
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  transition: var(--transition-fast);
}
.summary-card:hover {
  border-color: var(--color-brand-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.summary-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-2xl);
  border-radius: var(--radius-lg);
  background: var(--color-surface-secondary);
  flex-shrink: 0;
}
.summary-icon.positive { background: var(--color-bg-success-subtle); }
.summary-icon.negative { background: var(--color-bg-danger-subtle); }
.summary-content { flex: 1; min-width: 0; }
.summary-label {
  margin: 0 0 var(--space-1);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}
.summary-value {
  margin: 0;
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  line-height: var(--line-height-tight);
  white-space: normal;
  overflow-wrap: anywhere;
}
.summary-value.skeleton { color: transparent; }
.pnl-pct {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}
.text-up { color: var(--color-text-up) !important; }
.text-down { color: var(--color-text-down) !important; }
@media (max-width: 480px) {
  .summary-grid { grid-template-columns: 1fr; }
  .summary-value { font-size: var(--font-size-lg); }
}
</style>
