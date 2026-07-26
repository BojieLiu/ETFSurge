<template>
  <AppCard v-if="items.length" title="当日盈亏明细" icon="📊">
    <template #header-action>
      <p class="card-subtitle" v-if="activeTab !== 'combined'">
        当前视图：{{ activeTab === 'on_exchange' ? '场内' : '场外' }} ETF
      </p>
    </template>
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th scope="col">名称</th>
            <th scope="col">类型</th>
            <th scope="col">涨跌幅</th>
            <th scope="col">目标金额</th>
            <th scope="col">当日盈亏</th>
            <th v-if="showTrackedIndex" scope="col">跟踪指数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.symbol">
            <td><strong>{{ item.short_name || item.name }}</strong></td>
            <td><span class="type-badge" :class="item.portfolio_type">{{ item.portfolio_type === 'on_exchange' ? '场内' : '场外' }}</span></td>
            <td :class="changeClass(item.change_pct)">{{ formatChange(item.change_pct) }}</td>
            <td class="amount-cell">¥{{ formatNum(item.target_amount) }}</td>
            <td :class="changeClass(item.daily_pnl)">{{ formatChange(item.daily_pnl, true) }}</td>
            <td v-if="showTrackedIndex">{{ item.tracked_index || '—' }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="footer-row">
            <td colspan="2"><strong>合计</strong></td>
            <td :class="pnlWeightedChange >= 0 ? 'text-up' : 'text-down'">{{ formatChange(pnlWeightedChange) }}</td>
            <td class="amount-cell"><strong>¥{{ formatNum(pnlTotalAmount) }}</strong></td>
            <td class="amount-cell" :class="pnlTotal >= 0 ? 'text-up' : 'text-down'"><strong>¥{{ formatNum(pnlTotal) }}</strong></td>
            <td v-if="showTrackedIndex"></td>
          </tr>
        </tfoot>
      </table>
    </div>
  </AppCard>
</template>

<script setup>
import { computed } from 'vue'
import { changeClass } from '../../utils/changeClass'
import AppCard from '../ui/AppCard.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  activeTab: { type: String, required: true },
  pnlTotal: { type: Number, default: 0 },
  pnlTotalAmount: { type: Number, default: 0 },
  pnlWeightedChange: { type: Number, default: 0 }
})

const showTrackedIndex = computed(() => props.activeTab === 'off_exchange' || props.activeTab === 'combined')

function formatNum(n) {
  const v = n || 0
  try {
    return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  } catch {
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }
}

function formatChange(n, isAmount = false) {
  const val = n || 0
  const prefix = val >= 0 && !isAmount ? '+' : ''
  const suffix = isAmount ? '' : '%'
  return `${prefix}${val.toFixed(2)}${suffix}`
}
</script>

<style scoped>
.card-subtitle {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-normal);
}
.table-responsive {
  overflow-x: auto;
  padding: var(--space-4) var(--space-5);
  -webkit-overflow-scrolling: touch;
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}
.data-table th,
.data-table td {
  padding: var(--space-3) var(--space-4);
  text-align: left;
  vertical-align: middle;
  border-bottom: 1px solid var(--color-border-light);
}
.data-table th {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  background: var(--color-surface-secondary);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}
.data-table tbody tr {
  transition: var(--transition-fast);
}
.data-table tbody tr:hover {
  background: var(--color-surface-hover);
}
.data-table .amount-cell {
  white-space: nowrap;
  font-family: var(--font-family-mono);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.data-table .type-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0.5) var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-full);
  text-transform: capitalize;
}
.data-table .type-badge.on_exchange {
  color: var(--color-info-700);
  background: var(--color-bg-info-subtle);
}
.data-table .type-badge.off_exchange {
  color: var(--color-warning-700);
  background: var(--color-bg-warning-subtle);
}
.data-table .footer-row {
  background: var(--color-surface-secondary);
}
.data-table .footer-row td {
  border-top: 2px solid var(--color-border-medium);
  border-bottom: none;
  font-weight: var(--font-weight-semibold);
}
.text-up { color: var(--color-text-up) !important; }
.text-down { color: var(--color-text-down) !important; }
</style>