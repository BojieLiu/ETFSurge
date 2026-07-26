<template>
  <div class="input-wrapper" :class="wrapperClasses">
    <label v-if="label" :for="inputId" class="input-label">{{ label }}</label>
    <div class="input-group" :class="groupClasses">
      <span v-if="prefix" class="input-affix input-prefix" aria-hidden="true">{{ prefix }}</span>
      <input
        :id="inputId"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :readonly="readonly"
        :required="required"
        :min="min"
        :max="max"
        :step="step"
        :maxlength="maxlength"
        :autocomplete="autocomplete"
        :aria-describedby="describedBy"
        :aria-invalid="error ? 'true' : 'false'"
        :class="inputClasses"
        class="input-field"
        @input="onInput"
        @blur="onBlur"
        @focus="onFocus"
        @keydown="onKeydown"
      />
      <span v-if="suffix" class="input-affix input-suffix" aria-hidden="true">{{ suffix }}</span>
      <span v-if="loading" class="input-loader" aria-hidden="true">
        <svg class="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
          <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
        </svg>
      </span>
      <button
        v-if="clearable && !disabled && !readonly && modelValue !== null && modelValue !== ''"
        type="button"
        class="input-clear"
        @click="clearValue"
        @mousedown.prevent
        aria-label="清除内容"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
    <div v-if="helpText || error" class="input-meta" :class="{ 'input-meta--error': error }" role="alert" :aria-live="error ? 'assertive' : 'polite'">
      <span v-if="error" class="input-error">{{ error }}</span>
      <span v-else-if="helpText" class="input-help">{{ helpText }}</span>
      <span v-if="showCount && maxlength" class="input-count">{{ String(modelValue || '').length }} / {{ maxlength }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  type: { type: String, default: 'text' },
  label: String,
  placeholder: String,
  disabled: Boolean,
  readonly: Boolean,
  required: Boolean,
  error: String,
  helpText: String,
  clearable: Boolean,
  loading: Boolean,
  prefix: String,
  suffix: String,
  min: [String, Number],
  max: [String, Number],
  step: [String, Number],
  maxlength: Number,
  autocomplete: { type: String, default: 'off' },
  size: { type: String, default: 'md', validator: v => ['sm', 'md', 'lg'].includes(v) },
  id: String
})

const emit = defineEmits(['update:modelValue', 'blur', 'focus', 'keydown', 'clear'])

const inputId = ref(props.id || `input-${Math.random().toString(36).slice(2, 9)}`)
const isFocused = ref(false)
const describedBy = ref('')

const wrapperClasses = computed(() => [
  'input-wrapper',
  `input-wrapper--${props.size}`,
  { 'input-wrapper--disabled': props.disabled, 'input-wrapper--readonly': props.readonly, 'input-wrapper--error': !!props.error, 'input-wrapper--focused': isFocused.value }
])

const groupClasses = computed(() => [
  'input-group',
  { 'input-group--with-prefix': !!props.prefix, 'input-group--with-suffix': !!props.suffix || props.clearable || props.loading }
])

const inputClasses = computed(() => [
  'input-field',
  `input-field--${props.size}`,
  { 'input-field--error': !!props.error }
])

const showCount = computed(() => props.maxlength && !props.error)

const onInput = (e) => {
  const value = props.type === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value
  emit('update:modelValue', value)
}

const onBlur = (e) => {
  isFocused.value = false
  emit('blur', e)
}

const onFocus = (e) => {
  isFocused.value = true
  emit('focus', e)
}

const onKeydown = (e) => {
  emit('keydown', e)
}

const clearValue = () => {
  emit('update:modelValue', props.type === 'number' ? null : '')
  emit('clear')
}
</script>

<style scoped>
/* ==========================================
   Input Styles
   ========================================== */
.input-wrapper {
  display: inline-flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  font-size: var(--font-size-sm);
}

.input-label {
  font: var(--text-caption);
  color: var(--color-text-secondary);
}

.input-wrapper--sm .input-label { font-size: 10px; }
.input-wrapper--lg .input-label { font-size: var(--font-size-sm); }

/* Input Group */
.input-group {
  display: inline-flex;
  align-items: center;
  width: 100%;
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-md);
  transition: var(--transition-colors);
}

.input-group:hover:not(.input-group--disabled):not(.input-group--readonly) {
  border-color: var(--color-border-strong);
}

.input-wrapper--focused .input-group,
.input-field:focus {
  border-color: var(--color-border-focus);
  box-shadow: var(--shadow-focus);
  outline: none;
}

.input-wrapper--error .input-group,
.input-wrapper--error .input-group:hover {
  border-color: var(--color-border-error);
}

.input-wrapper--error .input-wrapper--focused .input-group,
.input-wrapper--error .input-field:focus {
  box-shadow: var(--shadow-focus-error);
}

.input-wrapper--disabled .input-group,
.input-wrapper--readonly .input-group {
  background: var(--color-surface-disabled);
  border-color: var(--color-border-light);
  color: var(--color-text-disabled);
  cursor: not-allowed;
}

/* Sizes */
.input-group--sm { height: var(--input-height-sm); }
.input-group--md { height: var(--input-height-md); }
.input-group--lg { height: var(--input-height-lg); }

.input-field {
  flex: 1;
  width: 0;
  min-width: 0;
  padding: 0 var(--input-padding-x);
  font-family: inherit;
  font-size: var(--input-font-size);
  line-height: var(--line-height-normal);
  color: var(--color-text-primary);
  background: transparent;
  border: none;
  outline: none;
  appearance: none;
}

.input-field::placeholder { color: var(--color-text-tertiary); }
.input-field:disabled { cursor: not-allowed; color: var(--color-text-disabled); }
.input-field[readonly] { cursor: default; }
.input-field[type="number"] { -moz-appearance: textfield; }
.input-field[type="number"]::-webkit-inner-spin-button,
.input-field[type="number"]::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }

.input-field--sm { padding: 0 var(--space-2); font-size: var(--font-size-xs); }
.input-field--md { padding: 0 var(--space-3); font-size: var(--font-size-sm); }
.input-field--lg { padding: 0 var(--space-4); font-size: var(--font-size-base); }

/* Affixes */
.input-affix {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.input-group--sm .input-affix { font-size: var(--font-size-xs); padding: 0 var(--space-2); }
.input-group--md .input-affix { padding: 0 var(--space-3); }
.input-group--lg .input-affix { padding: 0 var(--space-4); }

.input-group--with-prefix .input-field { border-radius: 0 var(--radius-md) var(--radius-md) 0; }
.input-group--with-suffix .input-field { border-radius: var(--radius-md) 0 0 var(--radius-md); }

/* Loader */
.input-loader {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  color: var(--color-brand-600);
  flex-shrink: 0;
}

.input-group--sm .input-loader { width: 16px; height: 16px; }
.input-group--lg .input-loader { width: 24px; height: 24px; }

.spinner {
  width: 100%;
  height: 100%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Clear Button */
.input-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  margin-right: var(--space-1);
  color: var(--color-text-tertiary);
  border-radius: var(--radius-sm);
  transition: var(--transition-fast);
}

.input-group--sm .input-clear { width: 20px; height: 20px; }
.input-group--lg .input-clear { width: 28px; height: 28px; }

.input-clear:hover:not(:disabled) {
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
}

.input-clear:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}

/* Meta */
.input-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-xs);
  line-height: var(--line-height-normal);
}

.input-wrapper--sm .input-meta { font-size: 10px; }

.input-error {
  color: var(--color-text-danger);
}

.input-help {
  color: var(--color-text-tertiary);
}

.input-count {
  color: var(--color-text-tertiary);
  font-family: var(--font-family-mono);
}

.input-meta--error .input-count { color: var(--color-text-danger); }

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  .input-loader .spinner { animation: none; }
}
</style>