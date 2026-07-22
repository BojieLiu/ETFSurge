<template>
  <section class="card capital-bar">
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
      <label v-else class="input-group dual">
        <span class="input-label">场内仓位</span>
        <AppInput
          type="number"
          :modelValue="capitalOn"
          @update:modelValue="$emit('update:capitalOn', $event)"
          placeholder="输入金额"
          :min="0"
          :step="10000"
          size="sm"
          aria-label="场内仓位金额"
        />
        <span class="input-label">场外仓位</span>
        <AppInput
          type="number"
          :modelValue="capitalOff"
          @update:modelValue="$emit('update:capitalOff', $event)"
          placeholder="输入金额"
          :min="0"
          :step="10000"
          size="sm"
          aria-label="场外仓位金额"
        />
      </label>
    </div>
    <div class="capital-actions">
      <AppButton variant="secondary" @click="$emit('refresh')">
        <span class="btn-icon" aria-hidden="true">↻</span>
        刷新
      </AppButton>
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

defineEmits(['update:capitalOn', 'update:capitalOff', 'refresh'])
</script>

<style scoped>
.capital-bar {
  padding: var(--space-4) var(--space-5);
}
.capital-inputs {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}
.input-group {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1;
  min-width: 200px;
}
.input-group.dual {
  flex: none;
}
.input-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.capital-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: flex-end;
}
@media (max-width: 480px) {
  .capital-inputs .input-group.dual { flex-direction: column; }
  .capital-bar { flex-direction: column; align-items: stretch; }
  .capital-actions { justify-content: stretch; }
  .capital-actions .btn { width: 100%; justify-content: center; }
}
</style>
