import { onUnmounted } from 'vue'
import { useTaskStore } from '../stores/task'
import logger from '../utils/logger'
import { WS_BASE } from '../utils/wsBase' // round35 FE3: 单点构造

// 节流：progress 更新每秒最多处理一次，减少主线程抖动
const PROGRESS_THROTTLE_MS = 1000
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 15000
// round35 FE3 (R126-2): 补齐心跳——market/news 均有 30s ping，task 缺失；
// 后端 _ws_loop 对 ping/heartbeat 统一回 pong。
const HEARTBEAT_INTERVAL_MS = 30000

/**
 * useTaskWS (P2-4) — 全局 task-notification WebSocket（对齐 useNewsWS 模式）。
 *
 * 单条持久连接驱动导航栏任务指示器；后端广播
 * { type: 'task_update', task_id, status, progress }。
 *
 * 从 App.vue 内联逻辑抽取：连接/回填/节流/自动建任务/record_id 回填/重连
 * （指数退避 + jitter）/unmount 关闭守卫，全部收敛于此。
 * 行为对齐点（与原实现一致）：
 * - 重连时 onopen 回填 fetchAndMergeTasks（断线期间新建任务不丢）
 * - Z27: WS 消息早于 addTask 时自动建任务，task_type 决定类型与 label
 * - completed 且无 record_id/design_id 时 fallback GET /tasks/{id} 回填
 */
export function useTaskWS() {
  const taskStore = useTaskStore()
  let ws = null
  let reconnectTimer = null
  let reconnectDelay = RECONNECT_BASE_MS
  let heartbeatTimer = null // round35 FE3: 30s 心跳（R126-2）
  let stopped = false
  let closedByUs = false
  let lastProgressTime = 0

  function connect() {
    if (stopped || (ws && ws.readyState <= 1)) return
    let url = `${WS_BASE}/task-notifications`
    try {
      ws = new WebSocket(url)
    } catch (e) {
      logger.error('[taskWS] 连接创建失败，准备重连', e)
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      reconnectDelay = RECONNECT_BASE_MS
      // round35 FE3 (R126-2): 30s 心跳——与 market/news WS 对齐，
      // 后端 _ws_loop 对 ping/heartbeat 回 {type:'pong'}。
      if (heartbeatTimer) clearInterval(heartbeatTimer)
      heartbeatTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, HEARTBEAT_INTERVAL_MS)
      // Backfill: on (re)connect, fetch any tasks created while disconnected
      taskStore.fetchAndMergeTasks()
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'pong') return
        if (msg.type !== 'task_update') return
        const taskId = msg.task_id

        // 本地无该任务时自动创建（避免 WS 消息早于 addTask 调用）
        // Z27: 用 task_type 初始化任务类型与 label（否则 check 任务会被误建为 design）
        if (!taskStore.getTask(taskId)) {
          const type = msg.task_type || 'design'
          const label = type === 'check' ? '策略检查与分析'
            : type === 'report' ? '市场研判报告' : '智能组合设计'
          taskStore.addTask(taskId, label, type)
        }

        // 节流：仅 progress 变化时限制频率
        const now = Date.now()
        if (msg.status === 'running' && now - lastProgressTime < PROGRESS_THROTTLE_MS) {
          // 跳过这次 progress 更新，但仍处理非 progress 字段
          return
        }
        lastProgressTime = now

        const patch = {
          status: msg.status,
          progress: typeof msg.progress === 'number' ? msg.progress : 0,
        }
        taskStore.updateTask(taskId, patch)
        // Backend _notify carries design_id on completed — fetch it directly.
        // Z27: 同时处理 record_id（check 任务无 design_id，只有 record_id）
        if (msg.record_id || msg.design_id) {
          taskStore.updateTask(taskId, {
            recordId: msg.record_id || msg.design_id,
            ...(msg.design_id ? { designId: msg.design_id } : {}),
          })
        } else if (msg.status === 'completed' || msg.status === 'completed_with_errors') {
          // fallback
          import('../api').then(({ portfolioApi }) => {
            portfolioApi.getTask(taskId).then((res) => {
              const did = res?.data?.result?.design_id
              if (did) taskStore.updateTask(taskId, { designId: did })
            }).catch(() => {})
          })
        }
      } catch (e) {
        // ignore malformed messages
      }
    }

    ws.onclose = () => {
      if (heartbeatTimer) clearInterval(heartbeatTimer)
      heartbeatTimer = null
      ws = null
      if (!closedByUs) scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose will follow; reconnect handled there
    }
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return
    // 指数退避 + jitter（对齐 useNewsWS）
    const delay = reconnectDelay + Math.random() * 500
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS)
      connect()
    }, delay)
  }

  function close() {
    stopped = true
    closedByUs = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = null
    if (heartbeatTimer) clearInterval(heartbeatTimer)
    heartbeatTimer = null
    if (ws) ws.close()
    ws = null
  }

  onUnmounted(close)

  return { connect, close }
}
