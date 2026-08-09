<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">🔍 标的分析</h2>
      <p class="section-desc">搜索股票/ETF/板块/指数，查看 AI 深度解读与行情数据</p>
    </div>

    <!-- Analysis mode tabs -->
    <div class="analysis-tabs" role="tablist">
      <button
        v-for="mode in modes" :key="mode.value"
        :class="['analysis-tab', { active: activeMode === mode.value, disabled: mode.disabled }]"
        :disabled="mode.disabled"
        @click="switchMode(mode.value)"
        role="tab" :aria-selected="activeMode === mode.value"
        :title="mode.disabled ? '美股/港股暂不支持板块分析' : mode.label"
      >
        {{ mode.label }}
      </button>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="input-row">
          <div class="search-wrap">
            <input
              type="text"
              :value="activeSearch.searchQuery.value"
              @input="onInput"
              :placeholder="currentPlaceholder"
              :title="currentPlaceholder"
              class="text-input"
              @keydown.enter="onEnterKeydown($event)"
              @focus="activeSearch.onSearchFocus()"
              @blur="activeSearch.onSearchBlur()"
            />
            <!-- F7 R18 + O30 (round7 §7 P30①): 三模式自动补全下拉——sector/index 模式
                 复用同一下拉（后端 /search kind 参数 + 键盘导航 + Enter 选中） -->
            <ul v-if="activeSearch.showDropdown.value" class="search-dropdown">
              <li
                v-for="(item, i) in activeSearch.searchResults.value"
                :key="item.symbol + i"
                :class="['search-option', { active: i === activeSearch.activeIndex.value }]"
                @mousedown.prevent="pickSearchItem(item)"
              >
                <span class="opt-name">{{ item.name }}</span>
                <span class="opt-symbol">{{ item.symbol }}</span>
                <span class="opt-type">{{ item.market || item.asset_type || item.type || '' }}</span>
              </li>
            </ul>
          </div>
          <button class="btn-primary" @click="doAnalyze" :disabled="loading">
            {{ loading ? '分析中...' : '🔍 分析' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Quick examples chips -->
    <div v-if="!query" class="quick-chips">
      <span class="chip-label">快速输入:</span>
      <button
        v-for="ex in visibleExamples" :key="ex.code"
        class="chip" @click="quickSelect(ex)">{{ ex.label }}</button>
    </div>

    <!-- F10 R35: 预设问题模板——点击后以该问题作为 prompt 附加输入 -->
    <div v-if="symbol && !loading" class="question-chips">
      <span class="chip-label">针对性分析:</span>
      <button
        v-for="tpl in QUESTION_TEMPLATES" :key="tpl.key"
        class="chip" :class="{ active: selectedQuestion === tpl.question }"
        @click="setQuestion(tpl)">{{ tpl.label }}</button>
    </div>

    <div v-if="error" class="error">
      {{ error }}
      <!-- O24 (round8 §7 §5.1K): 失败可重试——点击带退避重发同一输入 -->
      <button class="btn-retry" @click="doAnalyze" :disabled="loading">重试</button>
    </div>

    <div v-if="result" class="result" v-html="renderMarkdown(result)"></div>

    <div v-else-if="symbol && !loading" class="result-area">
      <p>已选择: <strong>{{ symbol }}</strong> ({{ currentModeLabel }})</p>
      <!-- F18 (round6 §16.6): "已选择"态增加"点击分析"引导按钮——明确下一步动作 -->
      <button class="btn-primary" @click="doAnalyze">📊 点击分析</button>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick, toRef } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useLLMStream } from '../../composables/useLLMStream'
import { useMarketSearch } from '../../composables/useMarketSearch'
import { marketApi } from '../../api'

const { start: startStream, stop: stopStream } = useLLMStream()

// R5: 输入处理——symbol 模式必须先把值写回 search.searchQuery 再触发 onSearchInput。
// 旧实现只调 onSearchInput() 不写回：onSearchInput 内部读 searchQuery.value（恒为空）
// → 永不触发搜索 → 自动补全完全不工作。
function onInput(e) {
  const v = e.target.value
  // O30: 三模式统一走 search 实例（symbol/sector/index 各自 kind）
  activeSearch.value.searchQuery.value = v
  activeSearch.value.onSearchInput()
}

const props = defineProps({
  marketTab: { type: String, default: 'A' },
  selectedSymbol: { type: String, default: null },
  // F2-7 步骤E: 外部快速分析入口（热点行「AI 分析」→ { mode, query, name }）
  externalTrigger: { type: Object, default: null },
})

const activeMode = ref('symbol')
const query = ref('')
const symbol = ref('')
// F7 R18: symbol 模式自动补全（复用 useMarketSearch：200ms debounce + include_stocks）
// F17 (round6 §16.5): 带 marketTab——A 场景只搜 A，短路后端 global 分支
// O30 (round7 §7 P30①): sector/index 模式各建一个 kind 实例——三模式复用同一套
// 下拉/键盘导航/Enter 选中（后端 /search kind 参数，sector→板块表，index→指数表）
// round9 §7 修复: market 传 toRef(props,'marketTab')（响应式）——旧实现 setup 求值
// 一次，切到港股 tab 后 marketFilter 仍为 'A' → 补全只显示 A 股。
const search = useMarketSearch({ market: toRef(props, 'marketTab') })
const sectorSearch = useMarketSearch({ market: toRef(props, 'marketTab'), kind: 'sector' })
const indexSearch = useMarketSearch({ market: toRef(props, 'marketTab'), kind: 'index' })
const activeSearch = computed(() => {
  if (activeMode.value === 'sector') return sectorSearch
  if (activeMode.value === 'index') return indexSearch
  return search
})
const loading = ref(false)
const result = ref('')
const error = ref('')
const lastAnalyzed = ref('')
// F10 R35: 预设问题模板（选中个股后针对性分析）
const selectedQuestion = ref('')
const QUESTION_TEMPLATES = [
  { key: 'tech', label: '📈 技术面分析', question: '请重点分析技术面：趋势、均线、MACD/KDJ/RSI 信号与关键支撑压力位' },
  { key: 'ops', label: '💼 操作建议', question: '请给出明确的操作建议：仓位、买卖点与止损位' },
  { key: 'news', label: '📰 资讯催化', question: '请重点分析近期资讯催化：利好利空因素与事件驱动' },
  { key: 'risk', label: '⚠️ 风险提示', question: '请重点提示风险：最大回撤、基本面风险与流动性风险' },
]

function setQuestion(tpl) {
  selectedQuestion.value = selectedQuestion.value === tpl.question ? '' : tpl.question
}

// R40: tab 切换重置——先 stopStream 中止在途请求，再清空输入/结果/错误/去重状态
function switchMode(mode) {
  if (mode === activeMode.value) return
  stopStream()
  activeMode.value = mode
  query.value = ''
  symbol.value = ''
  result.value = ''
  error.value = ''
  loading.value = false
  lastAnalyzed.value = ''  // 重置旧去重状态，避免干扰下次 selectedSymbol 触发
}

// R5: 市场切换重置——A→US 后旧市场的标的分析结果/输入不应残留（交互优化）
watch(() => props.marketTab, () => {
  stopStream()
  query.value = ''
  symbol.value = ''
  result.value = ''
  error.value = ''
  loading.value = false
  lastAnalyzed.value = ''
  if (search.searchQuery) search.searchQuery.value = ''
  search.searchResults.value = []
  search.showDropdown.value = false
})

const unsupportedSectorMarkets = ['US', 'HK']

const modes = computed(() => {
  const base = [
    { value: 'symbol', label: '个股/ETF' },
    { value: 'sector', label: '板块/概念' },
    { value: 'index', label: '指数' },
  ]
  // round10 P2-T: 美股/港股无板块数据源——板块模式禁用（避免展示 A 股板块）
  return base.map(m => ({
    ...m,
    disabled: m.value === 'sector' && unsupportedSectorMarkets.includes(props.marketTab),
  }))
})

// round10 P2-T: 切到 US/HK tab 时若停留在板块模式 → 回落 symbol（板块模式无数据源）
watch(() => props.marketTab, (mkt) => {
  if (activeMode.value === 'sector' && unsupportedSectorMarkets.includes(mkt)) {
    activeMode.value = 'symbol'
  }
})

const currentModeLabel = computed(() => {
  const m = modes.value.find(m => m.value === activeMode.value)
  return m ? m.label : '标的'
})

const placeholders = {
  // R5: 精简文案——完整示例已由下方“快速输入”chips 提供；placeholder 过长在窄屏必被截断
  symbol: '输入代码或名称，如 510050',
  sector: '输入板块代码/名称，如 BK1318',
  index: '输入指数代码，如 000001/HSI',
}

const currentPlaceholder = computed(() => placeholders[activeMode.value] || placeholders.symbol)

const EXAMPLES = {
  A: {
    symbol: [
      { code: '510050', label: '上证50ETF' },
      { code: '159915', label: '创业板ETF' },
      { code: '518880', label: '黄金ETF' },
      { code: '513100', label: '纳指ETF' },
    ],
    sector: [
      // F19-④ (round6 §16.7): 真实半导体板块代码 BK1318（旧 BK0477 已过期，
      // push2delay 板块表无此代码 → 板块分析 404）
      { code: 'BK1318', label: '半导体' },
      { code: 'BK0445', label: '人工智能' },
      { code: 'BK0891', label: '新能源车' },
    ],
    index: [
      { code: '000001', label: '上证指数' },
      { code: '399001', label: '深证成指' },
      { code: '399006', label: '创业板指' },
    ],
  },
  HK: {
    symbol: [
      { code: '00700', label: '腾讯控股' },
      { code: '09988', label: '阿里巴巴' },
      { code: '02800', label: '盈富基金' },
    ],
    sector: [],
    index: [
      { code: 'HSI', label: '恒生指数' },
      { code: 'HSCEI', label: '国企指数' },
    ],
  },
  US: {
    symbol: [
      { code: 'SPY', label: '标普500ETF' },
      { code: 'QQQ', label: '纳斯达克ETF' },
      { code: 'AAPL', label: 'Apple' },
    ],
    sector: [],
    index: [
      { code: 'SPX', label: '标普500' },
      { code: 'IXIC', label: '纳斯达克' },
    ],
  },
  global: {
    symbol: [
      { code: '000001', label: '上证指数' },
      { code: 'HSI', label: '恒生指数' },
      { code: 'SPX', label: '标普500' },
    ],
    sector: [],
    index: [
      { code: 'IXIC', label: '纳斯达克' },
      { code: 'GC=F', label: '黄金' },
    ],
  },
}

const visibleExamples = computed(() => {
  const byMarket = EXAMPLES[props.marketTab] || EXAMPLES.A
  return byMarket[activeMode.value] || []
})

// Watch selectedSymbol prop for external trigger (from watchlist)
watch(() => props.selectedSymbol, (val) => {
  if (val && val !== lastAnalyzed.value) {
    query.value = val
    if (search.searchQuery) search.searchQuery.value = val
    symbol.value = val
    nextTick(() => doAnalyze())
  }
})

// F2-7 步骤E: 外部触发（sector 模式快速入口）——activeMode + query + doAnalyze
watch(() => props.externalTrigger, (trig) => {
  if (trig && trig.query) {
    activeMode.value = (trig.mode === 'sector' || trig.mode === 'index') ? trig.mode : 'symbol'
    query.value = trig.query
    if (search.searchQuery) search.searchQuery.value = trig.query
    symbol.value = trig.query
    result.value = ''
    error.value = ''
    nextTick(() => doAnalyze())
  }
})

function quickSelect(ex) {
  query.value = ex.code
  symbol.value = ex.code
  result.value = ''
  error.value = ''
  doAnalyze()
}

// F18 (round6 §16.6): Enter 统一触发分析——symbol 模式下先处理下拉键
// （选中项写回 searchQuery），再统一 doAnalyze；sector/index 直接分析。
// O30: sector/index 模式同样支持下拉 Enter 选中（复用 activeSearch）
// 旧实现 Enter 只调 search.onSearchKeydown（选中不触发分析），键盘/鼠标不一致。
function onEnterKeydown(e) {
  activeSearch.value.onSearchKeydown(e)
  if (e.defaultPrevented) {
    // 下拉 Enter 已消费（选中项）→ 同步触发分析
    const q = activeSearch.value.searchQuery.value.trim()
    if (q) {
      nextTick(() => doAnalyze())
    }
    return
  }
  doAnalyze()
}

// F7 R18: 下拉选中 → 写入 query + 触发分析（名称→代码由 doAnalyze 内解析）
// O30: 三模式统一用 activeSearch（sector/index 下拉选中板块/指数）
// O23 (round8 §7 §5.1J): 复用 composable 的 selectSearchItem——回显「名称 (代码)」，
// 旧实现只写 item.symbol → 输入框只显示代码、doAnalyze 拿不到名称。
function pickSearchItem(item) {
  query.value = item.symbol
  activeSearch.value.selectSearchItem(item) // 写回 "名称 (代码)"
  symbol.value = item.symbol
  result.value = ''
  error.value = ''
  doAnalyze()
}

// O24 (round8 §7 §5.1K): SSE 失败分类文案——复用 llm.py 的 _last_llm_error 分级
// （[rate-limited] 429 / [timeout]），前端据此显示差异化提示而非笼统「网络错误」。
// 有错误对象时优先按 message 分类；无错误对象（SSE 空转）才判「AI 未返回内容」。
function classifyError(e, fullText) {
  const msg = ((e && e.message) || '').toString()
  if (msg.includes('429') || msg.includes('[rate-limited]')) {
    return '请求过于频繁，请稍后重试'
  }
  if (msg.includes('timeout') || msg.includes('[timeout]')) {
    return '数据源无响应，请稍后重试'
  }
  if (msg.includes('DATA_UNAVAILABLE') || msg.includes('数据源暂不可用')) {
    return '分析失败：数据源暂不可用'
  }
  if (!fullText || !fullText.trim()) return '分析失败：AI 未返回内容，请稍后重试'
  return '分析失败：' + (msg || '网络错误')
}

async function doAnalyze() {
  // F7 R18 + O30: 输入源统一为 activeSearch.searchQuery（三模式自动补全框）
  const q = activeSearch.value.searchQuery.value.trim()
  if (!q) {
    // R5: 空输入点“分析”给出明确反馈（旧实现静默 return，页面无任何动作）
    error.value = '请输入标的代码或名称'
    return
  }
  query.value = q
  loading.value = true
  error.value = ''
  result.value = ''
  lastAnalyzed.value = q

  // O23 (round8 §7 §5.1J): 混合串解析——兼容两种回显格式：
  //   「代码 名称」（acceptCompletion）→ 首个 token 为代码；
  //   「名称 (代码)」（selectSearchItem）→ 括号内为代码。
  // 旧 looksLikeCode 对整个串 test，含空格/中文的混合串解析失败。
  const firstToken = q.split(/[\s(（]/)[0] || q
  const parenMatch = q.match(/[（(]\s*([0-9A-Za-z.]+)\s*[)）]/)
  let codeToken = firstToken
  let namePart = ''
  let looksLikeCode = /^[0-9A-Za-z.]+$/.test(firstToken) && firstToken.length <= 12
  if (parenMatch && /^[0-9A-Za-z.]+$/.test(parenMatch[1]) && parenMatch[1].length <= 12) {
    // 「名称 (代码)」格式：括号内为代码，括号前为名称
    codeToken = parenMatch[1]
    namePart = q.slice(0, q.indexOf(parenMatch[0])).trim() || ''
    looksLikeCode = true
  } else if (looksLikeCode) {
    // 「代码 名称」格式：首个 token 为代码，其余为名称
    namePart = q.slice(firstToken.length).replace(/[()（）]/g, '').trim()
  }
  let reqSymbol = q
  let reqName = ''
  let assetType = props.marketTab === 'HK' ? 'HK' : (props.marketTab === 'US' ? 'US' : 'A')
  if (activeMode.value === 'symbol') {
    if (looksLikeCode) {
      reqSymbol = codeToken
      reqName = namePart
    } else {
      reqSymbol = q
      reqName = q
    }
  } else {
    reqSymbol = q
    reqName = q
  }
  // O23: symbol 显示真实代码（混合串输入时取 codeToken，供「已选择」态展示）
  symbol.value = looksLikeCode ? codeToken : q

  // F7 R19: symbol 模式名称→代码解析（命中下拉搜索结果首条则用其 symbol）
  if (activeMode.value === 'symbol' && !looksLikeCode) {
    try {
      const res = await marketApi.search(q, { include_stocks: true })
      const hits = res.data || []
      const hit = hits.find((i) => i.name === q) || hits[0]
      if (hit) {
        reqSymbol = hit.symbol || q
        reqName = hit.name || q
      }
    } catch (e) {
      // 解析失败回退：按原输入交给后端（R20 兜底）
    }
  }

  // R42: index 模式先解析中文指数名（如"沪深300"）→ 真实 symbol + 名称，避免 404
  // O23: 混合串（"上证指数 (000001)"）用 namePart/codeToken 匹配
  if (activeMode.value === 'index') {
    try {
      const meta = (await marketApi.indicesMeta()).data || []
      const hit = meta.find((i) => i.name === q)
        || meta.find((i) => i.symbol === q)
        || meta.find((i) => namePart && i.name === namePart)
        || meta.find((i) => looksLikeCode && i.symbol === codeToken)
        || meta.find((i) => (i.name || '').includes(q))
      if (hit) {
        reqSymbol = hit.symbol || q
        reqName = hit.name || q
      } else if (looksLikeCode) {
        reqSymbol = codeToken
        reqName = '' // 代码直传，后端 realtime 回填
      }
      assetType = 'index'
    } catch (e) {
      // 解析失败回退：按原输入交给后端（realtime 兜底）
    }
  }

  // F2-4: 复用已验证的 SSE 流式端点（symbol/sector/index 三模式），删除 fallback 假成功分支
  const endpoint = activeMode.value === 'sector'
    ? '/sector-analysis/stream'
    : '/symbol-analysis/stream'
  const body = activeMode.value === 'sector'
    // O23: sector 模式同样从混合串提取 code/name
    ? { sector_code: (looksLikeCode ? codeToken : q), sector_name: (namePart || q), sector_type: 'industry', market: props.marketTab }
    : { symbol: reqSymbol, name: reqName, asset_type: assetType, market: props.marketTab, question: selectedQuestion.value }

  try {
    const { fullText } = await startStream(endpoint, body, (token) => {
      result.value += token
    })
    result.value = fullText
    // F18 (round6 §16.6): SSE 空转/失败——返回空 fullText 时显示错误态，
    // 而非静默落入"已选择"分支（用户误以为已分析完成）。
    // O24 (round8 §7 §5.1K): 分类文案 + 可重试（失败态带「重试」按钮）。
    if (!fullText || !fullText.trim()) {
      error.value = classifyError(null, fullText)
    }
  } catch (e) {
    error.value = classifyError(e, result.value)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-1); color: var(--color-text-primary); }
.section-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0; }

.analysis-tabs {
  display: flex;
  gap: 0;
  margin-bottom: var(--space-3);
  border-bottom: 2px solid var(--color-border-light);
}
.analysis-tab {
  padding: var(--space-2) var(--space-4);
  font: var(--text-body-sm);
  color: var(--color-text-secondary);
  border: none;
  background: none;
  cursor: pointer;
  transition: var(--transition-fast);
  position: relative;
}
.analysis-tab:hover { color: var(--color-text-primary); background: var(--color-bg-secondary); }
.analysis-tab.disabled {
  color: var(--color-text-disabled, var(--color-text-tertiary, #aaa));
  cursor: not-allowed;
  opacity: 0.55;
}
.analysis-tab.disabled:hover { color: var(--color-text-disabled, #aaa); background: none; }
.analysis-tab.active {
  color: var(--color-brand-600);
  font-weight: var(--font-weight-semibold);
}
.analysis-tab.active::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--color-brand-500);
}

.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); }
.card-body { padding: var(--space-5); }
.input-row { display: flex; gap: var(--space-3); }
.search-wrap { position: relative; flex: 1; }
.search-dropdown {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 20;
  list-style: none; margin: 0; padding: var(--space-1) 0;
  background: var(--color-surface, #fff); border: 1px solid var(--color-border, #ddd);
  border-radius: var(--radius-md, 8px); box-shadow: 0 4px 16px rgba(0,0,0,.12);
  max-height: 260px; overflow-y: auto;
}
.search-option {
  display: flex; gap: var(--space-2); align-items: center;
  padding: var(--space-2) var(--space-3); cursor: pointer;
  font: var(--text-body-sm); color: var(--color-text-primary);
}
.search-option:hover, .search-option.active { background: var(--color-bg-secondary, #f5f5f5); }
.opt-name { flex: 1; }
.opt-symbol { font-family: var(--font-mono, monospace); color: var(--color-text-secondary); font-size: var(--text-xs); }
.opt-type { color: var(--color-text-muted, #999); font-size: var(--text-xs); }
.text-input {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-base);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-lg);
  background: var(--color-surface-primary);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color var(--transition-fast);
}
.text-input:focus { border-color: var(--color-brand-500); box-shadow: 0 0 0 3px var(--color-brand-100); }
.text-input::placeholder { color: var(--color-text-tertiary); }
.btn-primary {
  padding: var(--space-2) var(--space-5);
  font: var(--text-body);
  color: white;
  background: var(--color-brand-600);
  border: none;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: background var(--transition-fast);
  white-space: nowrap;
}
.btn-primary:hover { background: var(--color-brand-700); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.error { margin: var(--space-3); padding: var(--space-2) var(--space-3); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.result { margin-top: var(--space-4); line-height: 1.8; }
.quick-chips { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-3); padding: 0 var(--space-1); }
.question-chips { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-2); padding: 0 var(--space-1); }
.question-chips .chip.active { background: var(--color-brand-600, #2563eb); color: #fff; border-color: var(--color-brand-600, #2563eb); }
.chip-label { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.chip { padding: var(--space-1) var(--space-3); font-size: var(--font-size-sm); font-family: var(--font-family-mono); font-weight: var(--font-weight-medium); color: var(--color-brand-600); background: var(--color-bg-brand-subtle); border: 1px solid var(--color-brand-200); border-radius: var(--radius-full); cursor: pointer; transition: var(--transition-fast); }
.chip:hover { background: var(--color-brand-100); border-color: var(--color-brand-400); }
.result-area { margin-top: var(--space-4); padding: var(--space-4); text-align: center; color: var(--color-text-secondary); }
</style>
