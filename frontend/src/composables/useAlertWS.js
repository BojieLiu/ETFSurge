/**
 * useAlertWS - WebSocket 告警通道前端接入
 *
 * 监听 /ws/alerts 通道，接收后端推送的告警事件。
 * 支持：地缘风险预警 / 宏观数据异动 / 黑天鹅标记 / 因子拥挤度告警
 */
import { ref, onUnmounted } from 'vue'
import logger from '../utils/logger'

export function useAlertWS() {
  const ws = ref(null)
  const connected = ref(false)
  const alerts = ref([])
  const lastAlert = ref(null)

  function connect() {
    if (ws.value && (ws.value.readyState === WebSocket.OPEN || ws.value.readyState === WebSocket.CONNECTING)) {
      return
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/ws/alerts`

    try {
      ws.value = new WebSocket(url)

      ws.value.onopen = () => {
        connected.value = true
        logger.info('[AlertWS] 连接到告警通道')
      }

      ws.value.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          alerts.value.unshift({
            ...data,
            timestamp: data.timestamp || Date.now(),
          })
          lastAlert.value = data

          // 只保留最近 50 条
          if (alerts.value.length > 50) {
            alerts.value = alerts.value.slice(0, 50)
          }
        } catch (e) {
          logger.warn('[AlertWS] 解析消息失败:', e)
        }
      }

      ws.value.onclose = () => {
        connected.value = false
        logger.info('[AlertWS] 连接断开')
        // 自动重连 (30s)
        setTimeout(() => connect(), 30000)
      }

      ws.value.onerror = () => {
        connected.value = false
        ws.value?.close()
      }
    } catch (e) {
      logger.error('[AlertWS] 连接失败:', e)
    }
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
    connected.value = false
  }

  function clearAlerts() {
    alerts.value = []
    lastAlert.value = null
  }

  return { connected, alerts, lastAlert, connect, disconnect, clearAlerts }
}
