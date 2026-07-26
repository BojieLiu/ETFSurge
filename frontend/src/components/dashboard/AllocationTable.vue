<template>
  <AppCard :title="title" icon="📋">
    <div class="table-responsive">
      <table class="data-table alloc-table">
        <thead>
          <tr>
            <th scope="col">代码</th>
            <th scope="col">名称</th>
            <th scope="col">权重</th>
            <th scope="col" class="amount-header">目标金额</th>
            <th scope="col" class="amount-header">现价</th>
            <th scope="col">涨跌幅</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.symbol">
            <td><code>{{ item.symbol }}</code></td>
            <td><strong>{{ item.name }}</strong></td>
            <td><span class="weight-badge">{{ (item.target_weight * 100).toFixed(1) }}%</span></td>
            <td class="amount-cell">¥{{ formatNum(item.target_amount) }}</td>
            <td>¥{{ formatPrice(item.current_price) }}</td>
            <td :class="changeClass(item.change_pct)">
              <span class="change-value">{{ formatChange(item.change_pct) }}</span>
            </td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="footer-row">
            <td colspan="2"><strong>现金仓位</strong></td>
            <td><span class="weight-badge">{{ (cashPct * 100).toFixed(1) }}%</span></td>
            <td class="amount-cell"><strong>¥{{ formatNum(cashAmount) }}</strong></td>
            <td colspan="2">—</td>
          </tr>
        </tfoot>
      </table>
    </div>
  </AppCard>
</template>

<script setup>
import { changeClass } from '../../utils/changeClass'
import AppCard from '../ui/AppCard.vue'

defineProps({
  items: { type: Array, default: () => [] },
  cashPct: { type: Number, default: 0 },
  cashAmount: { type: Number, default: 0 },
  title: { type: String, required: true }
})

function formatNum(n) {
  const v = n || 0
  try {
    return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  } catch {
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }
}

function formatPrice(v) {
  return v != null ? v.toFixed(2) : '—'
}

function formatChange(pct) {
  return pct != null ? (pct > 0 ? '+' : '') + pct.toFixed(2) + '%' : '—'
}
</script>

<style scoped>
.table-responsive {
  overflow-x: auto;
  padding: var(--space-4) var(--space-5);
  -webkit-overflow-scrolling: touch;
  flex: 1;
  min-height: 0;
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
.data-table td code {
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  background: var(--color-surface-tertiary);
  padding: var(--space-0.5) var(--space-1);
  border-radius: var(--radius-sm);
}
.data-table.alloc-table { font-size: var(--font-size-xs); }
.data-table.alloc-table th,
.data-table.alloc-table td { padding: var(--space-2) var(--space-3); }
.data-table.alloc-table td:first-child { width: 85px; }
.data-table.alloc-table td:nth-child(2) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
.data-table.alloc-table .amount-cell { min-width: 100px; }
.data-table .weight-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0.5) var(--space-2);
  font-family: var(--font-family-mono);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-brand-700);
  background: var(--color-bg-brand-subtle);
  border-radius: var(--radius-full);
}
.data-table .change-value {
  font-family: var(--font-family-mono);
  font-weight: var(--font-weight-semibold);
}
.data-table .amount-cell {
  white-space: nowrap;
  font-family: var(--font-family-mono);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.data-table th.amount-header {
  text-align: right;
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