import axios from 'axios'
import logger from '../utils/logger'

const api = axios.create({ baseURL: '/api/v1', timeout: 60000 })

// 请求日志（仅开发环境）：便于排查接口调用链路
api.interceptors.request.use((config) => {
  logger.debug(`API → ${config.method?.toUpperCase()} ${config.url}`)
  return config
})

// 响应错误日志：捕获 HTTP 错误状态码与网络异常，便于问题定位
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const cfg = error.config || {}
    const url = cfg.url || '(unknown)'
    const method = (cfg.method || 'get').toUpperCase()
    const status = error.response?.status
    if (status) {
      logger.error(`API ← ${method} ${url} 失败 [${status}]`, error.response?.data)
    } else {
      logger.error(`API ← ${method} ${url} 网络/请求异常: ${error.message}`)
    }
    return Promise.reject(error)
  }
)

export const marketApi = {
  realtimeAll: () => api.get('/market/realtime'),
  realtimePortfolio: () => api.get('/market/realtime/portfolio'),
  realtimeBatch: (symbols, assetType = 'A') => api.get('/market/realtime/batch', { params: { symbols, asset_type: assetType } }),
  realtime: (symbol, assetType = 'A') => api.get(`/market/realtime/${symbol}`, { params: { asset_type: assetType } }),
  history: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/history/${symbol}`, { params: { asset_type: assetType, period } }),
  search: (keyword) => api.get('/market/search', { params: { keyword } }),
  indicators: (symbol, assetType = 'A') => api.get(`/market/indicators/${symbol}`, { params: { asset_type: assetType } }),
  signal: (symbol, assetType = 'A') => api.get(`/market/signal/${symbol}`, { params: { asset_type: assetType } }),
  chart: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/chart/${symbol}`, { params: { asset_type: assetType, period } }),
  indicesGlobal: () => api.get('/market/indices/global'),
  // Watchlist
  getWatchlist: (params = {}) => api.get('/market/watchlist', { params }),
  addWatchlist: (data) => api.post('/market/watchlist', data),
  updateWatchlist: (id, data) => api.put(`/market/watchlist/${id}`, data),
  removeWatchlist: (id) => api.delete(`/market/watchlist/${id}`),
  batchRemoveWatchlist: (ids) => api.delete('/market/watchlist', { data: { ids } }),
}

export const portfolioApi = {
  list: (type) => api.get('/portfolio/etfs', { params: type ? { portfolio_type: type } : {} }),
  add: (data) => api.post('/portfolio/etfs', data),
  update: (symbol, data) => api.put(`/portfolio/etfs/${symbol}`, data),
  remove: (symbol) => api.delete(`/portfolio/etfs/${symbol}`),
  calculate: (totalCapital, type) => api.post('/portfolio/calculate', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  dailyPnl: (totalCapital, type) => api.post('/portfolio/daily-pnl', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  getAllocation: (type, totalCapital) => api.post('/portfolio/calculate', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  getPnl: (type, totalCapital) => api.post('/portfolio/daily-pnl', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  strategyCheck: (data) => api.post('/portfolio/strategy-check-async', data),
  getStrategyCheckResult: (taskId) => api.get(`/portfolio/strategy-check-result/${taskId}`),
  listStrategyChecks: (limit = 10, offset = 0) => api.get('/portfolio/strategy-checks', { params: { limit, offset } }),
  getStrategyCheckDetail: (id) => api.get(`/portfolio/strategy-checks/${id}`),
  applyStrategy: (suggestions) => api.post('/portfolio/apply-strategy', suggestions),
  applyPortfolioDesign: (design) => api.post('/portfolio/apply-design', design),

  // Design History
  listDesigns: (limit = 10, offset = 0) => api.get('/portfolio/designs', { params: { limit, offset } }),
  getDesign: (id) => api.get(`/portfolio/designs/${id}`),
  deleteDesign: (id) => api.delete(`/portfolio/designs/${id}`),

  // PnL History
  getPnLHistory: (type, period = 'all') => api.get('/portfolio/pnl-history', { params: { portfolio_type: type, period } }),
  // Export/Import
  export: (type, format = 'csv') => api.get('/portfolio/export', { params: { portfolio_type: type, format }, responseType: format === 'csv' ? 'text' : 'json' }),
  import: (file, type = 'on_exchange', mode = 'merge', skipInvalid = true) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('portfolio_type', type)
    formData.append('mode', mode)
    formData.append('skip_invalid', String(skipInvalid))
    return api.post('/portfolio/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  designAsync: (params) => {
    const { capital = 500000, constraints } = params || {}
    return api.post('/portfolio/design-async', { capital, constraints })
  },
  getTask: (taskId) => api.get(`/portfolio/tasks/${taskId}`),
  listTasks: (limit = 10, offset = 0) => api.get('/portfolio/tasks', { params: { limit, offset } }),
  // Drift Check
  getDriftCheck: (type) => api.get('/portfolio/drift-check', { params: type ? { portfolio_type: type } : {} }),
}

export const analysisApi = {
  llmReport: (symbols) => api.post('/analysis/llm-report', symbols, { timeout: 180000 }),
  llmAdvice: (query, context) => api.post('/analysis/llm-advice', context, { params: { query }, timeout: 180000 }),
  llmNewsAnalysis: () => api.post('/analysis/llm-news-analysis', {}, { timeout: 180000 }),
  // portfolioDesign / portfolioDesignStream 已移除 — 使用 POST /portfolio/design-async
  llmReportStream: (symbols, onToken, onDone) => streamPost('/analysis/llm-report/stream', symbols, onToken, onDone),
  llmAdviceStream: (query, context, onToken, onDone) => streamPost('/analysis/llm-advice/stream', context, onToken, onDone, { query }),
  sectorAnalysisStream: (params, onToken, onDone) => streamPost('/analysis/sector-analysis/stream', params, onToken, onDone),
  symbolAnalysisStream: (params, onToken, onDone) => streamPost('/analysis/symbol-analysis/stream', params, onToken, onDone),
  newsImpactStream: (params, onToken, onDone) => streamPost('/analysis/news-impact/stream', params, onToken, onDone),
}

// Helper for streaming POST requests
async function streamPost(endpoint, body, onToken, onDone, params = {}) {
  const url = new URL(`${api.defaults.baseURL}${endpoint}`, window.location.origin)
  Object.entries(params).forEach(([k, v]) => url.searchParams.append(k, v))
  
  const response = await fetch(url.toString(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
    throw new Error(err.detail || `HTTP ${response.status}`)
  }
  
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() || ''
    
    for (const line of lines) {
      if (!line.trim()) continue
      const [eventLine, dataLine] = line.split('\n')
      const event = eventLine?.replace('event: ', '').trim()
      const data = dataLine?.replace('data: ', '').trim()
      
      if (!data) continue
      
      try {
        const parsed = JSON.parse(data)
        if (event === 'token' && onToken) {
          onToken(parsed.token)
        } else if (event === 'done' && onDone) {
          onDone(parsed)
        } else if (event === 'error') {
          throw new Error(parsed.message || 'Stream error')
        }
      } catch (e) {
        console.error('SSE parse error:', e, 'data:', data)
      }
    }
  }
}

export const newsApi = {
  headlines: () => api.get('/news/headlines'),
  macro: () => api.get('/news/macro'),
  global: () => api.get('/news/global'),
  stockNews: (symbol) => api.get(`/news/stock/${symbol}`),
  research: (symbol) => api.get(`/news/research/${symbol}`),
  newsImpact: (payload) => api.post('/analysis/news-impact', payload),
}

export const adminApi = {
  tokenUsage: () => api.get('/admin/token-usage'),
  tokenTimeseries: (params) => api.get('/admin/token-usage/timeseries', { params }),
  tokenFailures: (limit = 50) => api.get('/admin/token-usage/failures', { params: { limit } }),
}
