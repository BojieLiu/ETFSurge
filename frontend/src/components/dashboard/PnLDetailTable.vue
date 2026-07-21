<template>
  <AppCard variant="default" :padding="false" class="pnl-detail-table">
    <template #header>
      <h2 class="card__title">
        <span class="card-title-icon" aria-hidden="true">📋</span>
        当日盈亏明细
      </h2>
    </template>

    <AppTable
      :columns="columns"
      :data="tableData"
      row-key="symbol"
      :striped="true"
      :hoverable="true"
      density="comfortable"
    >
      <template #cell:type="{ row }">
        <AppBadge
          :variant="row.portfolio_type === 'on_exchange' ? 'outline' : 'default'"
          :color="row.portfolio_type === 'on_exchange' ? 'var(--color-brand-600)' : 'var(--color-success-600)'"
          size="sm"
          class="type-badge"
        >
          {{ row.portfolio_type === 'on_exchange' ? '场内' : '场外' }}
        </AppBadge>
      </template>

      <template #cell:change_pct="{ row }">
        <span :class="['change-value', changeClass(row.change_pct)]">
          {{ formatChange(row.change_pct) }}
        </span>
      </template>

      <template #cell:target_amount="{ row }">
        <span class="amount-cell">¥{{ formatNum(row.target_amount) }}</span>
      </template>

      <template #cell:daily_pnl="{ row }">
        <span :class="['change-value', changeClass(row.daily_pnl)]">
          {{ formatChange(row.daily_pnl, true) }}
        </span>
      </template>

      <template #cell:tracked_index="{ row }">
        <span v-if="row.tracked_index">{{ row.tracked_index }}</span>
        <span v-else class="text-muted">—</span>
      </template>
    </AppTable>

    <template #footer>
      <div class="table-footer">
        <div class="footer-row">
          <span class="footer-label"><strong>合计</strong></span>
          <span class="footer-change" :class="pnlWeightedChange >= 0 ? 'text-up' : 'text-down'">
            {{ formatChange(pnlWeightedChange) }}
          </span>
          <span class="footer-amount"><strong>¥{{ formatNum(pnlTotalAmount) }}</strong></span>
          <span class="footer-pnl" :class="pnlTotal >= 0 ? 'text-up' : 'text-down'">
            <strong>¥{{ formatNum(pnlTotal) }}</strong>
          </span>
          <span v-if="showTrackedIndex"></span>
        </div>
      </div>
    </template>
  </AppCard>
</template>

<script setup>
import { computed } from 'vue'
import { AppCard, AppTable, AppBadge } from '@/components'

const props = defineProps({
  items: { type: Array, default: () => [] },
  activeTab: { type: String, required: true },
  pnlTotal: { type: Number, default: 0 },
  pnlTotalAmount: { type: Number, default: 0 },
  pnlWeightedChange: { type: Number, default: 0 }
})

const showTrackedIndex = computed(() => props.activeTab === 'off_exchange' || props.activeTab === 'combined')

const columns = [
  { key: 'short_name', label: '名称', width: '160px' },
  { key: 'type', label: '类型', width: '80px' },
  { key: 'change_pct', label: '涨跌幅', width: '100px', align: 'center' },
  { key: 'target_amount', label: '目标金额', width: '120px', align: 'right' },
  { key: 'daily_pnl', label: '当日盈亏', width: '120px', align: 'right' },
  { key: 'tracked_index', label: '跟踪指数', width: '140px' }
]

const tableData = computed(() => {
  return props.items.map(item => ({
    symbol: item.symbol,
    short_name: item.short_name || item.name,
    name: item.name,
    portfolio_type: item.portfolio_type,
    change_pct: item.change_pct,
    target_amount: item.target_amount,
    daily_pnl: item.daily_pnl,
    tracked_index: item.tracked_index
  }))
})

function formatNum(n) {
  const v = n || 0
  try {
    return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  } catch {
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }
}

function changeClass(pct) {
  if (pct == null) return ''
  return pct >= 0 ? 'text-up' : 'text-down'
}

function formatChange(pct, isAmount = false) {
  if (pct == null) return '—'
  if (isAmount) {
    return (pct > 0 ? '+' : '') + formatNum(pct)
  }
  return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
}
</script>

<style scoped>
.pnl-detail-table {
  /* AppCard handles layout */
}

.type-badge {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.table-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-6);
  border-top: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  flex-wrap: wrap;
}

.footer-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.footer-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.footer-change {
  font: var(--text-mono-lg);
  font-weight: var(--font-weight-semibold);
  min-width: 80px;
  text-align: right;
}

.footer-amount,
.footer-pnl {
  font: var(--text-mono-lg);
  font-weight: var(--font-weight-bold);
  min-width: 100px;
  text-align: right;
}

.text-muted {
  color: var(--color-text-tertiary);
}

.change-value {
  font: var(--text-mono);
  font-weight: var(--font-weight-semibold);
}

.amount-cell {
  font: var(--text-mono);
  text-align: right;
  color: var(--color-text-primary);
}
</style>