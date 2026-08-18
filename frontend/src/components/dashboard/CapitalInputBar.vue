<template>
  <section class="card capital-bar">
    <div class="capital-header">
      <span class="capital-title-icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="1" y="4" width="22" height="16" rx="2" ry="2"/>
          <line x1="1" y1="10" x2="23" y2="10"/>
        </svg>
      </span>
      <h3 class="capital-title">投资本金</h3>
      <p class="capital-desc">设置场内/场外可用资金，点击「重新分配」更新下方数据</p>
    </div>
    <div class="capital-body">
      <div class="capital-inputs">
        <label v-if="activeTab === 'on_exchange'" class="input-group">
          <span class="input-label">场内仓位</span>
          <AppInput
            type="number"
            :modelValue="capitalOn"
            @update:modelValue="$emit('update:capitalOn', $event)"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            aria-label="场内仓位金额"
          />
        </label>
        <label v-else-if="activeTab === 'off_exchange'" class="input-group">
          <span class="input-label">场外仓位</span>
          <AppInput
            type="number"
            :modelValue="capitalOff"
            @update:modelValue="$emit('update:capitalOff', $event)"
            placeholder="输入金额"
            :min="0"
            :step="10000"
            aria-label="场外仓位金额"
          />
        </label>
        <template v-else>
          <label class="input-group">
            <span class="input-label">场内仓位</span>
            <AppInput
              type="number"
              :modelValue="capitalOn"
              @update:modelValue="$emit('update:capitalOn', $event)"
              placeholder="输入金额"
              :min="0"
              :step="10000"
              aria-label="场内仓位金额"
            />
            <button class="btn-rebalance-single" @click.stop="$emit('refresh-on')" aria-label="重新分配场内" title="重新分配场内">
              <span class="btn-icon" aria-hidden="true">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="10"/>
                  <path d="M12 2a10 10 0 0 1 10 10"/>
                  <path d="M12 2v10"/>
                </svg>
              </span>
            </button>
          </label>
          <label class="input-group">
            <span class="input-label">场外仓位</span>
            <AppInput
              type="number"
              :modelValue="capitalOff"
              @update:modelValue="$emit('update:capitalOff', $event)"
              placeholder="输入金额"
              :min="0"
              :step="10000"
              aria-label="场外仓位金额"
            />
            <button class="btn-rebalance-single" @click.stop="$emit('refresh-off')" aria-label="重新分配场外" title="重新分配场外">
              <span class="btn-icon" aria-hidden="true">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="10"/>
                  <path d="M12 2a10 10 0 0 1 10 10"/>
                  <path d="M12 2v10"/>
                </svg>
              </span>
            </button>
          </label>
        </template>
      </div>
      <div class="capital-actions">
        <AppButton variant="secondary" @click="$emit('refresh')">
          <span class="btn-icon" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 2a10 10 0 0 1 10 10"/>
              <path d="M12 2v10"/>
            </svg>
          </span>
          {{ activeTab === 'on_exchange' || activeTab === 'off_exchange' ? '重新分配' : '全部重新分配' }}
        </AppButton>
      </div>
    </div>
  </section>
</template>

<script setup>
import AppInput from '../ui/AppInput.vue'
import AppButton from '../ui/AppButton.vue'

defineProps({
  activeTab: { type: String, required: true },
  capitalOn: { type: Number, required: true },
  capitalOff: { type: Number, required: true }
})

defineEmits(['update:capitalOn', 'update:capitalOff', 'refresh', 'refresh-on', 'refresh-off'])
</script>

<style scoped>
.capital-bar {
  padding: 0;
  margin-bottom: var(--space-5);
  overflow: hidden;
  flex-shrink: 0;
}

/* Header */
.capital-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  background: var(--color-bg-brand-subtle);
  border-bottom: 1px solid var(--color-brand-100);
}
.capital-title-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  background: var(--color-brand-100);
  color: var(--color-brand-600);
  flex-shrink: 0;
}
.capital-title {
  margin: 0;
  font: var(--text-body);
  color: var(--color-brand-800);
  letter-spacing: var(--letter-spacing-wide);
}
.capital-desc {
  margin: 0 0 0 auto;
  font-size: var(--font-size-xs);
  /* R64 (round28): 对比度修复——brand-400(#60a5fa) 在 brand-50 背景上 <4.5:1
     （Lighthouse a11y 82）。改 brand-700 达标。 */
  color: var(--color-brand-700);
  line-height: 1.4;
}

/* Body */
.capital-body {
  padding: var(--space-4) var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

/* Inputs Area */
.capital-inputs {
  display: flex;
  align-items: center;
  gap: var(--space-16);
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}
.input-group {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 200px;
  max-width: 300px;
}
.input-label {
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.btn-rebalance-single {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  /* R64 (round28): 对比度修复——brand-400 在浅色背景 <4.5:1，改 brand-600 达标 */
  color: var(--color-brand-600);
  cursor: pointer;
  transition: all var(--duration-fast);
  flex-shrink: 0;
}
.btn-rebalance-single:hover {
  background: var(--color-brand-100);
  color: var(--color-brand-600);
}
.btn-rebalance-single:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

/* Actions */
.capital-actions {
  flex-shrink: 0;
}

@media (max-width: 600px) {
  .capital-body {
    flex-direction: column;
    align-items: stretch;
  }
  .capital-inputs { flex-direction: column; }
  .capital-actions { align-self: flex-end; }
}
</style>
