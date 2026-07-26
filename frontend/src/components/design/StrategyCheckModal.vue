<template>
  <div v-if="visible" class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-container">
      <div class="modal-header">
        <h3>选择分析类型</h3>
        <button class="modal-close" @click="$emit('close')">&times;</button>
      </div>
      <div class="modal-body">
        <p class="modal-desc">请选择需要检查的组合类型：</p>
        <div class="strategy-type-options">
          <div class="strategy-type-card" @click="$emit('select-type', 'on_exchange')">
            <span class="st-icon">&#127881;</span>
            <div class="st-content">
              <span class="st-title">场内组合分析</span>
              <span class="st-desc">分析交易所上市 ETF 组合（股票、行业 ETF 等）</span>
            </div>
          </div>
          <div class="strategy-type-card" @click="$emit('select-type', 'off_exchange')">
            <span class="st-icon">&#127974;</span>
            <div class="st-content">
              <span class="st-title">场外组合分析</span>
              <span class="st-desc">分析场外基金组合（联接基金、指数增强等）</span>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <AppButton variant="ghost" @click="$emit('close')">取消</AppButton>
      </div>
    </div>
  </div>
</template>

<script setup>
import AppButton from '../ui/AppButton.vue'

defineProps({
  visible: { type: Boolean, default: false }
})

defineEmits(['select-type', 'close'])
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-4);
}

.modal-container {
  background: var(--color-surface-primary, #fff);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl, 0 20px 60px rgba(0,0,0,0.3));
  max-width: 480px;
  width: 100%;
  overflow: hidden;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.modal-header h3 {
  margin: 0;
  font: var(--text-h4);
}

.modal-close {
  border: none;
  background: none;
  font-size: 1.5em;
  cursor: pointer;
  color: var(--color-text-secondary);
  padding: var(--space-1);
  line-height: 1;
  border-radius: var(--radius-sm);
}

.modal-close:hover {
  background: var(--color-bg-secondary);
}

.modal-body {
  padding: var(--space-5);
}

.modal-desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-4);
}

.modal-footer {
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: center;
}

.strategy-type-options {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.strategy-type-card {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-normal);
  background: var(--color-surface-secondary);
}

.strategy-type-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.st-icon {
  font-size: 1.8em;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
  flex-shrink: 0;
}

.st-content {
  flex: 1;
}

.st-title {
  display: block;
  font: var(--text-h4);
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.st-desc {
  display: block;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: 1.4;
}
</style>
