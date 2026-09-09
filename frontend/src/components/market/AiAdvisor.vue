<template>
  <section class="section-card">
    <div class="section-header">
      <h2 class="section-title">💬 AI 投资顾问</h2>
      <p class="section-desc">向 AI 提问获取投资建议，结合实时行情与组合上下文，支持多轮追问</p>
    </div>

    <div class="card">
      <div class="card-body">
        <div class="chat-scroll" ref="chatScrollRef">
          <!-- round53 §9: 消息气泡列表（用户右灰底 / 助手左 brand 左条） -->
          <div v-for="(m, i) in messages" :key="i" class="chat-row" :class="m.role">
            <div class="chat-bubble" :class="m.role" v-html="renderMarkdown(m.content)"></div>
          </div>
          <!-- 流式中的助手消息（跟随 token 追加） -->
          <div v-if="loading && streamingText" class="chat-row assistant">
            <div class="chat-bubble assistant streaming" v-html="renderMarkdown(streamingText)"></div>
          </div>
        </div>

        <div class="input-row">
          <input
            type="text"
            v-model="query"
            placeholder="输入您的投资问题，如：当前市场风格偏向成长还是价值？是否该调仓？"
            class="text-input"
            :disabled="loading"
            @keydown.enter="send"
          />
          <button class="btn-primary" @click="send" :disabled="loading || !query.trim()">
            {{ loading ? '思考中...' : (sessionId ? '追加提问' : '🤖 发送提问') }}
          </button>
          <button v-if="sessionId" class="btn-new-chat" @click="resetChat" :disabled="loading" title="开始新会话">
            新会话
          </button>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
        <div v-if="progress && !loading" class="stream-progress">
          <div class="progress-bar"><div class="progress-fill"></div></div>
          <span class="progress-text">{{ progress.message }}</span>
        </div>
        <div v-if="!messages.length && !loading && !error && !progress" class="hint">
          💡 输入上方问题，AI 将结合实时行情与您的组合给出建议；回答后可继续追问
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { renderMarkdown } from '../../utils/markdown'
import { useLLMStream } from '../../composables/useLLMStream'

const props = defineProps({ marketTab: { type: String, default: 'A' } })

const query = ref('')
const messages = ref([])          // [{role: 'user'|'assistant', content}]
const streamingText = ref('')
const loading = ref(false)
const error = ref('')
const chatScrollRef = ref(null)
const { start: startStream, stop: stopStream, progress, sessionId } = useLLMStream()

function _scrollBottom() {
  nextTick(() => {
    if (chatScrollRef.value) chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
  })
}

async function send() {
  const q = query.value.trim()
  if (!q || loading.value) return
  loading.value = true
  error.value = ''
  streamingText.value = ''
  messages.value.push({ role: 'user', content: q })
  query.value = ''
  _scrollBottom()
  try {
    // round53 §9: session_id 透传——首轮 ''（后端开新会话），追问带上轮 id
    const body = { query: q, market: props.marketTab }
    if (sessionId.value) body.session_id = sessionId.value
    await startStream('/llm-advice/stream', body, (token) => {
      streamingText.value += token
      _scrollBottom()
    })
    // done 后固化助手消息（metadata.session_id 在 onDone 由 composable 保存）
    if (streamingText.value) {
      messages.value.push({ role: 'assistant', content: streamingText.value })
      streamingText.value = ''
    }
  } catch (e) {
    error.value = '提问失败：' + (e?.message || '网络错误')
  } finally {
    loading.value = false
    _scrollBottom()
  }
}

function resetChat() {
  stopStream()
  messages.value = []
  streamingText.value = ''
  sessionId.value = ''
  error.value = ''
}
// R5: 市场切换重置——A→US 后旧市场的投顾回答/输入不应残留（交互优化）
// O29 (round7 §7 P29): 补 query 清空。
// round53 §9: 市场切换同时开新会话（跨市场上下文不复用）。
watch(() => props.marketTab, () => {
  resetChat()
  query.value = ''
})

</script>

<style scoped>
.section-card { margin-bottom: var(--space-4); }
.section-header { margin-bottom: var(--space-3); }
.section-title { font-size: var(--font-size-xl); font-weight: var(--font-weight-semibold); margin: 0 0 var(--space-1); color: var(--color-text-primary); }
.section-desc { font-size: var(--font-size-sm); color: var(--color-text-secondary); margin: 0; }
.card { background: var(--color-surface-primary); border: 1px solid var(--color-border-light); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); }
.card-body { padding: var(--space-5); }
.input-row { display: flex; gap: var(--space-3); }
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
.error { margin-top: var(--space-3); padding: var(--space-2) var(--space-3); color: var(--color-danger-700); background: var(--color-bg-danger-subtle); border-radius: var(--radius-md); font-size: var(--font-size-sm); }
.stream-progress { display: flex; align-items: center; gap: var(--space-3); margin-top: var(--space-3); }
.progress-bar { flex: 1; height: 4px; background: var(--color-border-light); border-radius: 999px; overflow: hidden; }
.progress-fill { width: 40%; height: 100%; background: var(--color-primary); border-radius: 999px; margin-left: -40%; animation: progress-indeterminate 1.1s ease-in-out infinite; }
.progress-text { font-size: var(--font-size-sm); color: var(--color-text-secondary); white-space: nowrap; }
@keyframes progress-indeterminate { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
.response { margin-top: var(--space-4); line-height: 1.8; }
.hint { margin-top: var(--space-4); padding: var(--space-4); text-align: center; color: var(--color-text-secondary); font-size: var(--font-size-sm); }

/* ── round53 §9: 多轮对话气泡 ── */
.chat-scroll {
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding-right: var(--space-1);
}
.chat-row { display: flex; }
.chat-row.user { justify-content: flex-end; }
.chat-row.assistant { justify-content: flex-start; }
.chat-bubble {
  max-width: 85%;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  font-size: var(--font-size-sm);
  line-height: 1.75;
  word-break: break-word;
}
.chat-bubble.user {
  background: var(--color-surface-tertiary);
  color: var(--color-text-primary);
  border-bottom-right-radius: var(--radius-sm);
}
.chat-bubble.assistant {
  background: var(--color-surface-primary);
  border: 1px solid var(--color-border-light);
  border-left: 3px solid var(--color-brand-500);
  color: var(--color-text-primary);
  border-bottom-left-radius: var(--radius-sm);
}
.chat-bubble.streaming { opacity: 0.85; }
.btn-new-chat {
  padding: var(--space-2) var(--space-3);
  font: var(--text-body);
  color: var(--color-text-secondary);
  background: var(--color-surface-tertiary);
  border: 1px solid var(--color-border-medium);
  border-radius: var(--radius-lg);
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--transition-fast);
}
.btn-new-chat:hover { background: var(--color-surface-hover); }
.btn-new-chat:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
