<template>
  <AppCard variant="default" :padding="false" class="allocation-table">
    <template #header>
      <h2 class="card__title">
        <span class="card-title-icon" aria-hidden="true">📋</span>
        {{ title }}
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
      <template #cell:weight="{ row }">
        <AppBadge variant="outline" :color="getWeightColor(row.target_weight)" class="weight-badge">
          {{ (row.target_weight * 100).toFixed(1) }}%
        </AppBadge>
      </template>

      <template #cell:target_amount="{ row }">
        <span class="amount-cell">¥{{ formatNum(row.target_amount) }}</span>
      </template>

      <template #cell:current_price="{ row }">
        <span v-if="row.current_price != null" class="price-cell">¥{{ row.current_price.toFixed(2) }}</span>
        <span v-else class="text-muted">—</span>
      </template>

      <template #cell:change_pct="{ row }">
        <span v-if="row.change_pct != null" :class="['change-value', changeClass(row.change_pct)]">
          {{ formatChange(row.change_pct) }}
        </span>
        <span v-else class="text-muted">—</span>
      </template>
    </AppTable>

    <template #footer>
      <div class="table-footer">
        <div class="footer-row">
          <span class="footer-label"><strong>现金仓位</strong></span>
          <AppBadge variant="outline" class="weight-badge">
            {{ (cashPct * 100).toFixed(1) }}%
          </AppBadge>
          <span class="footer-amount"><strong>¥{{ formatNum(cashAmount) }}</strong></span>
        </div>
      </div>
    </template>
  </AppCard>
</template>

<script setup>
import { AppCard, AppTable, AppBadge } from '@/components'

defineProps({
  items: { type: Array, default: () => [] },
  cashPct: { type: Number, default: 0 },
  cashAmount: { type: Number, default: 0 },
  title: { type: String, required: true }
})

const columns = [
  { key: 'symbol', label: '代码', width: '80px' },
  { key: 'name', label: '名称', width: '160px' },
  { key: 'weight', label: '权重', width: '100px' },
  { key: 'target_amount', label: '目标金额', width: '120px', align: 'right' },
  { key: 'current_price', label: '现价', width: '100px', align: 'right' },
  { key: 'change_pct', label: '涨跌幅', width: '100px', align: 'center' }
]

const tableData = computed(() => {
  return props.items.map(item => ({
    ...item,
    symbol: item.symbol,
    name: item.name,
    target_weight: item.target_weight,
    target_amount: item.target_amount,
    current_price: item.current_price,
    change_pct: item.change_pct
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

function formatChange(pct) {
  if (pct == null) return '—'
  return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
}

function getWeightColor(weight) {
  if (weight >= 0.2) return 'var(--color-brand-600)'
  if (weight >= 0.1) return 'var(--color-warning-600)'
  return 'var(--color-success-600)'
}
</script>

<style scoped>
.allocation-table {
  /* AppCard handles layout */
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

.footer-amount {
  font: var(--text-mono-lg);
  color: var(--color-text-primary);
}

.weight-badge {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
}

.amount-cell {
  font: var(--text-mono);
  text-align: right;
  color: var(--color-text-primary);
}

.price-cell {
  font: var(--text-mono);
  text-align: right;
  color: var(--color-text-primary);
}

.text-muted {
  color: var(--color-text-tertiary);
}

.change-value {
  font: var(--text-mono);
  font-weight: var(--font-weight-semibold);
}
</style>