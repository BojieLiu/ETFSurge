<template>
  <AppCard variant="outlined" title="资金设置" description="设置场内外仓位资金" icon="💰" :padding="false" class="capital-input-bar">
    <template #default>
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
            class="capital-input"
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
            class="capital-input"
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
            class="capital-input"
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
            class="capital-input"
          />
        </label>
      </div>
      <div class="capital-actions">
        <AppButton variant="secondary" @click="$emit('refresh')">
          <span class="btn-icon" aria-hidden="true">↻</span>
          刷新
        </AppButton>
      </div>
    </template>
  </AppCard>
</template>

<script setup>
import { AppCard, AppInput, AppButton } from '@/components'

defineProps({
  activeTab: { type: String, required: true },
  capitalOn: { type: Number, required: true },
  capitalOff: { type: Number, required: true }
})

defineEmits(['update:capitalOn', 'update:capitalOff', 'refresh'])
</script>

<style scoped>
.capital-input-bar {
  /* AppCard handles layout */
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

.capital-input {
  flex: 1;
  min-width: 120px;
}

.capital-actions {
  display: flex;
  gap: var(--space-2);
}

@media (max-width: 639px) {
  .capital-inputs {
    flex-direction: column;
    align-items: stretch;
  }
  .input-group {
    width: 100%;
  }
}
</style>