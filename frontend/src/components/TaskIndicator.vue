<template>
  <div class="task-indicator" v-if="taskStore.tasks.length > 0">
    <button
      class="task-bell"
      @click="open = !open"
      :aria-label="`进行中的任务: ${runningCount}`"
      aria-haspopup="true"
      :aria-expanded="open"
    >
      <span class="bell-icon" aria-hidden="true">🔔</span>
      <span v-if="runningCount > 0" class="bell-badge">{{ runningCount }}</span>
    </button>

    <div v-if="open" class="task-panel" role="menu">
      <div
        v-for="t in recentTasks"
        :key="t.taskId"
        class="task-item"
        :class="{ 'is-clickable': (t.status === 'completed' || t.status === 'completed_with_errors') && (t.designId || (t.type === 'check' && t.recordId)) }"
        @click="onClickTask(t)"
      >
        <div class="task-item-head">
          <span class="task-label">{{ t.label }}</span>
          <span class="task-status" :class="'status-' + t.status">
            {{ statusText(t.status) }}
          </span>
        </div>
        <div class="task-progress">
          <div class="task-progress-fill" :style="{ width: (t.progress || 0) + '%' }"></div>
        </div>
      </div>
      <div v-if="taskStore.tasks.length > 0" class="task-panel-footer">
        <button v-if="taskStore.taskHasMore" class="btn-load-more" @click.stop="loadMore">加载更多</button>
        <button v-else-if="taskStore.tasks.length > MAX_VISIBLE" class="btn-clear" @click="clearAll">清除历史</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'

const taskStore = useTaskStore()
const router = useRouter()
const open = ref(false)

const MAX_VISIBLE = 5

const runningCount = computed(
  () => taskStore.tasks.filter((t) => t.status === 'running').length
)

const recentTasks = computed(() => {
  const sorted = [...taskStore.tasks].sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
  return sorted.slice(0, MAX_VISIBLE)
})

function statusText(status) {
  if (status === 'running') return '进行中'
  if (status === 'quick_ready') return '方案已就绪'
  if (status === 'completed') return '✅ 完成'
  if (status === 'completed_with_errors') return '已完成（报告异常）'
  if (status === 'failed') return '❌ 失败'
  return status
}

function onClickTask(t) {
  // Z27: check 任务经 recordId 跳组合分析页；design 任务直达 AI 设计页。
  // round34-B7 C3：旧实现 push('/?designId=') 的 query 全库无消费者（死深链），
  // AI 设计已升独立路由 /ai，任务详情经 taskStore 状态恢复。
  if (t.status === 'completed' || t.status === 'completed_with_errors') {
    if (t.type === 'check' && t.recordId) {
      router.push('/portfolio-analysis')
    } else if (t.designId) {
      router.push('/ai')
    }
  }
  open.value = false
}

async function loadMore() {
  await taskStore.loadMoreTasks()
}

function clearAll() {
  taskStore.clearAllCompleted()
}
</script>

<style scoped>
.task-indicator {
  position: relative;
}

.task-bell {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: var(--space-1);
  font-size: 1.1rem;
  line-height: 1;
}

.bell-badge {
  position: absolute;
  top: -2px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--color-danger, #e53935);
  color: #fff;
  font-size: 0.7rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.task-panel {
  position: absolute;
  top: calc(100% + var(--space-2));
  right: 0;
  width: 240px;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: var(--radius-md, 8px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: var(--space-2);
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.task-item {
  padding: var(--space-2);
  border-radius: var(--radius-sm, 6px);
  background: var(--color-bg-soft, #f5f6f8);
}

.task-item.is-clickable {
  cursor: pointer;
}

.task-item.is-clickable:hover {
  background: var(--color-bg-hover, #eceef1);
}

.task-panel-footer {
  display: flex;
  justify-content: center;
  padding: var(--space-1) 0 0;
  border-top: 1px solid var(--color-border, #e0e0e0);
  margin-top: var(--space-1);
}

.btn-clear,
.btn-load-more {
  background: transparent;
  border: none;
  color: var(--color-text-secondary, #666);
  font-size: 0.75rem;
  cursor: pointer;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm, 4px);
}

.btn-clear:hover,
.btn-load-more:hover {
  background: var(--color-bg-hover, #eceef1);
  color: var(--color-text, #333);
}

.task-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-1);
  font-size: 0.85rem;
}

.task-status {
  font-size: 0.75rem;
}

.task-progress {
  height: 6px;
  border-radius: 999px;
  background: var(--color-track, #e0e0e0);
  overflow: hidden;
}

.task-progress-fill {
  height: 100%;
  background: var(--color-primary, #1976d2);
  transition: width 0.3s ease;
}

.status-completed .task-progress-fill {
  background: var(--color-success, #43a047);
}

.status-failed .task-progress-fill {
  background: var(--color-danger, #e53935);
}
</style>
