<template>
  <div class="panel-body design-loading">
    <div v-if="failed" class="feature-card loading-card error">
      <div class="error-icon">❌</div>
      <h3 class="loading-title">生成失败</h3>
      <p class="loading-text">{{ failed }}</p>
      <p class="loading-hint">3 秒后将返回设置页，请检查后端服务是否正常运行</p>
      <div class="panel-footer" style="margin-top:20px;text-align:center">
        <AppButton variant="ghost" size="sm" @click="$emit('cancel')">&#8592; 返回</AppButton>
      </div>
    </div>
    <div v-else class="feature-card loading-card">
      <div class="loading-spinner-pulse"></div>
      <h3 class="loading-title">智能组合设计生成中...</h3>
      <p class="loading-text">{{ stepLabel }}</p>
      <!-- F20: 已选标的/维度高亮 -->
      <p v-if="selectedLabel" class="loading-selected">已选：{{ selectedLabel }}</p>
      <div class="loading-progress">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <span class="progress-percent">{{ progress }}%</span>
      </div>
      <div class="loading-section">
        <div class="loading-steps">
          <!-- F20: 步骤高亮对齐 task.stage（数据采集→策略计算→保存→LLM 报告→完成） -->
          <div class="loading-step" :class="stepState(0)">
            <span class="step-icon">&#128200;</span> 采集全市场数据
            <span v-if="stepState(0).done" class="step-check">&#10003;</span>
          </div>
          <div class="loading-step" :class="stepState(1)">
            <span class="step-icon">&#128269;</span> 筛选候选标的
            <span v-if="stepState(1).done" class="step-check">&#10003;</span>
          </div>
          <div class="loading-step" :class="stepState(2)">
            <span class="step-icon">&#9881;</span> 因子评分与权重分配
            <span v-if="stepState(2).done" class="step-check">&#10003;</span>
          </div>
          <div class="loading-step" :class="stepState(3)">
            <span class="step-icon">&#128221;</span> 生成组合方案
            <span v-if="stepState(3).done" class="step-check">&#10003;</span>
          </div>
        </div>
        <div class="loading-hint" v-if="progress > 0">
          {{ timeoutHint }}
        </div>
      </div>
      <div class="panel-footer" style="margin-top:20px;text-align:center">
        <AppButton variant="ghost" size="sm" @click="$emit('cancel')">&#8592; 返回</AppButton>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import AppButton from '../ui/AppButton.vue'

const props = defineProps({
  progress: { type: Number, default: 0 },
  stepLabel: { type: String, default: '正在采集数据...' },
  failed: { type: String, default: '' },
  // F20 (round6 §16.8): 后端任务 stage 对齐（数据采集→策略计算→LLM 报告→完成）
  taskStage: { type: String, default: '' },
  // F20: 已选标的/维度标签
  selectedLabel: { type: String, default: '' },
  // F20: 已等待秒数（超时预估文案）
  elapsedSec: { type: Number, default: 0 },
})

defineEmits(['cancel'])

// F20: task.stage → 当前步骤序号（0-3）。未知 stage 回退到 progress 推断。
const STAGE_STEP = {
  '数据采集与策略计算中': 0,
  '策略计算完成': 1,
  '保存方案': 2,
  '方案已保存': 2,
  'LLM 报告生成中': 3,
  'LLM 报告暂不可用': 3,
  '报告完成': 3,
  '设计完成': 3,
}

function currentStep() {
  const stage = (props.taskStage || '').trim()
  if (STAGE_STEP[stage] !== undefined) return STAGE_STEP[stage]
  // 回退：progress 推断（<20→0, <40→1, <80→2, else 3）
  if (props.progress < 20) return 0
  if (props.progress < 40) return 1
  if (props.progress < 80) return 2
  return 3
}

function stepState(idx) {
  const cur = currentStep()
  return { done: idx < cur, active: idx === cur }
}

const timeoutHint = computed(() => {
  if (props.elapsedSec >= 60) {
    return `已等待 ${Math.floor(props.elapsedSec / 60)} 分钟，预计还需 1-2 分钟`
  }
  return '方案生成中，完成后会通过通知栏提醒您'
})
</script>

<style scoped>
.panel-body {
  padding: var(--space-4) 0;
}

.feature-card {
  max-width: 520px;
  margin: 0 auto;
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.loading-card {
  padding: var(--space-6) var(--space-5);
  text-align: center;
}

.loading-card.error {
  border-color: #e53935;
  background: #fff5f5;
}

.error-icon {
  font-size: 3em;
  margin-bottom: var(--space-3);
}

.loading-title {
  font: var(--text-h4);
  margin: 0 0 var(--space-2);
  color: var(--color-text-primary);
}

.loading-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-3);
}

.loading-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin: var(--space-3) 0 0;
}

.loading-spinner-pulse {
  width: 48px;
  height: 48px;
  margin: 0 auto var(--space-4);
  border: 4px solid var(--color-bg-tertiary);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
  position: relative;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), #42a5f5);
  border-radius: var(--radius-full);
  transition: width 0.5s ease;
  position: relative;
}

.progress-fill::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
  animation: shimmer 2s infinite;
}

@keyframes shimmer {
  to { left: 100%; }
}

.progress-percent {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  min-width: 30px;
  text-align: right;
}

.loading-section {
  text-align: left;
}

.loading-steps {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.loading-step {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  padding: var(--space-2);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.loading-step.done {
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
}

.loading-step.active {
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
  background: rgba(25, 118, 210, 0.08);
}

.step-icon {
  font-size: 1.2em;
  width: 24px;
  text-align: center;
}

.step-check {
  margin-left: auto;
  color: var(--color-success, #43A047);
  font-weight: var(--font-weight-bold);
}
</style>
