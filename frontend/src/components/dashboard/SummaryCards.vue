<template>
  <div class="summary-grid">
    <!-- 总仓位 -->
    <AppCard v-if="activeTab === 'combined'" layout="horizontal" icon="💰" class="summary-card" bordered padded hoverable>
      <p class="summary-label">总仓位</p>
      <p class="summary-value" :class="loading ? 'skeleton' : ''" aria-live="polite">
        <Skeleton v-if="loading" type="text" width="120" />
        <span v-else>¥{{ formatNum(totalAll) }}</span>
      </p>
    </AppCard>

    <!-- 场内当日盈亏 -->
    <AppCard v-if="activeTab !== 'off_exchange'" layout="horizontal"
      :icon="pnlOn >= 0 ? '📈' : '📉'"
      :style="pnlOn >= 0 ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : { '--app-card-icon-bg': 'var(--color-bg-danger-subtle)' }"
      class="summary-card" bordered padded hoverable
    >
      <p class="summary-label">场内当日盈亏</p>
      <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOn >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
        <Skeleton v-if="loading" type="text" width="120" />
        <span v-else>¥{{ formatNum(pnlOn) }}</span>
      </p>
    </AppCard>

    <!-- 场外当日盈亏 -->
    <AppCard v-if="activeTab !== 'on_exchange'" layout="horizontal"
      :icon="pnlOff >= 0 ? '📈' : '📉'"
      :style="pnlOff >= 0 ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : { '--app-card-icon-bg': 'var(--color-bg-danger-subtle)' }"
      class="summary-card" bordered padded hoverable
    >
      <p class="summary-label">场外当日盈亏</p>
      <p class="summary-value" :class="[loading ? 'skeleton' : '', pnlOff >= 0 ? 'text-up' : 'text-down']" aria-live="polite">
        <Skeleton v-if="loading" type="text" width="120" />
        <span v-else>¥{{ formatNum(pnlOff) }}</span>
      </p>
    </AppCard>

    <!-- Cumulative P&L loading skeletons -->
    <template v-if="pnlHistoryLoading">
      <AppCard v-if="activeTab !== 'off_exchange'" layout="horizontal" class="summary-card" bordered padded>
        <div class="summary-content">
          <p class="summary-label">场内累计盈亏</p>
          <Skeleton type="text" width="120" />
        </div>
      </AppCard>
      <AppCard v-if="activeTab !== 'on_exchange'" layout="horizontal" class="summary-card" bordered padded>
        <div class="summary-content">
          <p class="summary-label">场外累计盈亏</p>
          <Skeleton type="text" width="120" />
        </div>
      </AppCard>
      <AppCard v-if="activeTab === 'combined'" layout="horizontal" class="summary-card" bordered padded>
        <div class="summary-content">
          <p class="summary-label">总累计盈亏</p>
          <Skeleton type="text" width="120" />
        </div>
      </AppCard>
    </template>

    <!-- Cumulative P&L cards -->
    <template v-else>
      <AppCard v-if="activeTab !== 'off_exchange' && pnlHistory?.summary" layout="horizontal"
        icon="📊" :style="pnlHistory.summary.has_cost_basis_data ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : {}"
        class="summary-card" bordered padded hoverable
      >
        <p class="summary-label">场内累计盈亏</p>
        <p class="summary-value" :class="findCumulativePnl('on_exchange') >= 0 ? 'text-up' : 'text-down'" aria-live="polite">
          <template v-if="pnlHistory.summary.has_cost_basis_data">
            ¥{{ formatNum(findCumulativePnl('on_exchange')) }}
            <span class="pnl-pct">({{ findCumulativePnlPct('on_exchange') }}%)</span>
          </template>
          <span v-else class="text-muted">需输入成本</span>
        </p>
      </AppCard>

      <AppCard v-if="activeTab !== 'on_exchange' && pnlHistory?.summary" layout="horizontal"
        icon="📊" :style="pnlHistory.summary.has_cost_basis_data ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : {}"
        class="summary-card" bordered padded hoverable
      >
        <p class="summary-label">场外累计盈亏</p>
        <p class="summary-value" :class="findCumulativePnl('off_exchange') >= 0 ? 'text-up' : 'text-down'" aria-live="polite">
          <template v-if="pnlHistory.summary.has_cost_basis_data">
            ¥{{ formatNum(findCumulativePnl('off_exchange')) }}
            <span class="pnl-pct">({{ findCumulativePnlPct('off_exchange') }}%)</span>
          </template>
          <span v-else class="text-muted">需输入成本</span>
        </p>
      </AppCard>

      <AppCard v-if="activeTab === 'combined' && pnlHistory?.summary" layout="horizontal"
        icon="📊" :style="pnlHistory.summary.has_cost_basis_data ? { '--app-card-icon-bg': 'var(--color-bg-success-subtle)' } : {}"
        class="summary-card" bordered padded hoverable
      >
        <p class="summary-label">总累计盈亏</p>
        <p class="summary-value" :class="pnlHistory.summary.total_cumulative_pnl >= 0 ? 'text-up' : 'text-down'" aria-live="polite">
          <template v-if="pnlHistory.summary.has_cost_basis_data">
            ¥{{ formatNum(pnlHistory.summary.total_cumulative_pnl) }}
            <span class="pnl-pct">({{ pnlHistory.summary.total_cumulative_pnl_pct.toFixed(2) }}%)</span>
          </template>
          <span v-else class="text-muted">需输入成本</span>
        </p>
      </AppCard>
    </template>
  </div>
</template>

<script setup>
import Skeleton from '../ui/Skeleton.vue'
import AppCard from '../ui/AppCard.vue'

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
  // Uses backend summary.by_type (Sprint 2.3)
  const h = props.pnlHistory?.summary?.by_type?.[type]
  return h?.cumulative_pnl ?? 0
}

function findCumulativePnlPct(type) {
  // Uses backend summary.by_type (Sprint 2.3)
  const h = props.pnlHistory?.summary?.by_type?.[type]
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
  transition: var(--transition-fast);
}

.summary-label {
  margin: 0 0 var(--space-1);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
}

.summary-value {
  margin: 0;
  font-family: var(--font-family-mono);
  font: var(--text-h2);
  color: var(--color-text-primary);
  line-height: var(--line-height-tight);
  white-space: normal;
  overflow-wrap: anywhere;
}

.summary-value.skeleton { color: transparent; }

.pnl-pct {
  font: var(--text-body-sm);
}

.text-up { color: var(--color-text-up) !important; }
.text-down { color: var(--color-text-down) !important; }

@media (max-width: 480px) {
  .summary-grid { grid-template-columns: 1fr; }
  .summary-value { font-size: var(--font-size-lg); }
}
</style>
