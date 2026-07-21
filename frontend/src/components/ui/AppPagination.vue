<template>
  <nav class="pagination" aria-label="分页导航" v-if="pageCount > 1">
    <div class="pagination__info" v-if="showInfo">
      <span>共 {{ total }} 条</span>
      <span>第 {{ page }} / {{ pageCount }} 页</span>
    </div>

    <div class="pagination__controls">
      <button
        class="pagination__btn pagination__btn--first"
        :disabled="page <= 1"
        @click="goToPage(1)"
        :aria-label="t('pagination.first')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
          <polyline points="11 17 6 12 11 7"/>
          <polyline points="18 17 13 12 18 7"/>
        </svg>
      </button>

      <button
        class="pagination__btn pagination__btn--prev"
        :disabled="page <= 1"
        @click="goToPage(page - 1)"
        :aria-label="t('pagination.prev')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
      </button>

      <div class="pagination__pages" role="group" aria-label="页码">
        <button
          v-for="p in visiblePages"
          :key="p"
          :class="['pagination__page', { 'pagination__page--active': page === p, 'pagination__page--ellipsis': p === '...' }]"
          :disabled="p === '...'"
          @click="p !== '...' && goToPage(p)"
          :aria-label="p === '...' ? '' : `第 ${p} 页`"
          :aria-current="page === p ? 'page' : undefined"
        >
          {{ p }}
        </button>
      </div>

      <button
        class="pagination__btn pagination__btn--next"
        :disabled="page >= pageCount"
        @click="goToPage(page + 1)"
        :aria-label="t('pagination.next')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>

      <button
        class="pagination__btn pagination__btn--last"
        :disabled="page >= pageCount"
        @click="goToPage(pageCount)"
        :aria-label="t('pagination.last')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
          <polyline points="13 17 18 12 13 7"/>
          <polyline points="6 17 11 12 6 7"/>
        </svg>
      </button>
    </div>

    <div class="pagination__size" v-if="showSizeChanger">
      <label :for="sizeSelectId" class="pagination__size-label">{{ t('pagination.pageSize') }}</label>
      <select
        :id="sizeSelectId"
        class="pagination__size-select"
        :value="pageSize"
        @change="handleSizeChange"
        aria-label="每页条数"
      >
        <option v-for="size in pageSizes" :key="size" :value="size">{{ size }} {{ t('pagination.perPage') }}</option>
      </select>
    </div>

    <div class="pagination__jumper" v-if="showJumper">
      <span>{{ t('pagination.goto') }}</span>
      <input
        type="number"
        class="pagination__jumper-input"
        :value="page"
        @change="handleJumperChange"
        @keydown.enter="handleJumperChange"
        min="1"
        :max="pageCount"
        aria-label="跳转到第几页"
      >
      <span>{{ t('pagination.page') }}</span>
    </div>
  </nav>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  pageSizes: { type: Array, default: () => [10, 20, 50, 100] },
  showInfo: { type: Boolean, default: true },
  showSizeChanger: { type: Boolean, default: true },
  showJumper: { type: Boolean, default: false },
  pageCount: { type: Number, default: 0 }
})

const emit = defineEmits(['update:modelValue', 'update:pageSize'])

const sizeSelectId = `pagination-size-${Math.random().toString(36).slice(2, 9)}`

const t = (key) => {
  const dict = {
    'pagination.first': '首页',
    'pagination.prev': '上一页',
    'pagination.next': '下一页',
    'pagination.last': '末页',
    'pagination.pageSize': '每页',
    'pagination.perPage': '条',
    'pagination.goto': '跳转到',
    'pagination.page': '页'
  }
  return dict[key] || key
}

const pageCountComputed = computed(() => {
  if (props.pageCount > 0) return props.pageCount
  return Math.max(1, Math.ceil(props.total / props.pageSize))
})

const visiblePages = computed(() => {
  const current = props.modelValue
  const total = pageCountComputed.value
  const delta = 2 // 当前页前后显示的页数

  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1)
  }

  const pages = [1]
  
  let start = Math.max(2, current - delta)
  let end = Math.min(total - 1, current + delta)

  if (start > 2) pages.push('...')
  
  for (let i = start; i <= end; i++) {
    pages.push(i)
  }
  
  if (end < total - 1) pages.push('...')
  
  pages.push(total)
  
  return pages
})

function goToPage(p) {
  const target = Math.max(1, Math.min(p, pageCountComputed.value))
  if (target !== props.modelValue) {
    emit('update:modelValue', target)
  }
}

function handleSizeChange(event) {
  const newSize = Number(event.target.value)
  emit('update:pageSize', newSize)
  emit('update:modelValue', 1)
}

function handleJumperChange(event) {
  const value = parseInt(event.target.value, 10)
  if (!isNaN(value)) {
    goToPage(value)
  } else {
    event.target.value = props.modelValue
  }
}
</script>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.pagination__info {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-shrink: 0;
}

.pagination__controls {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex: 1;
  justify-content: center;
}

.pagination__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-surface-primary);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: var(--transition-fast);
}

.pagination__btn:hover:not(:disabled) {
  border-color: var(--color-brand-400);
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.pagination__btn:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.pagination__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pagination__pages {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.pagination__page {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
  padding: 0 var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: var(--transition-fast);
}

.pagination__page:hover:not(.pagination__page--ellipsis):not(.pagination__page--active) {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.pagination__page:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

.pagination__page--active {
  border-color: var(--color-brand-500);
  background: var(--color-brand-500);
  color: white;
}

.pagination__page--ellipsis {
  color: var(--color-text-tertiary);
  cursor: default;
}

.pagination__size {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.pagination__size-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.pagination__size-select {
  padding: var(--space-1) var(--space-3);
  padding-right: var(--space-8);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-md);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right var(--space-2) center;
}

.pagination__size-select:focus-visible {
  outline: none;
  border-color: var(--color-brand-500);
  box-shadow: var(--shadow-focus);
}

.pagination__jumper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.pagination__jumper-input {
  width: 50px;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-md);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  text-align: center;
}

.pagination__jumper-input:focus-visible {
  outline: none;
  border-color: var(--color-brand-500);
  box-shadow: var(--shadow-focus);
}

@media (max-width: 639px) {
  .pagination {
    gap: var(--space-3);
  }
  
  .pagination__info {
    order: 3;
    width: 100%;
    justify-content: center;
  }
  
  .pagination__size {
    order: 4;
    width: 100%;
    justify-content: center;
  }
  
  .pagination__jumper {
    order: 5;
    width: 100%;
    justify-content: center;
  }
}
</style>