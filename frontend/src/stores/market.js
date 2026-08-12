import { defineStore } from 'pinia'
import { ref } from 'vue'
import { marketApi } from '../api'
import { usePortfolioStore } from './portfolio'
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
  // round19 P6-② (2026-08-12): 状态机细分——'idle'|'connecting'|'connected'|
  // 'reconnecting'|'stopped'，导航栏不再把「主动断开（按需连接）」混同为「离线」。
  const wsStatus = ref('idle')

  // Watchlist
  const watchlist = ref([])
  const watchlistLoading = ref(false)
  const watchlistTotal = ref(0)

  let ws = null
  let reconnectTimer = null
  let heartbeatTimer = null
  let reconnectDelay = 1000
  let stopped = false
  // round19 P6-①: 连接生命周期提升至 App.vue 全站常驻后，Dashboard 等页面仍要
  // 消费行情消息——回调由单例改为多注册者数组（connect 只建连，页面各自注册/注销）。
  const onMessageCallbacks = []
  // round19 P2-②: portfolio_changed 广播消费防抖（批量操作触发多次广播 → 1s 合并刷新）
  let portfolioChangedTimer = null

  function connectWS(onMsg) {
    if (typeof onMsg === 'function') {
      onMessageCallbacks.push(onMsg)
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      return // 幂等：已存在可用连接时不重复建连（全站常驻后重复调用场景）
    }
    stopped = false
    doConnect()
  }

  function onWSMessage(cb) {
    if (typeof cb === 'function' && !onMessageCallbacks.includes(cb)) {
      onMessageCallbacks.push(cb)
    }
  }

  function offWSMessage(cb) {
    const i = onMessageCallbacks.indexOf(cb)
    if (i >= 0) onMessageCallbacks.splice(i, 1)
  }

  function doConnect() {
    if (stopped) return
    wsStatus.value = 'connecting'
    try {
      ws = new WebSocket(`${WS_BASE}/portfolio`)
    } catch (e) {
      logger.error('Market WS 连接创建失败，准备重连:', e)
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      wsConnected.value = true
      wsStatus.value = 'connected'
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
        // P1-1 (round16 3.9 B4): 行情 WS 推送消费——market_refresh 广播
        // {type:'realtime', data:[{symbol,price,change_pct},...]}，旧实现只处理
        // 顶层 msg.symbol → 推送不消费、行情更新受 TTL 缓存节流。
        if (msg.type === 'realtime' && Array.isArray(msg.data)) {
          for (const quote of msg.data) {
            if (!quote || !quote.symbol) continue
            const idx = realtimeData.value.findIndex(item => item.symbol === quote.symbol)
            if (idx >= 0) {
              realtimeData.value[idx] = {
                ...realtimeData.value[idx],
                price: quote.price ?? realtimeData.value[idx].price,
                change_pct: quote.change_pct ?? realtimeData.value[idx].change_pct,
              }
              realtimeData.value = [...realtimeData.value]
            }
          }
        }
        // round19 P2-②: 组合结构变更广播——任一标签页/页面增删改标的，
        // 其它已挂载页面与多标签页自动刷新（防抖 1s 合并批量操作）。
        if (msg.type === 'portfolio_changed') {
          if (portfolioChangedTimer) clearTimeout(portfolioChangedTimer)
          portfolioChangedTimer = setTimeout(() => {
            usePortfolioStore().fetchEtfs('on_exchange').catch(() => {})
            usePortfolioStore().fetchEtfs('off_exchange').catch(() => {})
          }, 1000)
        }
        if (msg.symbol) {
          const idx = realtimeData.value.findIndex(item => item.symbol === msg.symbol)
          if (idx >= 0) {
            realtimeData.value[idx] = { ...realtimeData.value[idx], price: msg.price, change_pct: msg.change_pct }
            realtimeData.value = [...realtimeData.value]
          }
        }
        for (const cb of onMessageCallbacks) {
          try { cb(msg) } catch (e) { logger.error('Market WS 消费回调失败:', e) }
        }
      } catch (e) {
        logger.error('Market WS 消息解析失败:', e)
      }
    }

    ws.onclose = () => {
      wsConnected.value = false
      // round19 P6-②: 主动断开（disconnectWS）触发的 onclose 不显示「重连中」
      wsStatus.value = stopped ? 'stopped' : 'reconnecting'
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
    wsStatus.value = 'stopped'
    clearInterval(heartbeatTimer)
    if (portfolioChangedTimer) {
      clearTimeout(portfolioChangedTimer)
      portfolioChangedTimer = null
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
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

  // Watchlist actions
  async function fetchWatchlist(limit = 100, offset = 0) {
    watchlistLoading.value = true
    try {
      const res = await marketApi.getWatchlist({ limit, offset })
      watchlist.value = res.data.items
      watchlistTotal.value = res.data.total
    } catch (e) {
      logger.error('获取自选列表失败:', e)
      throw e
    } finally {
      watchlistLoading.value = false
    }
  }

  async function addWatchlist(symbol, assetType = 'A', notes = '', name = '') {
    // R28: 携带前端搜索到的真实名称——后端 realtime 失败时用 name 入库（不 422）
    const res = await marketApi.addWatchlist({ symbol, asset_type: assetType, notes, name })
    const added = res.data
    // R5: 乐观插入——POST 响应已带 realtime（后端优化），立即显示价格，不等慢速全量 GET
    if (added?.symbol) {
      watchlist.value = [{ ...added, realtime: added.realtime || null }, ...watchlist.value]
      watchlistTotal.value += 1
    }
    // 后台全量刷新兜底（GET 已并行化，不阻塞 UI）
    fetchWatchlist().catch(() => {})
    return added
  }

  async function updateWatchlist(id, data) {
    const res = await marketApi.updateWatchlist(id, data)
    await fetchWatchlist()
    return res.data
  }

  async function removeWatchlist(id) {
    await marketApi.removeWatchlist(id)
    await fetchWatchlist()
  }

  async function batchRemoveWatchlist(ids) {
    await marketApi.batchRemoveWatchlist(ids)
    await fetchWatchlist()
  }

  function getQuote(symbol) {
    return realtimeData.value.find(item => item.symbol === symbol)
  }

  return { 
    realtimeData, indicators, signal, history, wsConnected, wsStatus, wsData, 
    connectWS, disconnectWS, onWSMessage, offWSMessage,
    fetchRealtime, fetchIndicators, fetchSignal, fetchHistory, getQuote,
    // Watchlist
    watchlist, watchlistLoading, watchlistTotal,
    fetchWatchlist, addWatchlist, updateWatchlist, removeWatchlist, batchRemoveWatchlist,
  }
})
