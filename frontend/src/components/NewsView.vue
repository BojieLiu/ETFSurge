<template>
  <div class="news-view">
    <!-- Page Header -->
    <header class="page-header">
      <h1 class="page-title">资讯监控</h1>
      <p class="page-description">实时推送重要资讯，按重要程度着色与评星；支持 AI 智能分析对组合的影响</p>
    </header>

    <div class="news-status" aria-live="polite">
      <span class="status-dot" :class="{ 'status-dot--on': connected }" aria-hidden="true"></span>
      <span>{{ connected ? '实时推送已连接' : '未连接' }}</span>
    </div>

    <!-- News List -->
    <section class="card news-card">
      <div v-if="loading && !news.length" class="news-empty">加载中...</div>
      <ul v-else class="news-list">
        <li
          v-for="item in news"
          :key="item.id"
          class="news-item"
          :class="[`news-item--${mapNewsLevel(item.level).color}`, { 'news-item--important': isImportant(item.level) }]"
        >
          <div class="news-item-head">
            <span
              class="news-level-badge"
              :class="`news-level-badge--${mapNewsLevel(item.level).color}`"
              :style="{ color: levelColor(item.level) }"
            >
              <span class="news-stars" aria-hidden="true">{{ mapNewsLevel(item.level).stars }}</span>
              <span class="news-level-label">{{ mapNewsLevel(item.level).label }}</span>
            </span>
            <h3 class="news-title" :style="{ color: levelColor(item.level) }">{{ item.title }}</h3>
          </div>

          <p v-if="item.content" class="news-content">{{ item.content }}</p>

          <div class="news-meta">
            <span v-if="item.source" class="news-source">{{ item.source }}</span>
            <span v-if="item.time" class="news-time">{{ item.time }}</span>
            <button class="news-ai-btn" @click="analyze(item)" :disabled="analyzing">
              <span aria-hidden="true">🤖</span> AI 智能分析
            </button>
          </div>
        </li>
      </ul>
    </section>

    <!-- AI Impact Panel -->
    <section v-if="impactPanel" class="card impact-panel" aria-live="polite">
      <div class="card-header">
        <h2 class="card-title"><span aria-hidden="true">🤖</span> AI 智能分析</h2>
        <button class="impact-close" @click="impactPanel = null" aria-label="关闭分析">✕</button>
      </div>

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
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { newsApi } from '../api'
import { useNewsWS } from '../composables/useNewsWS'
import { useToast } from '../stores/toast'
import { usePortfolioStore } from '../stores/portfolio'
import { mapNewsLevel, isImportant } from '../utils/newsLevel'

const { toast } = useToast()
const store = usePortfolioStore()

const news = ref([])
const loading = ref(false)
const seenIds = ref(new Set())
const connected = ref(false)
const impactPanel = ref(null)
const analyzing = ref(false)

const LEVEL_COLORS = {
  red: '#e5484d',
  orange: '#f5901e',
  blue: '#3b82f6',
  gray: '#8a8f98',
}

function levelColor(level) {
  return LEVEL_COLORS[mapNewsLevel(level).color] || LEVEL_COLORS.gray
}

async function loadNews() {
  loading.value = true
  try {
    const res = await newsApi.headlines()
    const items = res.data || []
    news.value = items
    items.forEach((it) => { if (it.id != null) seenIds.value.add(it.id) })
    // Toast reminder for important items when entering the news page from elsewhere.
    items.filter((it) => isImportant(it.level)).forEach((it) => {
      toast(`重要资讯：${it.title}`, 'warning')
    })
  } catch {
    news.value = []
  } finally {
    loading.value = false
  }
}

function handleNews(msg) {
  const item = msg && msg.data ? msg.data : msg
  if (!item || item.id == null) return
  if (seenIds.value.has(item.id)) return
  seenIds.value.add(item.id)
  news.value = [item, ...news.value]
}

const ws = useNewsWS()
ws.onNews(handleNews)

onMounted(() => {
  loadNews()
  ws.connect()
  connected.value = ws.connected.value
})

async function analyze(item) {
  analyzing.value = true
  impactPanel.value = null
  try {
    const portfolio = (store.etfs || []).map((e) => ({ symbol: e.symbol, name: e.name }))
    const res = await newsApi.newsImpact({
      news: { title: item.title, content: item.content },
      portfolio,
    })
    impactPanel.value = res.data
  } catch {
    toast('AI 分析失败，请稍后重试', 'error')
  } finally {
    analyzing.value = false
  }
}
</script>

<style scoped>
.news-view { display: flex; flex-direction: column; gap: var(--space-6); }
.news-status { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-text-muted); }
.status-dot--on { background: #2ecc71; box-shadow: 0 0 0 3px rgba(46, 204, 113, 0.2); }
.news-card { padding: var(--space-4); }
.news-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-3); }
.news-empty { color: var(--color-text-muted); padding: var(--space-4); text-align: center; }
.news-item { border: 1px solid var(--color-border-light); border-left-width: 4px; border-radius: var(--radius-lg); padding: var(--space-3); background: var(--color-surface-secondary); }
.news-item--red { border-left-color: #e5484d; }
.news-item--orange { border-left-color: #f5901e; }
.news-item--blue { border-left-color: #3b82f6; }
.news-item--gray { border-left-color: #8a8f98; }
.news-item--important { box-shadow: 0 0 0 1px rgba(229, 72, 77, 0.25); background: rgba(229, 72, 77, 0.04); }
.news-item-head { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.news-level-badge { display: inline-flex; align-items: center; gap: 4px; font-size: var(--font-size-xs); font-weight: 600; }
.news-stars { letter-spacing: 1px; }
.news-title { margin: 0; font-size: var(--font-size-base); font-weight: 600; }
.news-content { margin: var(--space-2) 0 0; color: var(--color-text-secondary); font-size: var(--font-size-sm); line-height: 1.6; }
.news-meta { display: flex; align-items: center; gap: var(--space-3); margin-top: var(--space-2); font-size: var(--font-size-xs); color: var(--color-text-muted); }
.news-ai-btn { margin-left: auto; border: 1px solid var(--color-border); background: var(--color-surface-primary); border-radius: var(--radius-md); padding: 4px 10px; cursor: pointer; font-size: var(--font-size-xs); }
.news-ai-btn:hover { border-color: var(--color-primary); }

.impact-panel { padding: var(--space-4); }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.impact-close { background: none; border: none; cursor: pointer; color: var(--color-text-muted); font-size: var(--font-size-base); }
.impact-summary { color: var(--color-text-primary); line-height: 1.7; }
.impact-subtitle { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: var(--space-3) 0 var(--space-1); }
.impact-holdings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.impact-holding { display: flex; flex-direction: column; gap: 2px; border-bottom: 1px dashed var(--color-border-light); padding-bottom: var(--space-2); }
.holding-symbol { font-weight: 600; }
.holding-reason { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
</style>
