<template>
  <section class="news-digest">
    <div class="digest-header">
      <h3 class="digest-title">🗞️ 重要资讯</h3>
      <router-link to="/news" class="digest-more">资讯页查看全部 ›</router-link>
    </div>

    <!-- loading：骨架 3 行，与真实 item 同高防 CLS -->
    <div v-if="loading && !items.length" class="digest-skeleton" role="status" aria-label="资讯加载中">
      <div v-for="i in 3" :key="i" class="digest-skeleton-item">
        <div class="digest-skeleton-line digest-skeleton-line--badge"></div>
        <div class="digest-skeleton-line digest-skeleton-line--title"></div>
      </div>
    </div>

    <!-- error：显式降级 + 重试（非静默清空） -->
    <div v-else-if="loadError && !items.length" class="digest-error" role="alert">
      <p>⚠️ 资讯加载失败</p>
      <button class="digest-retry" @click="connect">重试</button>
    </div>

    <!-- empty：WS 无推送时的静态提示（非交易时段常见态） -->
    <div v-else-if="!items.length" class="digest-empty">
      <p>暂无重要资讯</p>
      <router-link to="/news" class="digest-empty-cta">去资讯页查看 ›</router-link>
    </div>

    <!-- ready：Top N 重要资讯 -->
    <ul v-else class="digest-list">
      <li v-for="item in topItems" :key="item.id" class="digest-item" :class="{ 'digest-item--important': isImportant(item) }">
        <span v-if="item.category && item.category !== 'other'" class="digest-badge" :class="`digest-badge--${item.category}`">
          {{ categoryLabel(item.category) }}
        </span>
        <span class="digest-stars" :title="`重要等级 ${item.level || 1}/5`" aria-hidden="true">{{ levelStars(item.level) }}</span>
        <span class="digest-title-text" :title="item.title">{{ item.title }}</span>
        <span v-if="item.time" class="digest-time">{{ relativeTime(item.time) }}</span>
      </li>
    </ul>
  </section>
</template>

<script setup>
// R54 (round54-frontend-polish): Dashboard 重要资讯摘要（Top 3）。
// 独立最小四态组件——不复用 NewsView（其 tab/筛选/管理逻辑过重），
// 自持一条 useNewsWS 订阅（方案文档 §3.2 权衡：WS 连接 +1 已知可接受）。
import { ref, computed, onMounted } from 'vue'
import { useNewsWS } from '../../composables/useNewsWS'

const props = defineProps({
  limit: { type: Number, default: 3 },
})

const items = ref([])
const loadError = ref(false)
const wsReady = ref(false)

const { connected, connect, onNews } = useNewsWS((msg) => {
  wsReady.value = true
  loadError.value = false
  if (msg.type === 'news' && msg.data) {
    // 新消息插到头部，保持最多 20 条缓冲（够排序即可）
    items.value = [msg.data, ...items.value].slice(0, 20)
  } else if (Array.isArray(msg)) {
    items.value = msg.slice(0, 20)
  } else if (msg.type === 'snapshot' && Array.isArray(msg.data)) {
    items.value = msg.data.slice(0, 20)
  }
})

// 按重要等级（level 降序）取 Top N；level 缺省按 1 处理
const topItems = computed(() => {
  return [...items.value]
    .sort((a, b) => (b.level || 1) - (a.level || 1))
    .slice(0, props.limit)
})

function isImportant(item) {
  return (item.level || 1) >= 4
}

function levelStars(level) {
  const n = Math.min(5, Math.max(1, level || 1))
  return '★'.repeat(n) + '☆'.repeat(5 - n)
}

const CATEGORY_LABELS = {
  headline: '头条',
  macro: '宏观',
  global: '国际',
  stock: '个股',
  research: '研报',
}
function categoryLabel(category) {
  return CATEGORY_LABELS[category] || category
}

// 相对时间（对齐 NewsView 口径的最小实现）
function relativeTime(timeStr) {
  try {
    const t = new Date(timeStr).getTime()
    if (Number.isNaN(t)) return ''
    const diff = Date.now() - t
    const min = Math.floor(diff / 60000)
    if (min < 1) return '刚刚'
    if (min < 60) return `${min}分钟前`
    const h = Math.floor(min / 60)
    if (h < 24) return `${h}小时前`
    return `${Math.floor(h / 24)}天前`
  } catch {
    return ''
  }
}

onMounted(() => {
  connect()
})
</script>

<style scoped>
.news-digest {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-4) var(--space-5);
}
.digest-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}
.digest-title {
  margin: 0;
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.digest-more {
  font-size: var(--font-size-xs);
  color: var(--color-text-link);
  text-decoration: none;
}
.digest-more:hover { text-decoration: underline; }

.digest-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.digest-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-normal);
  padding: var(--space-1) 0;
}
.digest-item--important .digest-title-text {
  font-weight: var(--font-weight-medium);
}
.digest-badge {
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  padding: 0 var(--space-1);
  border-radius: var(--radius-xs);
  background: var(--color-surface-tertiary);
  color: var(--color-text-secondary);
}
.digest-badge--headline { background: var(--color-bg-danger-subtle); color: var(--color-text-danger); }
.digest-badge--macro { background: var(--color-bg-brand-subtle); color: var(--color-brand-700); }
.digest-badge--global { background: var(--color-bg-info-subtle); color: var(--color-info-700); }
.digest-stars {
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-warning);
  letter-spacing: -0.05em;
}
.digest-title-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
}
.digest-time {
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.digest-skeleton { display: flex; flex-direction: column; gap: var(--space-2); }
.digest-skeleton-item { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-2) 0; }
.digest-skeleton-line {
  height: 0.875rem;
  border-radius: var(--radius-xs);
  background: linear-gradient(90deg, var(--color-surface-tertiary) 25%, var(--color-surface-secondary) 50%, var(--color-surface-tertiary) 75%);
  background-size: 200% 100%;
  animation: digest-shimmer 1.5s ease-in-out infinite;
}
.digest-skeleton-line--badge { width: 64px; height: 0.75rem; }
.digest-skeleton-line--title { width: 100%; }
@keyframes digest-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.digest-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--color-text-danger);
  font-size: var(--font-size-sm);
}
.digest-retry {
  font-size: var(--font-size-xs);
  color: var(--color-brand-600);
  background: transparent;
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-2);
  cursor: pointer;
}
.digest-empty {
  text-align: center;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  padding: var(--space-4) 0;
}
.digest-empty-cta {
  display: inline-block;
  margin-left: var(--space-2);
  font-size: var(--font-size-xs);
  color: var(--color-text-link);
  text-decoration: none;
}
.digest-empty-cta:hover { text-decoration: underline; }

@media (prefers-reduced-motion: reduce) {
  .digest-skeleton-line { animation: none; }
}
@media (max-width: 640px) {
  .digest-time { display: none; }
}
</style>
