<template>
  <div class="news-view">
    <!-- F29 (round23 §2.4 A4): 资讯分类 tab——旧实现仅 headlines 可达，
         macro/global/stock/research 四端点 UI 不可达（事实死功能）。 -->
    <div class="news-tabs" role="tablist" aria-label="资讯分类">
      <button
        v-for="t in tabs"
        :key="t.value"
        type="button"
        role="tab"
        class="news-tab"
        :class="{ active: activeTab === t.value }"
        :aria-selected="activeTab === t.value"
        @click="switchTab(t.value)"
      >
        {{ t.label }}
      </button>
      <input
        v-if="activeTab === 'stock' || activeTab === 'research'"
        v-model="stockSymbol"
        class="symbol-input"
        placeholder="标的代码（如 600519 / 510300）"
        aria-label="标的代码"
        @keyup.enter="loadNews()"
      />
    </div>

    <div class="news-toolbar">
      <div class="news-status" aria-live="polite">
        <span class="status-dot" :class="{ 'status-dot--on': connected }" aria-hidden="true"></span>
        <span>{{ connected ? '实时推送已连接' : '未连接' }}</span>
      </div>

      <div class="level-filter" role="group" aria-label="重要性筛选">
        <span class="filter-label">最低重要性：</span>
        <button
          v-for="lvl in [1,2,3,4,5]"
          :key="lvl"
          type="button"
          class="filter-btn"
          :class="{ active: minLevel === lvl }"
          @click="minLevel = lvl"
          :aria-pressed="minLevel === lvl"
          :title="mapNewsLevel(lvl).label"
        >
          {{ mapNewsLevel(lvl).stars }} {{ mapNewsLevel(lvl).label }}
        </button>
        <!-- R178 (round52 §9.2 方案C): 排序切换——时间 ↓（默认）/ 重要性 ↓；
             纯前端 sort，无后端改动。全部 tab 条数多时按 level 排序更有用。 -->
        <button
          type="button"
          class="filter-btn sort-toggle"
          :aria-pressed="sortBy === 'level'"
          :title="sortBy === 'level' ? '切回按时间排序' : '按重要等级排序'"
          @click="sortBy = sortBy === 'level' ? 'time' : 'level'"
        >{{ sortBy === 'level' ? '★ 重要性' : '🕐 时间' }}</button>
      </div>
    </div>

    <!-- News List -->
    <section class="card news-card">
      <!-- F31: 半成品不静默上屏——冷启动/数据源熔断时显示不完整提示。
           R8 (round24): 横幅改为脱离文档流（absolute），出现/消失不再下移列表，
           消除布局偏移（CLS）。-->
      <div class="news-partial-banner" :class="{ 'news-partial-banner--show': partial && !loading }" role="status">
        ⚠️ 数据刷新中（当前仅部分数据，稍后自动补全）
      </div>
      <!-- round35 FE2 (R127): 错误态——加载失败不再静默清列表冒充「无资讯」 -->
      <div v-if="loadError && !filteredNews.length" class="news-load-error" role="alert">
        <p>⚠️ 资讯加载失败，请检查后端服务或稍后重试。</p>
        <button class="news-retry-btn" @click="loadNews()">重试</button>
      </div>
      <div v-else-if="loading && !filteredNews.length" class="news-skeleton" role="status" aria-label="加载中">
        <!-- R63 (round28): 骨架屏占位——旧实现单个「加载中...」文本 div 在数据到达后
             被整列表替换，高度从 1 行跳到 N 项 → CLS 0.198 回归（round27 为 0.001）。
             改用固定高度骨架项（与真实 news-item 同高），加载→数据切换不再位移。 -->
        <div v-for="i in 3" :key="i" class="news-skeleton-item">
          <div class="news-skeleton-line news-skeleton-line--badge"></div>
          <div class="news-skeleton-line news-skeleton-line--title"></div>
          <div class="news-skeleton-line news-skeleton-line--content"></div>
        </div>
      </div>
      <ul v-else class="news-list">
        <li
          v-for="item in filteredNews"
          :key="item.id"
          class="news-item"
          :class="[`news-item--${categoryColorClass(item.category, item.level)}`, { 'news-item--important': isImportant(item.level) }]"
        >
          <div class="news-item-head">
              <span
                class="news-level-badge"
                :class="`news-level-badge--${categoryColorClass(item.category, item.level)}`"
                :style="{ color: levelColor(item) }"
              >
                <!-- R83 (round29): 移除抽象数字星——新鲜度即时间，meta 行已显示
                     相对时间（刚刚/3小时前），数字星是重复二次编码且易误读为重要度。
                     other 类不渲染文字标签（灰边灰标题已表意）。 -->
                <span
                  v-if="item.category !== 'other'"
                  class="news-level-label"
                >{{ mapNewsCategory(item.category, item.level).label }}</span>
              </span>
              <!-- R178 (round52 §9.2 方案B-1): 重要等级星级——编码 level（重要度），
                   与旧星（编码 stars 新鲜度）语义不同；全量显示，灰色小字不与 category 抢色。 -->
              <span class="news-importance-stars" :title="`重要等级 ${item.level || 1}/5`" aria-hidden="true">{{ mapLevelStars(item.level) }}</span>
              <h3 class="news-title" :style="{ color: levelColor(item) }">{{ item.title }}</h3>
            </div>

          <p v-if="item.content" class="news-content">{{ item.content }}</p>

          <!-- P1-4 (round20 §五 P1-4): 消费后端预生成的 ai_summary（列表内联展示，
               消除「生成但不消费」冗余）——仅当后端已生成摘要时展示 -->
          <p v-if="item.ai_summary" class="news-ai-summary" :style="{ color: levelColor(item) }">
            <span class="ai-summary-tag" aria-hidden="true">🤖</span> {{ item.ai_summary }}
          </p>

            <div class="news-meta">
             <span v-if="item.source" class="news-source">{{ item.source }}</span>
             <span v-if="item.time" class="news-time" :title="item.time">{{ formatRelativeTime(item.time) }}</span>
             <a v-if="item.url" :href="item.url" target="_blank" rel="noopener" class="news-source-link">查看原文</a>
             <button class="news-ai-btn" :class="{ 'news-ai-btn--active': impactTarget === item.id }" @click="analyze(item)" :disabled="analyzing">
               <span aria-hidden="true">🤖</span> AI 智能分析
             </button>
           </div>

           <!-- F2-8: 行内展开分析区（结果出现在该条卡片内，无滚动/跳转） -->
           <div v-if="impactTarget === item.id" class="impact-inline" aria-live="polite">
             <!-- R45: 层级标签——与新闻卡视觉区分 -->
             <div class="impact-header">🤖 AI 智能分析</div>
             <div v-if="analyzing" class="impact-loading">🤖 AI 分析中…</div>
             <div v-else-if="impactError" class="impact-inline-error">
               <span>AI 分析失败，请稍后重试</span>
               <button class="impact-retry" @click="analyze(item)">重试</button>
             </div>
             <div v-else-if="impactPanel" class="impact-inline-body">
               <button class="impact-close" @click="impactTarget = null; impactPanel = null" aria-label="关闭分析">✕</button>
               <p v-if="impactPanel.summary" class="impact-summary">{{ impactPanel.summary }}</p>
               <div class="impact-block">
                 <h4 class="impact-subtitle">影响范围</h4>
                 <p>{{ impactPanel.impact_scope }}</p>
               </div>
               <div v-if="filteredAffectedHoldings.length" class="impact-block">
                 <h4 class="impact-subtitle">对组合内标的的影响</h4>
                 <ul class="impact-holdings">
                   <!-- R50: 用请求时刻快照（requestHoldings）过滤——不能基于渲染时 store.etfs -->
                   <li v-for="h in filteredAffectedHoldings" :key="h.symbol" class="impact-holding">
                     <span class="holding-symbol"><code>{{ h.symbol }}</code> {{ h.name }}</span>
                     <span class="holding-reason">{{ h.impact_reason }}</span>
                   </li>
                 </ul>
               </div>
               <div class="impact-disclaimer">
                 <span class="disclaimer-icon" aria-hidden="true">⚠️</span>
                 <span>{{ impactPanel.disclaimer || '本工具仅供个人研究，不构成任何投资建议，AI 输出可能存在错误，盈亏自负' }}</span>
               </div>
             </div>
           </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { newsApi } from '../api'
import { useNewsWS } from '../composables/useNewsWS'
import { useToastStore } from '../stores/toast'
import { usePortfolioStore } from '../stores/portfolio'
import { mapNewsLevel, mapNewsCategory, categoryColor, categoryColorClass, isImportant, mapLevelStars } from '../utils/newsLevel'

const { show: toast } = useToastStore()
const store = usePortfolioStore()

const news = ref([])
const loading = ref(false)
const loadError = ref(false)  // round35 FE2 (R127): 失败提示（空态冒充错误态修复）
const seenIds = ref(new Set())
const impactTarget = ref(null) // F2-8: 当前展开分析的新闻 id
const impactPanel = ref(null)  // F2-8: 最近一次分析结果
const impactError = ref(false) // F2-8: 行内失败状态（展示重试）
// R50: 请求时刻的组合代码集快照——渲染过滤用，避免组合变化后误过滤
const requestHoldings = ref(new Set())
const analyzing = ref(false)
const minLevel = ref(1) // 1-5, minimum importance level to show
// R178 (round52 §9.2 方案C): 排序切换——'time'（sort_time 降序，默认）| 'level'（level 降序 + sort_time 次序）
const sortBy = ref('time')

// F29 (round23 §2.4 A4): 资讯分类 tab（all/headlines/macro/global/stock/research）。
// R178 (round52 §9.2 方案A): 新增「全部」tab（三桶去重合并）并设为默认——用户诉求
// 一屏总览；tab 描述：all 不含个股/研报（按 symbol 查询型，全量拉取无意义）。
const tabs = [
  { value: 'all', label: '全部' },
  { value: 'headlines', label: '头条' },
  { value: 'macro', label: '宏观' },
  { value: 'global', label: '国际' },
  { value: 'stock', label: '个股' },
  { value: 'research', label: '研报' },
]
const activeTab = ref('all')
const stockSymbol = ref('600519')
const partial = ref(false) // F31: 冷启动/数据源熔断 partial 标识

function switchTab(v) {
  activeTab.value = v
  loadNews()
}

const LEVEL_COLORS = {
  red: '#e5484d',
  orange: '#f5901e',
  blue: '#3b82f6',
  gray: '#8a8f98',
  green: '#1aa260',
}

// F22: 着色改用 category（极性），level 仅表重要性。category 缺省时回退 level 语义。
function levelColor(item) {
  return categoryColor(item.category, item.level)
}

// R83 (round29): 相对时间格式化——新鲜度即时间，用「刚刚/3小时前/2天前」自然语言
// 替代绝对时刻，悬浮 title 仍显示精确时间。无法解析（如纯 "10:00"）则原样返回。
function formatRelativeTime(t) {
  if (!t) return ''
  const d = new Date(String(t).includes(' ') && !String(t).includes('T') ? String(t).replace(' ', 'T') : t)
  if (isNaN(d.getTime())) return t
  const diff = Date.now() - d.getTime()
  if (diff < 0) return t
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min}分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}小时前`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day}天前`
  return t
}

const filteredNews = computed(() => {
  const filtered = news.value.filter((it) => (Number(it.level) || 1) >= minLevel.value)
  if (sortBy.value === 'level') {
    // R178 方案C: level 降序（同分按 sort_time 降序），纯前端排序
    return filtered.slice().sort((a, b) => {
      const la = Number(a.level) || 1
      const lb = Number(b.level) || 1
      if (la !== lb) return lb - la
      return (Number(b.sort_time) || 0) - (Number(a.sort_time) || 0)
    })
  }
  return filtered
})

async function loadNews() {
  loading.value = true
  try {
    // F29: 按当前 tab 加载对应端点（旧实现仅 headlines）
    // R178: all tab → /news/all（三桶去重合并）
    const t = activeTab.value
    let res = null
    if (t === 'all') {
      res = await newsApi.all()
    } else if (t === 'headlines') {
      res = await newsApi.headlines()
    } else if (t === 'macro') {
      res = await newsApi.macro()
    } else if (t === 'global') {
      res = await newsApi.globalNews()
    } else if (t === 'stock') {
      res = await newsApi.stockNews(stockSymbol.value.trim() || '600519')
    } else if (t === 'research') {
      res = await newsApi.research(stockSymbol.value.trim() || '600519')
    }
    const items = (res && res.data) || []
    loadError.value = false  // round35 FE2: 成功即清除错误态
    // F31 (round23 §2.4 A4): 冷启动/数据源熔断时后端以 X-News-Partial 标记不完整，
    // 前端显示「数据刷新中（部分数据）」而非静默上屏残缺列表。
    partial.value = !!(res && res.headers && String(res.headers['x-news-partial']).toLowerCase() === 'true')
    news.value = items
    items.forEach((it) => { if (it.id != null) seenIds.value.add(it.id) })
    // Toast reminder for important items when entering the news page from elsewhere.
    // R178: all tab 合并视图含头条桶，重要资讯提醒同等生效。
    if (t === 'headlines' || t === 'all') {
      items.filter((it) => isImportant(it.level)).forEach((it) => {
        toast(`重要资讯：${it.title}`, 'warning')
      })
    }
  } catch {
    // round35 FE2: 失败置错误态；保留旧列表内容（不清空冒充无资讯）
    loadError.value = true
    partial.value = false
  } finally {
    loading.value = false
  }
}

/** Sort news array by sort_time descending (primary), fall back to time string */
function sortNews(arr) {
  return arr.slice().sort((a, b) => {
    const ta = a.sort_time != null ? Number(a.sort_time) : (a.time ? new Date(a.time).getTime() / 1000 : 0)
    const tb = b.sort_time != null ? Number(b.sort_time) : (b.time ? new Date(b.time).getTime() / 1000 : 0)
    return tb - ta
  })
}

function handleNews(msg) {
  // F29: WS 实时推送仅作用于头条 tab——其它 tab（宏观/国际/个股/研报）为
  // 独立数据源视图，混入 WS 快讯会污染列表（切 tab 即重载，无需合并）。
  // R178: all tab 为三桶合并视图且含头条桶——与 headlines 同等消费推送。
  if (activeTab.value !== 'headlines' && activeTab.value !== 'all') return
  // news_batch: array of pre-sorted items
  if (msg && msg.type === 'news_batch' && Array.isArray(msg.data)) {
    let added = 0
    for (const it of msg.data) {
      if (!it || !it.title) continue
      if (it.id == null) {
        it.id = `${it.time || Date.now()}_${it.title}`
      }
      if (seenIds.value.has(it.id)) continue
      seenIds.value.add(it.id)
      added++
    }
    if (!added) return
    // Merge — combine existing + new, dedup by id
    const existingIds = new Set(seenIds.value)
    const merged = [...news.value]
    for (const it of msg.data) {
      if (existingIds.has(it.id) && !news.value.some((n) => n.id === it.id)) {
        merged.push(it)
      }
    }
    news.value = sortNews(merged)
    return
  }

  // Single item (legacy news type or raw message)
  const item = msg && msg.data ? msg.data : msg
  if (!item || !item.title) return
  if (item.id == null) {
    item.id = `${item.time || Date.now()}_${item.title}`
  }
  if (seenIds.value.has(item.id)) return
  seenIds.value.add(item.id)
  // Prepend then re-sort to fix prepend-reversal bug
  news.value = sortNews([item, ...news.value])
}

const ws = useNewsWS()
const { connected } = ws
ws.onNews(handleNews)

onMounted(() => {
  loadNews()
  ws.connect()
})

async function analyze(item) {
  // F2-8: 已展开且有结果时再次点击 → 收起（toggle）；失败/分析中状态再次点击 → 重新分析
  if (impactTarget.value === item.id && impactPanel.value && !analyzing.value) {
    impactTarget.value = null
    impactPanel.value = null
    impactError.value = false
    return
  }
  impactTarget.value = item.id
  impactPanel.value = null
  impactError.value = false
  analyzing.value = true
  // R50: 发起请求时快照当前组合代码集（不能基于渲染时 store.etfs）
  requestHoldings.value = new Set((store.etfs || []).map((e) => e.symbol))
  try {
    const portfolio = (store.etfs || []).map((e) => ({ symbol: e.symbol, name: e.name }))
    const res = await newsApi.newsImpact({
      news: { title: item.title, content: item.content },
      portfolio,
    })
    impactPanel.value = res.data
  } catch {
    // F2-8: 失败在行内展示错误 + 重试（不再全局 toast 后无痕）
    impactError.value = true
  } finally {
    analyzing.value = false
  }
}
// R50: 渲染前用请求时刻快照过滤——组合外标的（LLM 幻觉）不展示
const filteredAffectedHoldings = computed(() => {
  const list = impactPanel.value?.affected_holdings || []
  if (!list.length) return []
  return list.filter((h) => requestHoldings.value.has(h.symbol))
})
</script>

<style scoped>
.news-view { display: flex; flex-direction: column; gap: var(--space-6); }
/* F29: 资讯分类 tab 条（美化轮 2026-09-06：药丸化） */
.news-tabs {
  display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2);
  padding: var(--space-2);
  background: var(--color-surface-tertiary);
  border-radius: var(--radius-full);
  border: 1px solid var(--color-border-light);
}
.news-tab {
  padding: var(--space-1.5) var(--space-3);
  border: none; border-radius: var(--radius-full);
  background: transparent; color: var(--color-text-secondary);
  cursor: pointer; font-size: var(--font-size-sm);
  transition: var(--transition-fast);
}
.news-tab:hover {
  color: var(--color-text-primary);
  background: var(--color-surface-hover);
}
.news-tab.active {
  background: var(--color-brand-500);
  color: #fff; font-weight: var(--font-weight-semibold);
  box-shadow: var(--shadow-xs);
}
.symbol-input {
  margin-left: auto; padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light); border-radius: var(--radius-md);
  background: var(--color-surface); color: var(--color-text);
  font-size: var(--font-size-sm); width: 180px;
}
.symbol-input:focus { outline: none; border-color: var(--color-brand-500); }
/* 美化轮（2026-09-06）: 工具栏加 brand 语义左条 + 重要性按钮药丸化 + 连接点走 token 化 */
.news-toolbar {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
  gap: var(--space-3); padding: var(--space-3) var(--space-4);
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-left: 3px solid var(--color-brand-500);
  border-radius: var(--radius-lg);
}
.news-status { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--color-neutral-400); /* 离线：中性灰 */
  transition: var(--transition-fast);
}
.status-dot--on {
  background: var(--color-success-500); /* 在线：token 化绿色 */
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.2);
  animation: pulseDot 1.6s ease-in-out infinite;
}
@keyframes pulseDot { 0%,100% { box-shadow: 0 0 0 3px rgba(34,197,94,0.2); } 50% { box-shadow: 0 0 0 6px rgba(34,197,94,0.05); } }
.level-filter { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.filter-label { font-size: var(--font-size-sm); color: var(--color-text-secondary); }
/* 美化轮: 重要性按钮 → 药丸 toggle（与 ControlPanel 同款品牌语义） */
.filter-btn {
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border-light);
  background: var(--color-surface-secondary);
  border-radius: var(--radius-full);
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs); cursor: pointer;
  transition: var(--transition-fast); white-space: nowrap;
}
.filter-btn:hover {
  border-color: var(--color-brand-300);
  color: var(--color-brand-700);
  background: var(--color-bg-brand-subtle);
}
.filter-btn.active {
  background: var(--color-bg-brand-subtle);
  border-color: var(--color-brand-500);
  color: var(--color-brand-700);
  font-weight: var(--font-weight-semibold);
}
.news-card { position: relative; padding: var(--space-4); min-height: 320px; }
.news-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-3); }
/* R63 (round28): 骨架屏（加载态占位）——与真实 news-item 同高，加载→数据切换无位移（CLS） */
.news-skeleton { display: flex; flex-direction: column; gap: var(--space-3); }

/* round35 FE2 (R127): 加载失败错误态 */
.news-load-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-8);
  color: var(--color-text-tertiary);
}
.news-retry-btn {
  padding: var(--space-2) var(--space-5);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-primary);
  cursor: pointer;
}
.news-retry-btn:hover {
  background: var(--color-bg-subtle, rgba(0, 0, 0, 0.04));
}
.news-skeleton-item {
  border: 1px solid var(--color-border-light);
  border-left-width: 4px;
  border-radius: var(--radius-lg);
  padding: var(--space-3);
  background: var(--color-surface-secondary);
  min-height: 96px;
}
.news-skeleton-line {
  height: 12px;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--color-surface-tertiary) 25%, var(--color-border-light) 50%, var(--color-surface-tertiary) 75%);
  background-size: 200% 100%;
  animation: news-skeleton-shimmer 1.4s ease-in-out infinite;
  margin-bottom: var(--space-2);
}
.news-skeleton-line--badge { width: 30%; height: 10px; }
.news-skeleton-line--title { width: 70%; height: 14px; }
.news-skeleton-line--content { width: 100%; }
@keyframes news-skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
/* R63 (round28): news-item 最小高度——ai_summary 异步出现时避免高度跳变（CLS） */
.news-item { min-height: 84px; }
.news-empty { color: var(--color-text-muted); padding: var(--space-4); text-align: center; }
/* F31: partial（不完整）提示条；R8: 脱离文档流避免布局偏移 */
.news-partial-banner {
  display: none;
  position: absolute; top: 0; left: 0; right: 0;
  padding: var(--space-2) var(--space-4);
  background: var(--color-warning-50, #fffbeb);
  color: var(--color-warning-600, #b45309);
  font-size: var(--font-size-sm);
  border-bottom: 1px solid var(--color-border-light);
  z-index: 1;
}
.news-partial-banner--show { display: block; }
.news-item { border: 1px solid var(--color-border-light); border-left-width: 4px; border-radius: var(--radius-lg); padding: var(--space-3); background: var(--color-surface-secondary); }
.news-item--red { border-left-color: #e5484d; }
.news-item--orange { border-left-color: #f5901e; }
.news-item--blue { border-left-color: #3b82f6; }
.news-item--green { border-left-color: #1aa260; }
.news-item--gray { border-left-color: #8a8f98; }
.news-item--important { box-shadow: 0 0 0 1px rgba(229, 72, 77, 0.25); background: rgba(229, 72, 77, 0.04); }
.news-item-head { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.news-level-badge { display: inline-flex; align-items: center; gap: 4px; font-size: var(--font-size-xs); font-weight: 600; }
/* R178 (round52 §9.2 方案B-1): 重要等级星级——灰色小字，不与 category 徽章抢色 */
.news-importance-stars { font-size: var(--font-size-xs); color: var(--color-text-tertiary, #8a8f98); letter-spacing: 1px; white-space: nowrap; }
.news-stars { letter-spacing: 1px; }
.news-title { margin: 0; font-size: var(--font-size-base); font-weight: 600; }
.news-content { margin: var(--space-2) 0 0; color: var(--color-text-secondary); font-size: var(--font-size-sm); line-height: 1.6; }
.news-ai-summary { margin: var(--space-1) 0 0; background: var(--color-surface-primary); border: 1px dashed var(--color-border); border-radius: var(--radius-sm); padding: 6px 8px; font-size: var(--font-size-xs); line-height: 1.6; }
.ai-summary-tag { margin-right: 2px; }
.news-meta { display: flex; align-items: center; gap: var(--space-3); margin-top: var(--space-2); font-size: var(--font-size-xs); color: var(--color-text-muted); }
.news-ai-btn { margin-left: auto; border: 1px solid var(--color-border); background: var(--color-surface-primary); border-radius: var(--radius-md); padding: 4px 10px; cursor: pointer; font-size: var(--font-size-xs); }
.news-ai-btn:hover { border-color: var(--color-primary); }
.news-ai-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.news-ai-btn--active { border-color: var(--color-primary); color: var(--color-primary); background: var(--color-bg-brand-subtle); }

/* F2-8: 行内展开区 */
.impact-inline { margin-top: var(--space-2); padding: var(--space-3); border-radius: var(--radius-md); background: var(--color-bg-brand-subtle); border-top: 2px solid var(--color-primary); animation: impact-fadein 0.2s ease; }
.impact-header { display: flex; align-items: center; gap: var(--space-1); font-size: var(--font-size-sm); font-weight: 600; color: var(--color-primary-dark); margin-bottom: var(--space-2); }
@keyframes impact-fadein { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
.impact-loading { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.impact-inline-error { display: flex; align-items: center; gap: var(--space-2); color: var(--color-danger-700); font-size: var(--font-size-sm); }
.impact-retry { padding: 2px 10px; border: 1px solid var(--color-border); border-radius: var(--radius-md); cursor: pointer; background: var(--color-surface-primary); font-size: var(--font-size-xs); }
.impact-inline-body { position: relative; max-height: 360px; overflow-y: auto; }
.impact-close { position: absolute; top: 0; right: 0; background: none; border: none; cursor: pointer; color: var(--color-text-muted); font-size: var(--font-size-base); z-index: 1; }
.impact-summary { color: var(--color-text-primary); line-height: 1.7; }
.impact-subtitle { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: var(--space-2) 0 var(--space-1); }
.impact-holdings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.impact-holding { display: flex; flex-direction: column; gap: 2px; border-bottom: 1px dashed var(--color-border-light); padding-bottom: var(--space-2); }
.holding-symbol { font-weight: 600; }
.holding-reason { color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.impact-disclaimer { display: flex; align-items: center; gap: var(--space-2); margin-top: var(--space-2); padding: var(--space-2) var(--space-3); background: var(--color-surface-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-md); font-size: var(--font-size-xs); color: var(--color-text-muted); }
.disclaimer-icon { flex-shrink: 0; }
</style>
