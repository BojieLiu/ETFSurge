<template>
  <div class="panel-body">
    <div class="history-panel" v-if="items.length > 0 || !loaded">
      <div class="history-header">
        <h4>历史方案</h4>
        <button class="history-close" @click="$emit('close')">X</button>
      </div>
      <div v-if="loading" class="history-empty">加载中...</div>
      <div v-else-if="items.length === 0" class="history-empty">暂无历史记录，先生成一个方案吧</div>
      <div v-else class="history-list">
        <div v-for="h in items" :key="h._type + '-' + h.id" class="history-item"
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
          <span class="history-capital">{{ h._type === 'design' ? (h.capital / 10000).toFixed(0) + '万' : '' }}</span>
          <span class="history-detail-link">查看详情</span>
        </div>
      </div>
    </div>
    <div class="wizard-actions-center" style="margin-top: var(--space-4);">
      <AppButton variant="ghost" @click="$emit('close')">返回</AppButton>
    </div>
  </div>
</template>

<script setup>
import { formatDate } from '../../utils/formatDate'
import AppButton from '../ui/AppButton.vue'

defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  loaded: { type: Boolean, default: false }
})

defineEmits(['select', 'close'])
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
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
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
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
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
  color: var(--color-primary);
  opacity: 0;
  transition: opacity var(--transition-fast);
  white-space: nowrap;
  font-weight: var(--font-weight-medium);
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
