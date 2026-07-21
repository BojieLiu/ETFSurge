<template>
  <div class="news-view">
    <PageHeader
      title="资讯监控"
      description="实时推送重要资讯，AI 智能分析对组合的影响"
    >
      <template #action>
        <div class="news-toolbar">
          <div class="news-status" aria-live="polite">
            <span class="status-dot" :class="{ 'status-dot--on': connected }" aria-hidden="true"></span>
            <span>{{ connected ? '实时推送已连接' : '未连接' }}</span>
          </div>

          <div class="level-filter" role="group" aria-label="重要性筛选">
            <span class="filter-label">最低重要性：</span>
            <AppButton
              v-for="lvl in [1,2,3,4,5]"
              :key="lvl"
              variant="outline"
              size="sm"
              :class="{ 'btn--active': minLevel === lvl }"
              @click="minLevel = lvl"
              :aria-pressed="minLevel === lvl"
              :title="mapNewsLevel(lvl).label"
            >
              {{ mapNewsLevel(lvl).stars }} {{ mapNewsLevel(lvl).label }}
            </AppButton>
          </div>
        </div>
      </template>
    </PageHeader>

    <!-- News List -->
    <Section title="最新资讯" :padded="false" :divided="false">
      <AppCard variant="default" :padding="false" v-if="loading && !filteredNews.length">
        <AppSkeleton type="text" :rows="5" />
      </AppCard>

      <div v-else class="news-list">
        <AppCard
          v-for="item in filteredNews"
          :key="item.id"
          variant="outlined"
          class="news-item"
          :class="[`news-item--${mapNewsLevel(item.level).color}`, { 'news-item--important': isImportant(item.level) }]"
          :padding="false"
        >
          <div class="news-item-head">
            <AppBadge
              :variant="mapNewsLevel(item.level).variant"
              :dot="false"
              class="news-level-badge"
            >
              <span class="news-stars" aria-hidden="true">{{ mapNewsLevel(item.level).stars }}</span>
              <span class="news-level-label">{{ mapNewsLevel(item.level).label }}</span>
            </AppBadge>
            <h3 class="news-title" :style="{ color: levelColor(item.level) }">{{ item.title }}</h3>
          </div>

          <p v-if="item.content" class="news-content">{{ item.content }}</p>

          <div class="news-meta">
            <span v-if="item.source" class="news-source">{{ item.source }}</span>
            <span v-if="item.time" class="news-time">{{ item.time }}</span>
            <AppButton
              variant="ghost"
              size="sm"
              class="news-ai-btn"
              @click="analyze(item)"
              :disabled="analyzing"
            >
              <span aria-hidden="true">🤖</span> AI 智能分析
            </AppButton>
          </div>
        </AppCard>

        <div v-if="filteredNews.length === 0" class="news-empty">
          <AppSkeleton type="text" :rows="3" />
        </div>
      </div>
    </Section>

    <!-- AI Impact Panel -->
    <Section v-if="impactPanel" title="AI 智能分析" :padded="false" :divided="false">
      <AppCard variant="elevated" class="impact-panel" aria-live="polite">
        <template #header>
          <h2 class="card__title"><span aria-hidden="true">🤖</span> AI 智能分析</h2>
          <AppButton variant="ghost" size="sm" @click="impactPanel = null" aria-label="关闭分析">✕</AppButton>
        </template>

        <p v-if="impactPanel.summary" class="impact-summary">{{ impactPanel.summary }}</p>

        <div class="impact-block">
          <h3 class="impact-subtitle">影响范围</h3>
          <p>{{ impactPanel.impact_scope }}</p>
        </div>

        <div v-if="impactPanel.affected_holdings && impactPanel.affected_holdings.length" class="impact-block">
          <h3 class="impact-subtitle">对组合内标的的影响</h3>
          <ul class="impact-holdings">
            <li v-for="h in impactPanel.affected_holdings" :key="h.symbol" class="impact-holding">
              <span class="holding-symbol"><code>{{ h.symbol }}</code> {{ h.name }}</span>
              <span class="holding-reason">{{ h.impact_reason }}</span>
            </li>
          </ul>
        </div>

        <div class="impact-disclaimer">
          <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
          <span>{{ impactPanel.disclaimer || '本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负' }}</span>
        </div>
      </AppCard>
    </Section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { newsApi } from '@/api'
import { useNewsWS } from '@/composables/useNewsWS'
import { useToastStore } from '@/stores/toast'
import { usePortfolioStore } from '@/stores/portfolio'
import { mapNewsLevel, isImportant } from '@/utils/newsLevel'
import { PageHeader, Section, AppCard, AppButton, AppBadge, AppSkeleton } from '@/components'

const { show: toast } = useToastStore()
const store = usePortfolioStore()

const news = ref([])
const loading = ref(false)
const seenIds = ref(new Set())
const impactPanel = ref(null)
const analyzing = ref(false)
const minLevel = ref(1)
const connected = ref(false)

const LEVEL_COLORS = {
  red: '#e5484d',
  orange: '#f5901e',
  blue: '#3b82f6',
  gray: '#8a8f98'
}

function levelColor(level) {
  return LEVEL_COLORS[mapNewsLevel(level).color] || LEVEL_COLORS.gray
}

const filteredNews = computed(() => {
  return news.value.filter((it) => (Number(it.level) || 1) >= minLevel.value)
})

async function loadNews() {
  loading.value = true
  try {
    const res = await newsApi.headlines()
    const items = res.data || []
    news.value = items
    items.forEach((it) => { if (it.id != null) seenIds.value.add(it.id) })
    items.filter((it) => isImportant(it.level)).forEach((it) => {
      toast({ type: 'info', title: it.title, message: it.content?.slice(0, 100), duration: 8000 })
    })
  } catch (e) {
    console.error('[NewsView] loadNews failed', e)
  } finally {
    loading.value = false
  }
}

async function analyze(item) {
  if (analyzing.value) return
  analyzing.value = true
  try {
    const res = await newsApi.impact({ news_id: item.id, holdings: store.all.map(h => h.symbol) })
    impactPanel.value = res.data
  } catch (e) {
    console.error('[NewsView] analyze failed', e)
    toast({ type: 'error', message: 'AI 分析失败，请稍后重试' })
  } finally {
    analyzing.value = false
  }
}

// WebSocket
const { connected: wsConnected, connect: wsConnect, disconnect: wsDisconnect } = useNewsWS({
  onMessage: (msg) => {
    if (msg.type === 'news' && msg.data) {
      const item = msg.data
      if (item.id != null && !seenIds.value.has(item.id)) {
        seenIds.value.add(item.id)
        news.value.unshift(item)
      }
      if (isImportant(item.level)) {
        toast({ type: 'info', title: item.title, message: item.content?.slice(0, 100), duration: 8000 })
      }
    }
  },
  onConnect: () => { connected.value = true },
  onDisconnect: () => { connected.value = false }
})

onMounted(() => {
  loadNews()
  wsConnect()
})

onUnmounted(() => {
  wsDisconnect()
})
</script>

<style scoped>
.news-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-section-md);
}

.news-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.news-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-neutral-400);
}

.status-dot--on {
  background: var(--color-success-500);
  box-shadow: 0 0 0 2px var(--color-bg-success-subtle);
}

.level-filter {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.filter-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.filter-btn {
  height: 28px;
  padding: 0 var(--space-2);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-full);
  background: var(--color-surface-secondary);
  border: 1px solid var(--color-border-light);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: var(--transition-fast);
}

.filter-btn:hover,
.filter-btn.active {
  border-color: var(--color-brand-400);
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
}

.filter-btn.active {
  border-color: var(--color-brand-600);
  color: var(--color-brand-700);
}

.news-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.news-item {
  /* Card styling handled by AppCard */
}

.news-item-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.news-level-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
}

.news-level-badge .news-stars {
  font-size: var(--font-size-xs);
  line-height: 1;
}

.news-level-badge .news-level-label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
}

.news-title {
  margin: 0;
  font: var(--text-h4);
  line-height: var(--line-height-snug);
}

.news-content {
  margin: 0 0 var(--space-3);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
}

.news-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.news-source {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.news-time {
  opacity: 0.7;
}

.news-ai-btn {
  margin-left: auto;
}

.impact-panel {
  margin-top: var(--space-4);
}

.impact-summary {
  margin: 0 0 var(--space-4);
  padding: var(--space-4);
  background: var(--color-bg-brand-subtle);
  border-radius: var(--radius-md);
  font: var(--text-body);
  color: var(--color-text-primary);
}

.impact-block {
  margin-bottom: var(--space-4);
}

.impact-subtitle {
  margin: 0 0 var(--space-2);
  font: var(--text-h4);
  color: var(--color-text-primary);
}

.impact-holdings {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.impact-holding {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-md);
}

.holding-symbol code {
  font: var(--text-mono);
  color: var(--color-brand-600);
  background: var(--color-bg-brand-subtle);
  padding: var(--space-half) var(--space-1);
  border-radius: var(--radius-sm);
}

.holding-reason {
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  text-align: right;
  max-width: 60%;
}

.impact-disclaimer {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--color-bg-warning-subtle);
  border-radius: var(--radius-md);
  font: var(--text-body-sm);
  color: var(--color-warning-700);
}

@media (max-width: 639px) {
  .news-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  
  .level-filter {
    justify-content: flex-start;
    overflow-x: auto;
    padding-bottom: var(--space-2);
    -webkit-overflow-scrolling: touch;
  }
  
  .filter-btn {
    flex-shrink: 0;
  }
}
</style>