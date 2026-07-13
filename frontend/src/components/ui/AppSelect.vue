<template>
  <div class="select-wrapper" :class="wrapperClasses">
    <label v-if="label" :for="selectId" class="select-label">{{ label }}</label>
    <div class="select-group" :class="groupClasses">
      <select
        :id="selectId"
        :value="modelValue"
        :disabled="disabled"
        :required="required"
        :multiple="multiple"
        :size="multiple ? 4 : undefined"
        :aria-describedby="describedBy"
        :aria-invalid="error ? 'true' : 'false'"
        :class="selectClasses"
        class="select-field"
        @change="onChange"
        @blur="onBlur"
        @focus="onFocus"
      >
        <option v-if="placeholder && !multiple" value="" disabled>{{ placeholder }}</option>
        <option v-for="opt in options" :key="opt.value" :value="opt.value" :disabled="opt.disabled">
          {{ opt.label }}
        </option>
      </select>
      <div class="select-arrow" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>
      <span v-if="loading" class="select-loader" aria-hidden="true">
        <svg class="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
          <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
        </svg>
      </span>
    </div>
    <div v-if="helpText || error" class="select-meta" :class="{ 'select-meta--error': error }" role="alert" :aria-live="error ? 'assertive' : 'polite'">
      <span v-if="error" class="select-error">{{ error }}</span>
      <span v-else class="select-help">{{ helpText }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: [String, Number, Array],
  options: { type: Array, default: () => [] },
  label: String,
  placeholder: String,
  disabled: Boolean,
  required: Boolean,
  error: String,
  helpText: String,
  loading: Boolean,
  multiple: Boolean,
  size: { type: String, default: 'md', validator: v => ['sm', 'md', 'lg'].includes(v) },
  id: String
})

const emit = defineEmits(['update:modelValue', 'blur', 'focus', 'change'])

const selectId = ref(props.id || `select-${Math.random().toString(36).slice(2, 9)}`)
const isFocused = ref(false)

const wrapperClasses = computed(() => [
  'select-wrapper',
  `select-wrapper--${props.size}`,
  { 'select-wrapper--disabled': props.disabled, 'select-wrapper--error': !!props.error, 'select-wrapper--focused': isFocused.value }
])

const groupClasses = computed(() => [
  'select-group',
  { 'select-group--loading': props.loading }
])

const selectClasses = computed(() => [
  'select-field',
  `select-field--${props.size}`
])

const describedBy = computed(() => {
  const ids = []
  if (props.error) ids.push(`${selectId.value}-error`)
  if (props.helpText && !props.error) ids.push(`${selectId.value}-help`)
  return ids.length ? ids.join(' ') : undefined
})

const onChange = (e) => {
  const value = props.multiple
    ? Array.from(e.target.selectedOptions).map(o => o.value)
    : e.target.value
  emit('update:modelValue', value)
  emit('change', value, e)
}

const onBlur = (e) => {
  isFocused.value = false
  emit('blur', e)
}

const onFocus = (e) => {
  isFocused.value = true
  emit('focus', e)
}
</script>

<style scoped>
/* ==========================================
   Select Styles
   ========================================== */
.select-wrapper {
  display: inline-flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  font-size: var(--font-size-sm);
}

.select-label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.select-wrapper--sm .select-label { font-size: 10px; }
.select-wrapper--lg .select-label { font-size: var(--font-size-sm); }

/* Select Group */
.select-group {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 100%;
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-md);
  transition: var(--transition-colors);
}

.select-group:hover:not(.select-group--disabled) {
  border-color: var(--color-border-strong);
}

.select-wrapper--focused .select-group,
.select-field:focus {
  border-color: var(--color-border-focus);
  box-shadow: var(--shadow-focus);
  outline: none;
}

.select-wrapper--error .select-group,
.select-wrapper--error .select-group:hover {
  border-color: var(--color-border-error);
}

.select-wrapper--error .select-wrapper--focused .select-group,
.select-wrapper--error .select-field:focus {
  box-shadow: var(--shadow-focus-error);
}

.select-wrapper--disabled .select-group {
  background: var(--color-surface-disabled);
  border-color: var(--color-border-light);
  color: var(--color-text-disabled);
  cursor: not-allowed;
}

/* Sizes */
.select-group--sm { height: var(--input-height-sm); }
.select-group--md { height: var(--input-height-md); }
.select-group--lg { height: var(--input-height-lg); }

/* Select Field */
.select-field {
  flex: 1;
  width: 0;
  min-width: 0;
  appearance: none;
  padding: 0 var(--space-10) 0 var(--input-padding-x);
  font-family: inherit;
  font-size: var(--input-font-size);
  line-height: var(--line-height-normal);
  color: var(--color-text-primary);
  background: transparent;
  border: none;
  outline: none;
  cursor: pointer;
}

.select-field:disabled { cursor: not-allowed; color: var(--color-text-disabled); }
.select-field::placeholder { color: var(--color-text-tertiary); }

.select-field--sm { padding: 0 var(--space-8) 0 var(--space-2); font-size: var(--font-size-xs); }
.select-field--md { padding: 0 var(--space-10) 0 var(--space-3); font-size: var(--font-size-sm); }
.select-field--lg { padding: 0 var(--space-12) 0 var(--space-4); font-size: var(--font-size-base); }

/* Multiple select */
.select-field[multiple] {
  height: auto;
  min-height: 120px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
}

/* Arrow */
.select-arrow {
  position: absolute;
  right: var(--space-3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-tertiary);
  pointer-events: none;
  flex-shrink: 0;
}

.select-group--sm .select-arrow { right: var(--space-2); }
.select-group--lg .select-arrow { right: var(--space-4); }

.select-wrapper--disabled .select-arrow { color: var(--color-text-disabled); }

/* Loader */
.select-loader {
  position: absolute;
  right: var(--space-3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  color: var(--color-brand-600);
  flex-shrink: 0;
}

.select-group--sm .select-loader { right: var(--space-2); width: 16px; height: 16px; }
.select-group--lg .select-loader { right: var(--space-4); width: 24px; height: 24px; }

.spinner {
  width: 100%;
  height: 100%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Meta */
.select-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-xs);
  line-height: var(--line-height-normal);
}

.select-wrapper--sm .select-meta { font-size: 10px; }

.select-error { color: var(--color-text-danger); }
.select-help { color: var(--color-text-tertiary); }
.select-meta--error .select-help { color: var(--color-text-danger); }

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  .spinner { animation: none; }
}
</style>