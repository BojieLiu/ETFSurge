<template>
  <AppCard
    variant="outlined"
    title="智能组合设计"
    description="输入资金，一键生成进攻/平衡/防御三种风格的 ETF 组合方案"
    icon="✨"
    class="design-wizard"
    :padding="false"
  >
    <div class="design-wizard__body">
      <div class="capital-input-section">
        <label class="capital-label">
          <span class="capital-currency">¥</span>
          <span>投资金额</span>
        </label>
        <div class="capital-input-wrapper">
          <AppInput type="number" v-model="localCapital" min="10000" step="10000" placeholder="请输入金额" />
        </div>
        <p class="capital-hint">建议 10 万元以上以获得更好的分散效果</p>

        <div class="capital-presets">
          <AppButton
            v-for="amt in [100000, 500000, 1000000]"
            :key="amt"
            variant="outline"
            size="sm"
            :class="{ 'btn--active': Number(localCapital) === amt }"
            @click="localCapital = amt"
          >
            {{ (amt / 10000).toFixed(0) }}万
          </AppButton>
        </div>
      </div>

      <div class="wizard-actions-center">
        <AppButton variant="primary" size="lg" @click="startDesign" :disabled="!localCapital || localCapital < 10000">
          ✨ 开始设计
        </AppButton>
        <AppButton variant="ghost" @click="$emit('cancel')">取消</AppButton>
      </div>
    </div>

    <template #footer>
      <span class="design-wizard__footer-text">
        流程：扫描全市场 ETF → 三层筛选 → LLM 精选 → 三套方案
      </span>
    </template>
  </AppCard>
</template>

<script setup>
import { ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppCard from '@/components/ui/AppCard.vue'

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
.design-wizard {
  max-width: 520px;
  margin: 0 auto;
}

.design-wizard__body {
  padding: var(--card-padding);
}

.capital-input-section {
  margin-bottom: var(--space-4);
}

.capital-label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

.capital-currency {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.capital-input-wrapper {
  margin-bottom: var(--space-2);
}

.capital-hint {
  margin: 0 0 var(--space-4);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.capital-presets {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.capital-presets .btn--active {
  border-color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
  color: var(--color-brand-700);
}

.wizard-actions-center {
  display: flex;
  justify-content: center;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.design-wizard__footer-text {
  display: block;
  text-align: center;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  padding: var(--space-2) 0;
}
</style>