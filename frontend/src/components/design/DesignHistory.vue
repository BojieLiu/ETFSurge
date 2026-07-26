<template>
  <div class="panel-body">
    <div class="history-panel" v-if="items.length > 0 || loading || loaded">
      <div class="history-header">
        <h4>任务列表</h4>
        <button class="history-close" @click="$emit('close')">X</button>
      </div>
      <div class="history-filters">
        <button v-for="opt in filterOptions" :key="opt.key"
                class="filter-tab" :class="{ active: statusFilter === opt.key }"
                @click="statusFilter = opt.key">
          {{ opt.label }}
        </button>
      </div>
      <div v-if="loading" class="history-empty">加载中...</div>
      <div v-else-if="filteredItems.length === 0 && items.length === 0" class="history-empty">暂无任务记录</div>
      <div v-else-if="filteredItems.length === 0" class="history-empty">当前筛选项无匹配任务</div>
      <div v-else class="history-list">
        <div v-for="h in filteredItems" :key="h._type + '-' + h.id" class="history-item"
             @click="$emit('select', h.id, h)">
          <span class="history-icon">{{ h._type === 'check' ? '🔍' : '💡' }}</span>
          <span class="history-task-type" :class="h._type">{{ h._type === 'design' ? '智能组合设计' : '策略检查与分析' }}</span>
          <span class="history-status" :class="'status-' + (h.status || 'completed')">
            <template v-if="h.status === 'completed'">✅ 成功</template>
            <template v-else-if="h.status === 'failed'">❌ 失败</template>
            <template v-else-if="h.status === 'running'">⏳ 运行中</template>
            <template v-else>✅ 成功</template>
          </span>
          <span class="history-date">{{ formatDate(h.created_at) }}</span>
          <span class="history-capital">{{ h._type === 'design' && typeof h.capital === 'number' && h.capital > 0 ? (h.capital / 10000).toFixed(0) + '万' : '' }}</span>
          <span v-if="h.error_message" class="history-error" :title="h.error_message">{{ h.error_message.slice(0, 40) }}{{ h.error_message.length > 40 ? '...' : '' }}</span>
          <span class="history-detail-link" :class="{'detail-error': h.status === 'failed'}">
            <template v-if="h.status === 'completed' && h._type === 'design'">📊 查看方案</template>
            <template v-else-if="h.status === 'completed' && h._type === 'check'">📋 查看报告</template>
            <template v-else-if="h.status === 'failed'">⚠️ 查看错误</template>
            <template v-else>→ 查看详情</template>
          </span>
        </div>
      </div>
    </div>
    <div class="wizard-actions-center" style="margin-top: var(--space-4);">
      <AppButton variant="ghost" @click="$emit('close')">返回</AppButton>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { formatDate } from '../../utils/formatDate'
import AppButton from '../ui/AppButton.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  loaded: { type: Boolean, default: false }
})

defineEmits(['select', 'close'])

const statusFilter = ref('all')
const filterOptions = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '运行中' },
  { key: 'completed', label: '已完成' },
  { key: 'failed', label: '失败' },
]

const filteredItems = computed(() => {
  if (statusFilter.value === 'all') return props.items
  return props.items.filter(h => h.status === statusFilter.value)
})
</script>

<style scoped>
.panel-body {
  padding: var(--space-4) 0;
}

.history-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  margin-top: var(--space-4);
  overflow: hidden;
  max-height: 420px;
  overflow-y: auto;
  background: var(--color-surface-secondary);
  box-shadow: var(--shadow-sm);
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-tertiary);
  position: sticky;
  top: 0;
  z-index: 1;
}

.history-header h4 {
  margin: 0;
  font: var(--text-h4);
  color: var(--color-text-primary);
}

.history-close {
  border: none;
  background: none;
  cursor: pointer;
  font-size: var(--font-size-lg);
  color: var(--color-text-secondary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
  line-height: 1;
}

.history-close:hover {
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
}

.history-filters {
  display: flex;
  gap: 0;
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-secondary);
}

.filter-tab {
  border: none;
  background: none;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  transition: all var(--transition-fast);
  position: relative;
  font-weight: var(--font-weight-medium);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.filter-tab:hover {
  color: var(--color-text-primary);
  border-bottom-color: var(--color-border);
}

.filter-tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.history-empty {
  padding: var(--space-10) var(--space-4);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
}

.history-list {
  display: flex;
  flex-direction: column;
}

.history-item {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  transition: all var(--transition-fast);
  border-bottom: 1px solid var(--color-border);
}

.history-item:hover {
  background: var(--color-bg-secondary);
  transform: translateX(4px);
}

.history-item:last-child {
  border-bottom: none;
}

.history-item:active {
  background: var(--color-bg-tertiary);
  transform: translateX(2px);
}

.history-date {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  min-width: 110px;
  white-space: nowrap;
}

.history-capital {
  font: var(--text-body);
  color: var(--color-text);
  min-width: 60px;
  white-space: nowrap;
}

.history-style {
  font-size: var(--font-size-2xs);
  padding: var(--space-0) var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.history-detail-link {
  margin-left: auto;
  font-size: var(--font-size-2xs);
  white-space: nowrap;
  font-weight: var(--font-weight-semibold);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-primary-soft, #e3f2fd);
  color: var(--color-primary, #1565c0);
  border: 1px solid var(--color-primary-border, #bbdefb);
  opacity: 0;
  transition: all var(--transition-fast);
  cursor: pointer;
  line-height: 1.3;
}

.history-detail-link.detail-error {
  background: var(--color-danger-soft, #fce4ec);
  color: var(--color-danger, #c62828);
  border-color: #ffcdd2;
}

.history-item:hover .history-detail-link {
  opacity: 1;
}

.history-detail-link:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.08));
}

.history-status {
  font-size: var(--font-size-2xs);
  padding: var(--space-0) var(--space-2);
  border-radius: var(--radius-full);
  white-space: nowrap;
  font-weight: var(--font-weight-medium);
  flex-shrink: 0;
}

.history-status.status-completed {
  color: #2e7d32;
}

.history-status.status-failed {
  color: #c62828;
}

.history-status.status-running {
  color: #ef6c00;
}

.history-item:hover .history-detail-link {
  opacity: 1;
}

.history-task-type {
  font-size: var(--font-size-2xs);
  padding: var(--space-0) var(--space-2);
  border-radius: var(--radius-full);
  white-space: nowrap;
  font-weight: var(--font-weight-medium);
  flex-shrink: 0;
}

.history-task-type.design {
  background: #e3f2fd;
  color: #1565c0;
  border: 1px solid #bbdefb;
}

.history-task-type.check {
  background: #fff3e0;
  color: #e65100;
  border: 1px solid #ffe0b2;
}

.wizard-actions-center {
  display: flex;
  gap: var(--space-3);
  justify-content: center;
}
</style>
