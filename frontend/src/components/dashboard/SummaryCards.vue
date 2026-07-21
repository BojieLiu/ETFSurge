<template>
  <div class="summary-cards">
    <!-- Total Position Card (Combined view) -->
    <AppCard
      v-if="activeTab === 'combined'"
      variant="default"
      class="summary-card"
      :padding="false"
    >
      <div class="summary-content">
        <span class="summary-icon" aria-hidden="true">💰</span>
        <div class="summary-text">
          <p class="summary-label">总仓位</p>
          <AppSkeleton v-if="loading" type="text" width="120" />
          <p v-else class="summary-value">¥{{ formatNum(totalAll) }}</p>
        </div>
      </div>
    </AppCard>

    <!-- Daily P&L Cards -->
    <AppCard
      v-if="activeTab !== 'off_exchange'"
      variant="default"
      class="summary-card"
      :padding="false"
    >
      <div class="summary-content">
        <span class="summary-icon" :class="pnlOn >= 0 ? 'positive' : 'negative'" aria-hidden="true">
          {{ pnlOn >= 0 ? '📈' : '📉' }}
        </span>
        <div class="summary-text">
          <p class="summary-label">场内当日盈亏</p>
          <AppSkeleton v-if="loading" type="text" width="120" />
          <p v-else class="summary-value" :class="pnlOn >= 0 ? 'text-up' : 'text-down'">
            ¥{{ formatNum(pnlOn) }}
          </p>
        </div>
      </div>
    </AppCard>

    <AppCard
      v-if="activeTab !== 'on_exchange'"
      variant="default"
      class="summary-card"
      :padding="false"
    >
      <div class="summary-content">
        <span class="summary-icon" :class="pnlOff >= 0 ? 'positive' : 'negative'" aria-hidden="true">
          {{ pnlOff >= 0 ? '📈' : '📉' }}
        </span>
        <div class="summary-text">
          <p class="summary-label">场外当日盈亏</p>
          <AppSkeleton v-if="loading" type="text" width="120" />
          <p v-else class="summary-value" :class="pnlOff >= 0 ? 'text-up' : 'text-down'">
            ¥{{ formatNum(pnlOff) }}
          </p>
        </div>
      </div>
    </AppCard>

    <!-- Cumulative P&L Loading Skeletons -->
    <template v-if="pnlHistoryLoading">
      <AppCard
        v-if="activeTab !== 'off_exchange'"
        variant="default"
        class="summary-card"
        :padding="false"
      >
        <div class="summary-content">
          <p class="summary-label">场内累计盈亏</p>
          <AppSkeleton type="text" width="120" />
        </div>
      </AppCard>
      <AppCard
        v-if="activeTab !== 'on_exchange'"
        variant="default"
        class="summary-card"
        :padding="false"
      >
        <div class="summary-content">
          <p class="summary-label">场外累计盈亏</p>
          <AppSkeleton type="text" width="120" />
        </div>
      </AppCard>
      <AppCard
        v-if="activeTab === 'combined'"
        variant="default"
        class="summary-card"
        :padding="false"
      >
        <div class="summary-content">
          <p class="summary-label">总累计盈亏</p>
          <AppSkeleton type="text" width="120" />
        </div>
      </AppCard>
    </template>

    <!-- Cumulative P&L Cards -->
    <template v-else>
      <AppCard
        v-if="activeTab !== 'off_exchange' && pnlHistory?.summary"
        variant="default"
        class="summary-card"
        :padding="false"
      >
        <div class="summary-content">
          <span class="summary-icon positive" aria-hidden="true">📊</span>
          <div class="summary-text">
            <p class="summary-label">场内累计盈亏</p>
            <p class="summary-value text-up" aria-live="polite">
              ¥{{ formatNum(findCumulativePnl('on_exchange')) }}
              <span class="pnl-pct">({{ findCumulativePnlPct('on_exchange') }}%)</span>
            </p>
          </div>
        </div>
      </AppCard>

      <AppCard
        v-if="activeTab !== 'on_exchange' && pnlHistory?.summary"
        variant="default"
        class="summary-card"
        :padding="false"
      >
        <div class="summary-content">
          <span class="summary-icon positive" aria-hidden="true">📊</span>
          <div class="summary-text">
            <p class="summary-label">场外累计盈亏</p>
            <p class="summary-value text-up" aria-live="polite">
              ¥{{ formatNum(findCumulativePnl('off_exchange')) }}
              <span class="pnl-pct">({{ findCumulativePnlPct('off_exchange') }}%)</span>
            </p>
          </div>
        </div>
      </AppCard>

      <AppCard
        v-if="activeTab === 'combined' && pnlHistory?.summary"
        variant="default"
        class="summary-card"
        :padding="false"
      >
        <div class="summary-content">
          <span class="summary-icon positive" aria-hidden="true">📊</span>
          <div class="summary-text">
            <p class="summary-label">总累计盈亏</p>
            <p class="summary-value text-up" aria-live="polite">
              ¥{{ formatNum(pnlHistory.summary.total_cumulative_pnl) }}
              <span class="pnl-pct">({{ pnlHistory.summary.total_cumulative_pnl_pct.toFixed(2) }}%)</span>
            </p>
          </div>
        </div>
      </AppCard>
    </template>
  </div>
</template>

<script setup>
import { AppCard, AppSkeleton } from '@/components'

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
  return h?.cumulative_pnl_pct ? h.cumulative_pnl_pct.toFixed(2) : '0.00'
}
</script>

<style scoped>
.summary-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-gap-md);
}

@media (max-width: 1023px) {
  .summary-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 639px) {
  .summary-cards {
    grid-template-columns: 1fr;
  }
}

.summary-card {
  /* AppCard handles styling */
}

.summary-content {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
}

.summary-icon {
  font-size: var(--font-size-2xl);
  line-height: 1;
  flex-shrink: 0;
}

.summary-icon.positive {
  color: var(--color-text-up);
}

.summary-icon.negative {
  color: var(--color-text-down);
}

.summary-text {
  display: flex;
  flex-direction: column;
  gap: var(--space-half);
  min-width: 0;
}

.summary-label {
  margin: 0;
  font: var(--text-caption);
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
}

.summary-value {
  margin: 0;
  font: var(--text-h4);
  color: var(--color-text-primary);
}

.summary-value.text-up {
  color: var(--color-text-up);
}

.summary-value.text-down {
  color: var(--color-text-down);
}

.pnl-pct {
  font: var(--text-body-sm);
  color: var(--color-text-tertiary);
  margin-left: var(--space-2);
}
</style>