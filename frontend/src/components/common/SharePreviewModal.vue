<template>
  <div v-if="visible" class="share-preview-mask" @click.self="$emit('close')">
    <div class="share-preview-modal" role="dialog" aria-modal="true" aria-label="分享图预览">
      <div class="share-preview-header">
        <span class="share-preview-title">{{ title || '分享预览' }}</span>
        <button class="share-preview-close" @click="$emit('close')" aria-label="关闭">✕</button>
      </div>
      <div class="share-preview-body">
        <p v-if="generating" class="share-preview-loading">图片生成中…</p>
        <img v-else-if="imageUrl" class="share-preview-img" :src="imageUrl" alt="分享图预览" />
        <p v-else class="share-preview-loading">图片生成失败，请重试</p>
        <p v-if="copyState === 'ok'" class="share-preview-tip share-preview-tip--ok">已复制到剪贴板，去粘贴分享吧 ✓</p>
        <p v-else-if="copyState === 'fail'" class="share-preview-tip share-preview-tip--err">复制失败（浏览器拒绝或不支持），可改用下载</p>
        <p v-else-if="copyState === 'unsupported'" class="share-preview-tip share-preview-tip--err">当前浏览器不支持复制图片，请改用下载</p>
      </div>
      <div class="share-preview-footer">
        <button class="btn-ghost-sm btn-primary-sm" @click="$emit('copy')" :disabled="generating || !imageUrl">复制到剪贴板</button>
        <button class="btn-ghost-sm" @click="$emit('download')" :disabled="generating || !imageUrl">下载图片</button>
        <button class="btn-ghost-sm" @click="$emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, default: false },
  title: { type: String, default: '分享预览' },
  imageUrl: { type: String, default: '' },
  generating: { type: Boolean, default: false },
  copyState: { type: String, default: '' },
})
defineEmits(['close', 'copy', 'download'])
</script>

<style scoped>
.share-preview-mask {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
  padding: var(--space-4, 16px);
}
.share-preview-modal {
  width: min(560px, 94vw); max-height: 90vh; overflow: auto;
  background: var(--color-surface-primary, #fff);
  border-radius: var(--radius-xl, 16px);
  box-shadow: var(--shadow-lg, 0 12px 40px rgba(0,0,0,0.3));
}
.share-preview-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--color-border-light, #e5e7eb);
}
.share-preview-title { font-weight: 600; font-size: 16px; color: var(--color-text-primary, #111827); }
.share-preview-close { border: none; background: transparent; font-size: 16px; cursor: pointer; color: var(--color-text-secondary, #6b7280); }
.share-preview-body { padding: 16px 18px; text-align: center; }
.share-preview-img { width: 100%; border-radius: 8px; border: 1px solid var(--color-border-light, #e5e7eb); }
.share-preview-loading { color: var(--color-text-secondary, #6b7280); font-size: 14px; }
.share-preview-tip { font-size: 13px; margin: 10px 0 0; }
.share-preview-tip--ok { color: var(--color-success-600, #16a34a); }
.share-preview-tip--err { color: var(--color-danger-600, #dc2626); }
.share-preview-footer { display: flex; gap: 8px; justify-content: center; padding: 0 18px 18px; flex-wrap: wrap; }
.btn-ghost-sm { padding: 6px 16px; font-size: 13px; color: var(--color-text-secondary); background: transparent; border: 1px solid var(--color-border-light); border-radius: 999px; cursor: pointer; }
.btn-ghost-sm:hover:not(:disabled) { background: var(--color-surface-hover); color: var(--color-text-primary); }
.btn-ghost-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary-sm { background: var(--color-brand-600, #2563eb); border-color: var(--color-brand-600, #2563eb); color: #fff; }
.btn-primary-sm:hover:not(:disabled) { background: var(--color-brand-700, #1d4ed8); color: #fff; }
</style>
