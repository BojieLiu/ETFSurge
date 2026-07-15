import { defineStore } from 'pinia'
import { ref } from 'vue'
import { marketApi } from '../api'
import logger from '../utils/logger'

const WS_BASE = (() => {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/v1/ws`
})()

export const useMarketStore = defineStore('market', () => {
  const realtimeData = ref([])
  const indicators = ref(null)
  const signal = ref(null)
  const history = ref([])
  const wsConnected = ref(false)
  const wsData = ref(null)

  let ws = null
  let reconnectTimer = null
  let heartbeatTimer = null
  let reconnectDelay = 1000
  let stopped = false
  let onMessageCallback = null

  function connectWS(onMsg) {
    if (typeof onMsg === 'function') {
      onMessageCallback = onMsg
    }
    stopped = false
    doConnect()
  }

  function doConnect() {
    if (stopped) return
    try {
      ws = new WebSocket(`${WS_BASE}/portfolio`)
    } catch (e) {
      logger.error('Market WS 连接创建失败，准备重连:', e)
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      wsConnected.value = true
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
        wsData.value = msg
        if (msg.symbol) {
          const idx = realtimeData.value.findIndex(item => item.symbol === msg.symbol)
          if (idx >= 0) {
            realtimeData.value[idx] = { ...realtimeData.value[idx], price: msg.price, change_pct: msg.change_pct }
            realtimeData.value = [...realtimeData.value]
          }
        }
        if (onMessageCallback) onMessageCallback(msg)
      } catch (e) {
        logger.error('Market WS 消息解析失败:', e)
      }
    }

    ws.onclose = () => {
      wsConnected.value = false
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
      doConnect()
    }, reconnectDelay + jitter)
  }

  function disconnectWS() {
    stopped = true
    wsConnected.value = false
    clearInterval(heartbeatTimer)
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (ws) ws.close()
    ws = null
    onMessageCallback = null
  }

  async function fetchRealtime() {
    const res = await marketApi.realtimePortfolio()
    realtimeData.value = res.data
  }

  async function fetchIndicators(symbol, assetType = 'A') {
    const res = await marketApi.indicators(symbol, assetType)
    indicators.value = res.data
  }

  async function fetchSignal(symbol, assetType = 'A') {
    const res = await marketApi.signal(symbol, assetType)
    signal.value = res.data
  }

  async function fetchHistory(symbol, assetType = 'A', period = 'daily') {
    const res = await marketApi.history(symbol, assetType, period)
    history.value = res.data
  }

  function getQuote(symbol) {
    return realtimeData.value.find(item => item.symbol === symbol)
  }

  return { realtimeData, indicators, signal, history, wsConnected, wsData, connectWS, disconnectWS, fetchRealtime, fetchIndicators, fetchSignal, fetchHistory, getQuote }
})
