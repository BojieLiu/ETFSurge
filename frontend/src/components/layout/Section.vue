<template>
  <section
    class="section"
    :class="[
      `section--${size}`,
      { 'section--divided': divided },
      { 'section--bordered': bordered },
      { 'section--padded': padded }
    ]"
    :id="id"
    :aria-labelledby="ariaLabelledby"
  >
    <header v-if="$slots.header || title || description" class="section__header">
      <div class="section__titles">
        <h2 v-if="title" :class="titleTag" class="section__title">{{ title }}</h2>
        <p v-if="description" class="section__description">{{ description }}</p>
      </div>
      <div class="section__actions">
        <slot name="header" />
      </div>
    </header>

    <div class="section__content">
      <slot />
    </div>

    <footer v-if="$slots.footer" class="section__footer">
      <slot name="footer" />
    </footer>
  </section>
</template>

<script setup>
defineProps({
  title: String,
  description: String,
  titleTag: { type: String, default: 'h2', validator: v => ['h1', 'h2', 'h3', 'h4'].includes(v) },
  size: {
    type: String,
    default: 'md',
    validator: v => ['xs', 'sm', 'md', 'lg', 'xl'].includes(v)
  },
  divided: { type: Boolean, default: false },
  bordered: { type: Boolean, default: false },
  padded: { type: Boolean, default: true },
  id: String,
  ariaLabelledby: String
})
</script>

<style scoped>
.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-gap-md);
}

.section__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-gap-md);
  flex-wrap: wrap;
}

.section__titles {
  flex: 1;
  min-width: 0;
}

.section__title {
  margin: 0 0 var(--space-half);
  font: var(--text-h3);
  color: var(--color-text-primary);
}

.section__description {
  margin: 0;
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
}

.section__actions {
  display: flex;
  align-items: center;
  gap: var(--space-gap-sm);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.section__content {
  flex: 1;
  min-height: 0;
  width: 100%;
}

.section__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-gap-sm);
  padding-top: var(--space-gap-md);
  border-top: 1px solid var(--color-border-light);
  flex-wrap: wrap;
}

/* Sizes */
.section--xs { gap: var(--space-section-xs); }
.section--sm { gap: var(--space-section-sm); }
.section--md { gap: var(--space-section-md); }
.section--lg { gap: var(--space-section-lg); }
.section--xl { gap: var(--space-section-xl); }

/* Divided */
.section--divided > * + * {
  border-top: 1px solid var(--color-border-light);
  padding-top: var(--space-section-md);
  margin-top: calc(var(--space-section-md) * -1);
}

/* Bordered */
.section--bordered {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--card-padding);
}

.section--bordered .section__header {
  margin: calc(var(--card-padding) * -1) calc(var(--card-padding) * -1) var(--space-gap-md);
  padding: var(--card-padding) var(--card-padding) 0;
}

.section--bordered .section__content {
  padding: 0;
}

.section--bordered .section__footer {
  margin: var(--space-gap-md) calc(var(--card-padding) * -1) calc(var(--card-padding) * -1);
  padding: var(--space-gap-md) var(--card-padding) 0;
}
</style>