<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">🔥 热点板块排行</h2>
      <p class="section-desc">实时板块热度与资金流向监测</p>
    </div>

    <div class="card">
      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="['tab-btn', { active: activeTab === tab.key }]"
          @click="switchTab(tab.key)"
        >{{ tab.label }}</button>
      </div>

      <!-- P2-8 (round17): 板块热度数据源冷却提示——sectors/heat 返回 degraded=true
           （非零率 <50%）时显式标注；正常时不渲染（不误报，负向断言覆盖） -->
      <div v-if="degraded && activeTab === 'heat'" class="degraded-banner" role="alert">
        ⚠️ 部分板块涨跌幅数据源冷却（非零率 &lt;50%），涨跌幅可能缺失
      </div>

      <div class="card-body">
        <!-- Loading skeleton: O30② (round7 §7 P30②) 行数对齐各 tab 数据量——
             旧实现固定 5 行（48px×5≈240px），hot 加载后 15 条（≈840px）→
             加载完成撑高 ~600px 把下方 AiAdvisor/UnifiedAnalysis 推下视口
             （CLS 0.393 具体交互表现）。按 tab 对齐行数 + card-body min-height。 -->
        <div v-if="loading" class="loading-skeleton">
          <div class="skeleton-row" v-for="i in skeletonRows" :key="i"></div>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="error">{{ error }}</div>

        <!-- Empty -->
        <div v-else-if="!dataList.length" class="empty-state">暂无板块数据</div>

        <!-- Data Table: Hot Plates -->
        <div v-else-if="activeTab === 'hot'" class="data-list">
          <div
            v-for="(item, i) in dataList"
            :key="i"
            class="data-row"
          >
            <span class="row-rank">{{ i + 1 }}</span>
            <div class="row-main">
              <span class="row-name">{{ item.plate_name || item.name }}</span>
              <span class="row-desc" v-if="item.reason || item.hot_reason">
                {{ item.reason || item.hot_reason }}
              </span>
              <span class="row-stocks" v-if="item.lead_stocks || item.stocks">
                领涨: {{ leadStockNames(item) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Data Table: Sector Heat -->
        <div v-else-if="activeTab === 'heat'" class="data-list">
          <div
            v-for="(item, i) in dataList"
            :key="i"
            class="data-row"
          >
            <span class="row-rank">{{ i + 1 }}</span>
            <div class="row-main">
              <span class="row-name">{{ item.sector_name || item.name }}</span>
              <!-- O19 (round8 §7 §5.1D): v-if 改 `!= null` 同时挡 null/undefined——
                   财联社板块热度 change_pct 恒 null，旧 `!== undefined` 不挡 null →
                   null.toFixed 抛 TypeError → 卡片消失 -->
              <span
                v-if="item.change_pct != null"
                :class="['row-change', item.change_pct >= 0 ? 'text-up' : 'text-down']"
              >
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
              </span>
            </div>
            <span class="row-heat" v-if="item.heat_index != null">
              热度: {{ fmtHeat(item.heat_index) }}
            </span>
            <span v-if="item.rank_change != null" :class="['row-rank-chg', item.rank_change >= 0 ? 'text-up' : 'text-down']">
              {{ item.rank_change > 0 ? '↑' : (item.rank_change < 0 ? '↓' : '—') }}{{ item.rank_change ? Math.abs(item.rank_change) : '' }}
            </span>
            <!-- P0-18 (round16 3.19 R4): 板块热度行补「📈 技术」按钮——技术分析对象=
                 领涨个股（heat 条目无自身 symbol，EM 源带 lead_stocks[].symbol）；
                 无领涨股时禁用（旧实现发 /market/chart/undefined 404） -->
            <div class="row-actions">
              <button class="row-action" @click="openTechnical(item)"
                      :disabled="!leadStockSymbol(item)" title="技术分析">📈 技术</button>
              <button class="row-action" @click="emitAnalyze('sector', item)" title="AI 分析">🤖 AI 分析</button>
            </div>
          </div>
        </div>

        <!-- Data Table: Stock Hot Rank -->
        <div v-else-if="activeTab === 'stock'" class="data-list">
          <div
            v-for="(item, i) in dataList"
            :key="i"
            class="data-row data-row--stock"
          >
            <span class="row-rank">{{ i + 1 }}</span>
            <div class="row-main">
              <span class="row-name">{{ item.name }}</span>
              <span class="row-code">{{ item.code || item.symbol }}</span>
              <span class="row-stock-meta">
                <span v-if="item.price" class="row-price">现价 {{ fmtPrice(item.price) }}</span>
                <span v-if="item.sector" class="row-sector">{{ item.sector }}</span>
                <span v-if="item.turnover" class="row-turnover">成交 {{ fmtTurnover(item.turnover) }}</span>
                <span
                  v-for="(c, ci) in (item.concept_tags || []).slice(0, 3)"
                  :key="ci"
                  class="row-chip"
                >{{ c }}</span>
              </span>
            </div>
            <span
              v-if="item.change_pct != null"
              :class="['row-change', item.change_pct >= 0 ? 'text-up' : 'text-down']"
            >
              {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
            </span>
            <div class="row-actions">
              <!-- P0-18 (round16 3.19 R4): 技术分析对象=领涨个股——sectors/heat 条目无
                   symbol/code，旧实现发 /market/chart/undefined 404；无领涨股时禁用 -->
              <button class="row-action" @click="openTechnical(item)"
                      :disabled="!leadStockSymbol(item)" title="技术分析">📈 技术</button>
              <button class="row-action" @click="emitAnalyze('symbol', item)" title="AI 分析">🤖 AI 分析</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- F2-7 步骤E: 技术分析弹窗 -->
    <TechnicalAnalysisModal
      v-if="techModal"
      :symbol="techModal.symbol"
      :name="techModal.name"
      :asset-type="techModal.assetType || 'A'"
      @close="techModal = null"
      @ai="(p) => { techModal = null; emitAnalyze('symbol', p) }"
    />
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { marketApi } from '../../api'
import TechnicalAnalysisModal from './TechnicalAnalysisModal.vue'

// F2-7 步骤E: 行内「AI 分析」事件（联动 MarketAnalysis → UnifiedAnalysis）
const emit = defineEmits(['analyze'])

// Z31: Accept marketTab prop from parent for market-scoped data
const props = defineProps({
  marketTab: { type: String, default: 'A' },
})

const tabs = [
  { key: 'hot', label: '热点板块' },
  { key: 'heat', label: '板块热度' },
  { key: 'stock', label: '热门个股' },
]
const activeTab = ref('hot')
const dataList = ref([])
const loading = ref(false)
const error = ref('')
// P2-8 (round17): sectors/heat 响应 degraded 标记（非零率 <50% → 数据源冷却）
const degraded = ref(false)

// O30②: 骨架行数按各 tab 数据量对齐（hot 15 / heat 20 / stock 50）——
// 加载中与加载后高度级差消除，防布局抖动
const skeletonRows = computed(() => {
  const n = activeTab.value === 'stock' ? 50 : activeTab.value === 'heat' ? 20 : 15
  return Math.min(n, 15) // 渲染上限 15 行（骨架对齐视觉即可，防止 50 行撑爆）
})
const techModal = ref(null)

function fmtPrice(v) {
  return Number(v).toFixed(2)
}

function fmtTurnover(v) {
  const n = Number(v)
  if (!n) return '—'
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(0) + '万'
  return String(n)
}

function fmtHeat(v) {
  const n = Number(v)
  if (!n && n !== 0) return '—'
  return n >= 10000 ? (n / 10000).toFixed(2) + '万' : n.toFixed(1)
}

// F2-7 步骤E: 热点行 → UnifiedAnalysis（symbol / sector 模式）
function emitAnalyze(mode, item) {
  if (mode === 'sector') {
    emit('analyze', { mode: 'sector', query: item.plate_code || item.name, name: item.name || item.plate_name })
  } else {
    emit('analyze', { mode: 'symbol', query: item.symbol || item.code, name: item.name })
  }
}

function openTechnical(item) {
  // P2-N (round10 §5.3): 弹窗 assetType 按条目市场推断——HK→'HK'、US→'US'、
  // 其余→'A'（防港股被当 A 股查 K 线 → 指标全空）
  const itemMarket = (item.market || item.asset_type || props.marketTab || 'A').toUpperCase()
  const assetType = itemMarket === 'HK' || itemMarket === 'US' ? itemMarket : 'A'
  // P0-18 (round16 3.19 R4): 技术分析对象改为领涨个股（sectors/heat 条目无自身
  // symbol；EM 源条目带 lead_stocks[].symbol）——旧实现 symbol=undefined → 404。
  const leadSym = leadStockSymbol(item)
  if (!leadSym) return // 无领涨股 → 按钮已禁用，双保险
  techModal.value = {
    symbol: leadSym,
    name: leadStockName(item),
    assetType,
  }
}

// P0-18: 领涨股 symbol（条目自身无 symbol 时用领涨股）；无 → null（按钮禁用）
function leadStockSymbol(item) {
  if (item.symbol || item.code) return item.symbol || item.code
  const stocks = item.lead_stocks || item.stocks || []
  const first = stocks[0]
  if (!first) return null
  return first.symbol || first.secu_code || first.code || null
}

function leadStockName(item) {
  const stocks = item.lead_stocks || item.stocks || []
  const first = stocks[0]
  if (!first) return item.name
  return first.name || first.secu_name || item.name
}

function leadStockNames(item) {
  const stocks = item.lead_stocks || item.stocks || []
  return stocks.slice(0, 3).map(s => s.name || s.secu_name || '').filter(Boolean).join(', ')
}

async function switchTab(tab) {
  activeTab.value = tab
  // O28 (round7 §7 P28①): 先置 loading 再拉数据——旧实现先 dataList=[] 再异步
  // fetch（loading 未置 true）→ 切换瞬间落入「暂无板块数据」空态闪烁；数据源
  // 冷却时空态持续，用户误以为卡片消失。loading 骨架占位避免闪烁。
  loading.value = true
  dataList.value = []
  degraded.value = false // P2-8: 切换 tab 复位降级标记（避免旧 tab 状态残留）
  error.value = ''
  await fetchData()
}

// Z31: Re-fetch when market tab changes
watch(() => props.marketTab, () => {
  dataList.value = []
  degraded.value = false // P2-8: 市场切换复位降级标记（防旧市场 banner 残留）
  error.value = ''
  fetchData()
})

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    let resp
    switch (activeTab.value) {
      case 'hot':
        resp = await marketApi.getHotPlates(15, props.marketTab)
        break
      case 'heat':
        resp = await marketApi.getSectorHeat(20, props.marketTab)
        break
      case 'stock':
        resp = await marketApi.getStockHotRank(50, props.marketTab)
        break
    }
    // F6 R14: 双兼容——兼容数组（旧）与 {items,total}（hot-plates 契约 v2.0）
    const d = resp.data
    dataList.value = Array.isArray(d) ? d : (d?.items ?? [])
    // P2-8 (round17): sectors/heat 降级标记透传——heat tab 且响应带 degraded=true
    // 时显示冷却提示（hot/stock tab 无此字段 → 恒 false 不误报）
    degraded.value = activeTab.value === 'heat' && !Array.isArray(d) && !!d?.degraded
  } catch (e) {
    error.value = '加载失败: ' + (e?.message || '网络错误')
    dataList.value = []
    degraded.value = false // P2-8: 失败复位降级标记（防 error + banner 同时残留）
  } finally {
    loading.value = false
  }
}

onMounted(() => { fetchData() })
</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--text-lg); font-weight: 600; color: var(--color-text-primary); margin: 0; }
.section-desc { font-size: var(--text-sm); color: var(--color-text-secondary); margin-top: var(--space-1); }

.tab-bar { display: flex; gap: var(--space-1); margin-bottom: var(--space-3); border-bottom: 1px solid var(--color-border); padding-bottom: var(--space-1); }
.tab-btn { padding: var(--space-1) var(--space-3); border: none; background: none; cursor: pointer; font-size: var(--text-sm); color: var(--color-text-secondary); border-radius: var(--radius-sm); }
.tab-btn.active { color: var(--color-primary); background: var(--color-bg-hover); font-weight: 600; }
.tab-btn:hover { background: var(--color-bg-hover); }

/* P2-8 (round17): 数据源冷却提示条（黄色警示，非零率 <50% 时显示） */
.degraded-banner { margin-bottom: var(--space-3); padding: var(--space-2) var(--space-3); background: #fff8e1; border: 1px solid #ffe082; border-radius: var(--radius-md); font-size: var(--text-xs); color: #8d6e00; }

.card-body { min-height: 120px; }
.loading-skeleton { display: flex; flex-direction: column; gap: var(--space-2); }
.skeleton-row { height: 48px; background: var(--color-bg-hover); border-radius: var(--radius-sm); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 0.8; } }
.error { color: var(--color-danger); font-size: var(--text-sm); }
.empty-state { text-align: center; padding: var(--space-6); color: var(--color-text-tertiary); font-size: var(--text-sm); }

.data-list { display: flex; flex-direction: column; gap: var(--space-1); }
.data-row { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2); border-radius: var(--radius-sm); }
.data-row:hover { background: var(--color-bg-hover); }
.row-rank { width: 24px; text-align: center; font-size: var(--text-sm); color: var(--color-text-tertiary); font-weight: 600; }
.row-main { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.row-name { font-size: var(--text-sm); font-weight: 500; color: var(--color-text-primary); }
.row-desc { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.row-stocks { font-size: var(--text-xs); color: var(--color-text-secondary); }
.row-code { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.row-change { font-size: var(--text-sm); font-weight: 500; white-space: nowrap; }
.row-heat { font-size: var(--text-xs); color: var(--color-text-secondary); white-space: nowrap; }
.row-rank-chg { font-size: var(--text-xs); white-space: nowrap; }
.row-actions { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.row-action { padding: 2px 8px; font-size: var(--text-xs); border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface-primary); color: var(--color-text-secondary); cursor: pointer; white-space: nowrap; }
.row-action:hover { border-color: var(--color-primary); color: var(--color-primary); }
.row-stock-meta { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; font-size: var(--text-xs); color: var(--color-text-tertiary); }
.row-price, .row-sector, .row-turnover { color: var(--color-text-secondary); }
.row-chip { padding: 1px 6px; border-radius: var(--radius-full); background: var(--color-bg-brand-subtle, rgba(59, 130, 246, 0.08)); border: 1px solid var(--color-brand-200, rgba(59, 130, 246, 0.2)); color: var(--color-brand-600); font-size: var(--text-xs); }
.data-row--stock { flex-wrap: wrap; }
</style>
