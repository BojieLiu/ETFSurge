<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">📊 市场综合研判</h2>
      <p class="section-desc">基于实时行情与宏观数据的 AI 市场环境分析</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="action-area">
          <button class="btn-report" @click="generate" :disabled="loading">
            <span v-if="!loading" class="btn-icon">🤖</span>
            <span v-else class="btn-spinner"></span>
            <span>{{ loading ? 'AI 分析中...' : (report ? '重新生成研判' : `生成${marketLabel}研判`) }}</span>
          </button>
          <p v-if="!loading && !report && !error" class="action-hint">点击按钮，AI 将综合分析当前市场环境生成报告</p>
        </div>

        <div v-if="loading" class="loading-bar">
          <div class="loading-bar-inner"></div>
        </div>

        <div v-if="error" class="error">{{ error }}</div>

        <div v-if="report" class="report" v-html="renderMarkdown(report)"></div>
        <div v-if="modelLine && !loading" class="model-line">{{ modelLine }}</div>

        <div v-if="report && !loading" class="followup">
          <div v-for="(m, i) in followMessages" :key="i" class="chat-row" :class="m.role">
            <div class="chat-bubble" :class="m.role" v-html="renderMarkdown(m.content)"></div>
          </div>
          <div v-if="followStreaming" class="chat-row assistant">
            <div class="chat-bubble assistant streaming" v-html="renderMarkdown(followStreaming)"></div>
          </div>
          <div class="input-row">
            <input v-model="followQuery" placeholder="就本报告追问，如：为什么判震荡？" class="text-input"
              :disabled="followLoading" @keydown.enter="followUp" />
            <button class="btn-report btn-follow" @click="followUp" :disabled="followLoading || !followQuery.trim()">
              {{ followLoading ? '思考中...' : '追问' }}
            </button>
            <button class="btn-new-chat" @click="refreshReport" :disabled="loading || followLoading" title="基于最新数据重判">
              重判
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useLLMStream } from '../../composables/useLLMStream'

const props = defineProps({ marketTab: { type: String, default: 'A' } })

const report = ref('')
const loading = ref(false)
const error = ref('')

const marketLabels = { A: 'A股', HK: '港股', US: '美股' }
const marketLabel = computed(() => marketLabels[props.marketTab] || props.marketTab || '市场')

const { start: startStream, stop: stopStream, sessionId, metadata } = useLLMStream()
// 模型归因：done.metadata.model（后端 done.usage.model 透传），缺失回退未知
const modelLine = computed(() => {
  const m = metadata?.value // R187 同型加固（UnifiedAnalysis/MarketReport/AiAdvisor 三处同模式）
  if (!m || !m.model) return ''
  return `模型 · ${m.model}` + (m.cached ? '（缓存）' : '')
})

const followQuery = ref('')
const followMessages = ref([])
const followStreaming = ref('')
const followLoading = ref(false)

// R4-28: 序号守卫——快速切换 tab 时丢弃过期市场流的 token/状态，
// 避免旧流回调覆盖新市场报告或错乱 loading 状态
let genSeq = 0

async function generate() {
  const seq = ++genSeq
  loading.value = true
  report.value = ''
  error.value = ''
  followMessages.value = []
  followStreaming.value = ''
  sessionId.value = ''
  try {
    // Z31: 发送 market 参数，后端按 marketTab 采集对应市场数据
    await startStream('/llm-report/stream', { symbols: null, market: props.marketTab }, (token) => {
      if (seq !== genSeq) return // 过期市场流 token 丢弃
      report.value += token
    })
  } catch (e) {
    if (e?.name === 'AbortError') return
    if (seq !== genSeq) return
    error.value = '生成失败：' + (e?.message || '网络错误')
  } finally {
    if (seq === genSeq) loading.value = false
  }
}

async function followUp() {
  const q = followQuery.value.trim()
  if (!q || followLoading.value || !report.value) return
  followLoading.value = true
  error.value = ''
  followStreaming.value = ''
  followMessages.value.push({ role: 'user', content: q })
  followQuery.value = ''
  try {
    const body = { symbols: null, market: props.marketTab, query: q }
    if (sessionId.value) body.session_id = sessionId.value
    let acc = ''
    await startStream('/llm-report/stream', body, (token) => { acc += token; followStreaming.value = acc })
    if (acc) followMessages.value.push({ role: 'assistant', content: acc })
    followStreaming.value = ''
  } catch (e) {
    if (e?.name !== 'AbortError') error.value = '追问失败：' + (e?.message || '网络错误')
  } finally {
    followLoading.value = false
  }
}

function refreshReport() {
  sessionId.value = ''
  generate()
}

// R5 交互优化：切换市场 tab → 只取消进行中的旧流、清空旧报告（避免残留旧市场内容），
// **不自动触发 LLM 研判**——LLM 生成耗时且消耗配额，由用户点击按钮主动生成。
watch(() => props.marketTab, () => {
  stopStream()
  genSeq++ // 使旧 generate 的后续回调失效
  report.value = ''
  error.value = ''
  followMessages.value = []
  followStreaming.value = ''
  followQuery.value = ''
  sessionId.value = ''
})
</script>

<style scoped>
/* 美化轮（2026-09-06）: section-card 圆角卡 + 品牌左边条；title 加大 + 副标；card 沉底嵌入 */
.section-card {
  margin-bottom: var(--space-4);
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-left: 3px solid var(--color-brand-500);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.section-header {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  background: var(--color-surface-secondary);
  border-bottom: 1px solid var(--color-border-light);
  margin-bottom: 0;
}
.section-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  margin: 0;
  color: var(--color-text-primary);
  display: flex; align-items: center; gap: var(--space-2);
}
.section-title::before {
  content: '';
  width: 4px; height: 18px;
  background: var(--color-brand-500);
  border-radius: var(--radius-full);
}
.section-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0; }
.card {
  background: transparent;
  border: none;
  box-shadow: none;
  border-radius: 0;
}
.card-body { padding: var(--space-5); }

.action-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-6) 0;
}

.btn-report {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-8);
  font: var(--text-h4);
  color: white;
  background: linear-gradient(135deg, var(--color-brand-600), var(--color-brand-700));
  border: none;
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.btn-report:hover {
  background: linear-gradient(135deg, var(--color-brand-700), var(--color-brand-800));
  box-shadow: 0 4px 16px rgba(0,0,0,0.2);
  transform: translateY(-1px);
}

.btn-report:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.btn-icon { font-size: var(--font-size-xl); line-height: 1; }

.btn-spinner {
  width: 20px;
  height: 20px;
  border: 3px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.action-hint {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  text-align: center;
  background: var(--color-surface-secondary);
  border: 1px dashed var(--color-border-medium);
  border-radius: var(--radius-md);
}

.loading-bar {
  height: 3px;
  background: var(--color-surface-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
  margin-bottom: var(--space-4);
}

.loading-bar-inner {
  height: 100%;
  width: 30%;
  background: var(--color-brand-500);
  border-radius: var(--radius-full);
  animation: loadingSlide 1.5s ease-in-out infinite;
}

@keyframes loadingSlide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.error { margin-top: var(--space-3); padding: var(--space-2) var(--space-3); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.report { margin-top: var(--space-4); line-height: 1.8; }
.followup { margin-top: var(--space-4); border-top: 1px dashed var(--color-border-medium); padding-top: var(--space-4); }
.chat-row { display: flex; margin-bottom: var(--space-3); }
.chat-row.user { justify-content: flex-end; }
.chat-bubble { max-width: 90%; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); font-size: var(--font-size-sm); line-height: 1.7; }
.chat-bubble.user { background: var(--color-surface-tertiary); }
.chat-bubble.assistant { background: var(--color-surface-secondary); border-left: 3px solid var(--color-brand-500); }
.input-row { display: flex; gap: var(--space-2); margin-top: var(--space-3); }
.text-input { flex: 1; padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border-medium); border-radius: var(--radius-md); background: var(--color-surface-primary); color: var(--color-text-primary); }
.btn-follow { padding: var(--space-2) var(--space-5); }
.btn-new-chat { padding: var(--space-2) var(--space-3); border: 1px solid var(--color-border-medium); border-radius: var(--radius-md); background: transparent; color: var(--color-text-secondary); cursor: pointer; }
.model-line { margin-top: var(--space-2); font-size: var(--font-size-xs); color: var(--color-text-tertiary); text-align: right; }
</style>
