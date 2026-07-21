<template>
  <header
    class="page-header"
    :class="{ 'page-header--with-action': $slots.action }"
  >
    <div class="page-header__content">
      <div class="page-header__titles">
        <h1 v-if="title" class="page-header__title">{{ title }}</h1>
        <p v-if="description" class="page-header__description">{{ description }}</p>
      </div>
      <div v-if="$slots.action" class="page-header__action">
        <slot name="action" />
      </div>
    </div>
    <div v-if="$slots.tabs" class="page-header__tabs">
      <slot name="tabs" />
    </div>
    <div v-if="$slots.breadcrumb" class="page-header__breadcrumb">
      <slot name="breadcrumb" />
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: String,
  description: String
})
</script>

<style scoped>
.page-header {
  padding: var(--space-section-sm) 0;
  border-bottom: 1px solid var(--color-border-light);
  margin-bottom: var(--space-section-md);
  flex-shrink: 0;
}

.page-header__content {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-gap-md);
  flex-wrap: wrap;
  margin-bottom: var(--space-gap-sm);
}

.page-header__titles {
  flex: 1;
  min-width: 0;
}

.page-header__title {
  font: var(--text-h2);
  color: var(--color-text-primary);
  margin: 0;
  line-height: var(--line-height-tight);
}

.page-header__description {
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  margin: var(--space-half) 0 0 0;
  max-width: 600px;
}

.page-header__action {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-gap-sm);
}

.page-header__tabs {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--color-border-light);
  margin: calc(var(--space-gap-sm) * -1) calc(var(--space-padding-md) * -1) 0;
  padding: 0 var(--space-padding-md);
  overflow-x: auto;
}

.page-header__breadcrumb {
  margin-top: var(--space-gap-sm);
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

@media (max-width: 639px) {
  .page-header {
    padding: var(--space-section-xs) 0;
    margin-bottom: var(--space-section-sm);
  }
  
  .page-header__content {
    flex-direction: column;
    align-items: stretch;
  }
  
  .page-header__action {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>