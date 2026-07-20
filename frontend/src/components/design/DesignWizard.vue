<template>
  <div class="panel-body design-wizard">
    <div class="feature-card">
      <div class="feature-card-header">
        <span class="feature-card-icon" aria-hidden="true">&#10024;</span>
        <div>
          <h3 class="feature-card-title">智能组合设计</h3>
          <p class="feature-card-subtitle">输入资金，一键生成进攻/平衡/防御三种风格的 ETF 组合方案</p>
        </div>
      </div>

      <div class="feature-card-body">
        <div class="capital-input-section">
          <label class="capital-label">
            <span class="capital-currency">&#165;</span>
            <span>投资金额</span>
          </label>
          <div class="capital-input-wrapper">
            <AppInput type="number" v-model="localCapital" min="10000" step="10000" />
          </div>
          <p class="capital-hint">建议 10 万元以上以获得更好的分散效果</p>

          <div class="capital-presets">
            <button
              v-for="amt in [100000, 500000, 1000000]"
              :key="amt"
              class="preset-btn"
              :class="{ active: Number(localCapital) === amt }"
              @click="localCapital = amt"
            >{{ (amt / 10000).toFixed(0) }}万</button>
          </div>
        </div>

        <div class="wizard-actions-center">
          <AppButton variant="primary" size="lg" @click="startDesign" :disabled="!localCapital || localCapital < 10000">
            &#10024; 开始设计
          </AppButton>
          <AppButton variant="ghost" @click="$emit('cancel')">取消</AppButton>
        </div>
      </div>

      <div class="feature-card-footer">
        <span>流程：扫描全市场 ETF &#8594; 三层筛选 &#8594; LLM 精选 &#8594; 三套方案</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import AppButton from '../ui/AppButton.vue'
import AppInput from '../ui/AppInput.vue'

const props = defineProps({
  capital: { type: Number, default: 500000 }
})

const emit = defineEmits(['start-design', 'cancel'])

const localCapital = ref(props.capital)

watch(() => props.capital, (val) => {
  localCapital.value = val
})

function startDesign() {
  if (!localCapital.value || localCapital.value < 10000) return
  emit('start-design', localCapital.value)
}
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

.feature-card-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-5) var(--space-3);
}

.feature-card-icon {
  font-size: 2em;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
  flex-shrink: 0;
}

.feature-card-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-1);
}

.feature-card-subtitle {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin: 0;
  line-height: 1.4;
}

.feature-card-body {
  padding: var(--space-3) var(--space-5) var(--space-5);
}

.feature-card-footer {
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  text-align: center;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.capital-input-section {
  text-align: center;
  padding: var(--space-4) 0;
}

.capital-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  margin-bottom: var(--space-4);
}

.capital-currency {
  font-size: 1.5em;
  color: var(--color-primary);
}

.capital-input-wrapper {
  max-width: 240px;
  margin: 0 auto var(--space-3);
}

.capital-input-wrapper :deep(input) {
  text-align: center;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  padding: var(--space-3);
}

.capital-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin: 0 0 var(--space-4);
  text-align: center;
}

.capital-presets {
  display: flex;
  gap: var(--space-3);
  justify-content: center;
  margin-bottom: var(--space-5);
}

.preset-btn {
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-surface-secondary, #fff);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-weight: var(--font-weight-medium);
}

.preset-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-bg-tertiary);
}

.preset-btn.active {
  background: var(--color-primary);
  color: #fff;
  border-color: var(--color-primary);
}

.wizard-actions-center {
  display: flex;
  gap: var(--space-3);
  justify-content: center;
  margin-top: var(--space-4);
}
</style>
