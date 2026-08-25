import { defineStore } from 'pinia'
import { ref } from 'vue'
import { marketApi } from '../api'
import { usePortfolioStore } from './portfolio'
import logger from '../utils/logger'
import { WS_BASE } from '../utils/wsBase' // round35 FE3: 单点构造
import { createSingleFlight } from '../utils/singleFlight' // Round34 B4/R110

export const useMarketStore = defineStore('market', () => {
  const realtimeData = ref([])
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

  // Round34 B4 / R119: 批量行情合并刷新——N 条快速 symbol 消息在同一微任务内
  // 只做一次 map+替换（旧实现每条消息全量替换数组 → 50 条批量推送产生 50 次
  // 响应式更新，可触发 >16ms 长任务）。验收：50 条 batch 推送无 >16ms 长任务。
  let _pendingQuotes = null // Map<symbol, {price, change_pct}>
  let _quoteFlushScheduled = false

  function queueQuoteUpdate(msg) {
    if (!_pendingQuotes) _pendingQuotes = new Map()
    _pendingQuotes.set(msg.symbol, { price: msg.price, change_pct: msg.change_pct })
    if (_quoteFlushScheduled) return
    _quoteFlushScheduled = true
    Promise.resolve().then(() => {
      _quoteFlushScheduled = false
      const updates = _pendingQuotes
      _pendingQuotes = null
      if (!updates || !updates.size || !realtimeData.value.length) return
      let changed = false
      const next = realtimeData.value.map((item) => {
        const u = updates.get(item.symbol)
        if (!u) return item
        changed = true
        return { ...item, price: u.price, change_pct: u.change_pct }
      })
      if (changed) realtimeData.value = next // 循环外一次性赋值（R119 核心）
    })
  }

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
        // round35 §12.7-B 第一步: 删除 {type:'realtime'} 死分支——后端定时行情推送
        // 链路已删（调度器决策 B），该格式一个月无生产消息；行情更新走 REST TTL 轮询。
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
          queueQuoteUpdate(msg)
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

  // Watchlist actions
  // round35 FE1 (§14.4-R123): fetchRealtime/fetchIndicators/fetchSignal/fetchHistory/
  // getQuote 五个 REST action 已删——生产代码零调用者（同域端点由组件直调替代），
  // indicators/signal/history refs 从未被写入属死状态。
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
    // R5: 乐观插入——POST 响应已带 realtime（后端优化），立即显示价格，不等慢速全量 GET。
    // round35 FE1 (§14.5): 删除此处的后台全量刷新兜底 GET——唯一消费者
    // WatchlistPanel 用组件本地副本并在 mutation 后自行 fetchItems，
    // store 内再 refetch 造成每次 mutation 双倍 GET。
    if (added?.symbol) {
      watchlist.value = [{ ...added, realtime: added.realtime || null }, ...watchlist.value]
      watchlistTotal.value += 1
    }
    return added
  }

  async function updateWatchlist(id, data) {
    const res = await marketApi.updateWatchlist(id, data)
    return res.data
  }

  async function removeWatchlist(id) {
    await marketApi.removeWatchlist(id)
  }

  async function batchRemoveWatchlist(ids) {
    await marketApi.batchRemoveWatchlist(ids)
  }

  // ── Round34 B4 / R110: indices/global 单飞 + 30s TTL（共享 util）────────
  // Dashboard 单次加载请求数 ==1（基线 ×3）；FE1+FE2 gauge 新增消费方时自动护栏。
  const _indicesSF = createSingleFlight({ ttlMs: 30_000 })

  async function fetchIndicesGlobal() {
    return _indicesSF.run('indices:global', () => marketApi.indicesGlobal())
  }

  return { 
    realtimeData, wsConnected, wsStatus, wsData, 
    connectWS, disconnectWS, onWSMessage, offWSMessage,
    // Watchlist
    watchlist, watchlistLoading, watchlistTotal,
    fetchWatchlist, addWatchlist, updateWatchlist, removeWatchlist, batchRemoveWatchlist,
    // Round34 B4 R110
    fetchIndicesGlobal,
  }
})
