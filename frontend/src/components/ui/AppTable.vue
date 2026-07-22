<template>
  <div class="table-wrapper" :class="{ 'table-wrapper--sticky-header': stickyHeader }">
    <table class="table" :role="role">
      <thead v-if="columns.length" class="table__thead">
        <tr class="table__header-row">
          <th
            v-for="col in columns"
            :key="col.key"
            :class="[
              'table__th',
              col.align && `table__th--${col.align}`,
              col.sortable && 'table__th--sortable',
              col.width && 'table__th--fixed'
            ]"
            :style="{ width: col.width, minWidth: col.minWidth }"
            :aria-sort="sortColumn === col.key ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'"
            @click="col.sortable && handleSort(col.key)"
            scope="col"
          >
            <div class="table__th-content">
              <span class="table__th-label">{{ col.label }}</span>
              <span v-if="col.sortable" class="table__th-sort" aria-hidden="true">
                <svg v-if="sortColumn === col.key && sortDirection === 'asc'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <polyline points="18 15 12 9 6 15"/>
                </svg>
                <svg v-else-if="sortColumn === col.key && sortDirection === 'desc'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" opacity="0.3">
                  <polyline points="18 15 12 9 6 15"/>
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </span>
            </div>
          </th>
        </tr>
      </thead>
      <tbody class="table__tbody">
        <tr
          v-for="(row, rowIndex) in data"
          :key="getRowKey(row, rowIndex)"
          :class="[
            'table__tr',
            striped && rowIndex % 2 === 1 && 'table__tr--striped',
            hoverable && 'table__tr--hoverable',
            selectable && 'table__tr--selectable',
            rowClass ? rowClass(row) : ''
          ]"
          @click="selectable && handleRowClick(row, $event)"
          @dblclick="selectable && handleRowDblClick(row, $event)"
          tabindex="selectable ? 0 : undefined"
          @keydown.enter="selectable && handleRowClick(row, $event)"
          @keydown.space.prevent="selectable && handleRowClick(row, $event)"
        >
          <template v-for="col in columns" :key="col.key">
            <td
              :class="[
                'table__td',
                col.align && `table__td--${col.align}`,
                col.class
              ]"
              :style="{ width: col.width, minWidth: col.minWidth }"
            >
              <slot :name="`cell-${col.key}`" :row="row" :value="getCellValue(row, col)" :index="rowIndex">
                <slot :name="`cell`" :row="row" :col="col" :value="getCellValue(row, col)" :index="rowIndex">
                  <div v-if="col.render" v-html="col.render(row, rowIndex)" />
                  <span v-else>{{ formatCellValue(getCellValue(row, col), col) }}</span>
                </slot>
              </slot>
            </td>
          </template>
        </tr>
        
        <tr v-if="data.length === 0" class="table__tr--empty">
          <td :colspan="columns.length" class="table__empty">
            <slot name="empty">
              <div class="table__empty-content">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48" aria-hidden="true">
                  <rect x="3" y="3" width="18" height="18" rx="2"/>
                  <path d="M9 9h6v6H9z"/>
                </svg>
                <p>{{ emptyText }}</p>
              </div>
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div v-if="pagination" class="table__pagination">
    <AppPagination
      :page="page"
      :pageSize="pageSize"
      :total="total"
      :page-sizes="pageSizes"
      @update:page="handlePageChange"
      @update:pageSize="handlePageSizeChange"
    />
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import AppPagination from './AppPagination.vue'

const props = defineProps({
  columns: {
    type: Array,
    required: true
  },
  data: {
    type: Array,
    default: () => []
  },
  rowKey: {
    type: [String, Function],
    default: 'id'
  },
  rowClass: Function,
  striped: { type: Boolean, default: true },
  hoverable: { type: Boolean, default: true },
  selectable: { type: Boolean, default: false },
  stickyHeader: { type: Boolean, default: false },
  density: {
    type: String,
    default: 'comfortable',
    validator: v => ['compact', 'comfortable', 'spacious'].includes(v)
  },
  emptyText: { type: String, default: '暂无数据' },
  sortColumn: String,
  sortDirection: { type: String, default: 'asc', validator: v => ['asc', 'desc'].includes(v) },
  pagination: { type: Boolean, default: false },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  pageSizes: { type: Array, default: () => [10, 20, 50, 100] },
  role: { type: String, default: 'table' }
})

const emit = defineEmits([
  'sort', 'row-click', 'row-dblclick', 'selection-change',
  'update:page', 'update:pageSize', 'page-change', 'page-size-change'
])

function getRowKey(row, index) {
  return typeof props.rowKey === 'function' ? props.rowKey(row, index) : row[props.rowKey] ?? `row-${index}`
}

function getCellValue(row, col) {
  if (col.key.includes('.')) {
    return col.key.split('.').reduce((obj, key) => obj?.[key], row)
  }
  return row[col.key]
}

function formatCellValue(value, col) {
  if (value === null || value === undefined || value === '') return '—'
  if (col.format && typeof col.format === 'function') return col.format(value)
  return value
}

function handleSort(key) {
  if (props.sortColumn === key) {
    emit('sort', key, props.sortDirection === 'asc' ? 'desc' : 'asc')
  } else {
    emit('sort', key, 'asc')
  }
}

function handleRowClick(row, event) {
  if (event.target.closest('button, a, input, select, label, .table__action')) return
  emit('row-click', row, event)
}

function handleRowDblClick(row, event) {
  emit('row-dblclick', row, event)
}

function handlePageChange(page) {
  emit('update:page', page)
  emit('page-change', page, props.pageSize)
}

function handlePageSizeChange(pageSize) {
  emit('update:pageSize', pageSize)
  emit('update:page', 1)
  emit('page-size-change', pageSize)
  emit('page-change', 1, pageSize)
}
</script>

<style scoped>
.table-wrapper {
  overflow-x: auto;
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-light);
  background: var(--color-surface-primary);
}

.table-wrapper--sticky-header .table__thead {
  position: sticky;
  top: 0;
  z-index: 10;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.table__thead {
  background: var(--color-surface-secondary);
}

.table__th {
  padding: var(--table-cell-padding-y) var(--table-cell-padding-x);
  text-align: left;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  white-space: nowrap;
  border-bottom: 1px solid var(--color-border-medium);
  user-select: none;
  transition: var(--transition-fast);
}

.table__th--center { text-align: center; }
.table__th--right { text-align: right; }

.table__th--sortable {
  cursor: pointer;
}

.table__th--sortable:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.table__th--fixed {
  position: sticky;
  left: 0;
  z-index: 5;
}

.table__th-content {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.table__th-sort {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-tertiary);
  flex-shrink: 0;
}

.table__tbody {
  background: var(--color-surface-primary);
}

.table__tr {
  border-bottom: 1px solid var(--color-border-light);
  transition: var(--transition-fast);
}

.table__tr:last-child {
  border-bottom: none;
}

.table__tr--striped:nth-child(even) {
  background: var(--color-surface-secondary);
}

.table__tr--hoverable:hover {
  background: var(--color-surface-hover);
}

.table__tr--selectable {
  cursor: pointer;
}

.table__tr--selectable:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--color-brand-500);
}

.table__td {
  padding: var(--table-cell-padding-y) var(--table-cell-padding-x);
  vertical-align: middle;
  color: var(--color-text-primary);
}

.table__td--center { text-align: center; }
.table__td--right { text-align: right; }

.table__tr--empty .table__empty {
  padding: var(--space-12) var(--space-6);
  text-align: center;
}

.table__empty-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-tertiary);
}

.table__empty-content svg {
  opacity: 0.5;
}

.table__empty-content p {
  margin: 0;
  font-size: var(--font-size-sm);
}

/* Density */
.table--compact .table__th,
.table--compact .table__td {
  padding: var(--density-compact-cell-padding-y) var(--density-compact-cell-padding-x);
}

.table--comfortable .table__th,
.table--comfortable .table__td {
  padding: var(--density-comfortable-cell-padding-y) var(--density-comfortable-cell-padding-x);
}

.table--spacious .table__th,
.table--spacious .table__td {
  padding: var(--density-spacious-cell-padding-y) var(--density-spacious-cell-padding-x);
}

/* Row height */
.table--compact .table__tr { min-height: var(--density-compact-row-height); }
.table--comfortable .table__tr { min-height: var(--density-comfortable-row-height); }
.table--spacious .table__tr { min-height: var(--density-spacious-row-height); }

/* Pagination */
.table__pagination {
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
}
</style>