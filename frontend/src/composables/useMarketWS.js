import { ref, onUnmounted } from 'vue'
import logger from '../utils/logger'

const WS_BASE = (() => {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const host = location.host
  return `${proto}://${host}/api/v1/ws`
})()

export function useMarketWS(handler) {
  const connected = ref(false)
  let ws = null
  let reconnectTimer = null
  let heartbeatTimer = null
  let reconnectDelay = 1000
  let stopped = false
  let msgHandler = typeof handler === 'function' ? handler : null

  function connect() {
    if (stopped) return
    try {
      ws = new WebSocket(`${WS_BASE}/portfolio`)
    } catch (e) {
      logger.error('Market WS 连接创建失败，准备重连:', e)
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000
      heartbeatTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('ping')
        }
      }, 30000)
    }

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'pong') return
        if (msgHandler) msgHandler(msg)
      } catch (e) {
        logger.error('Market WS 消息解析失败:', e)
      }
    }

    ws.onclose = () => {
      connected.value = false
      clearInterval(heartbeatTimer)
      scheduleReconnect()
    }

    ws.onerror = () => {
      logger.error('Market WS 发生错误')
      if (ws) ws.close()
    }
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return
    const jitter = Math.floor(Math.random() * 200)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      reconnectDelay = Math.min(reconnectDelay * 2, 8000)
      connect()
    }, reconnectDelay + jitter)
  }

  function disconnect() {
    stopped = true
    clearInterval(heartbeatTimer)
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (ws) ws.close()
  }

  function onMarketData(fn) {
    msgHandler = fn
  }

  onUnmounted(disconnect)

  return { connected, connect, disconnect, onMarketData, stop: disconnect }
}
