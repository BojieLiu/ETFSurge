import axios from 'axios'
import logger from '../utils/logger'

const api = axios.create({ baseURL: '/api/v1', timeout: 60000 })

api.interceptors.request.use((config) => {
  logger.debug(`API → ${config.method?.toUpperCase()} ${config.url}`)
  return config
})

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
  realtimePortfolio: () => api.get('/market/realtime/portfolio'),
  history: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/history/${symbol}`, { params: { asset_type: assetType, period } }),
  search: (keyword) => api.get('/market/search', { params: { keyword } }),
  indicators: (symbol, assetType = 'A') => api.get(`/market/indicators/${symbol}`, { params: { asset_type: assetType } }),
  signal: (symbol, assetType = 'A') => api.get(`/market/signal/${symbol}`, { params: { asset_type: assetType } }),
  chart: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/chart/${symbol}`, { params: { asset_type: assetType, period } }),
  indicesGlobal: () => api.get('/market/indices/global'),
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
  dailyPnl: (totalCapital, type) => api.post('/portfolio/daily-pnl', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  getAllocation: (type, totalCapital) => api.post('/portfolio/calculate', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  getPnl: (type, totalCapital) => api.post('/portfolio/daily-pnl', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  strategyCheck: (data) => api.post('/portfolio/strategy-check-async', data),
  getStrategyCheckResult: (taskId) => api.get(`/portfolio/strategy-check-result/${taskId}`),
  listStrategyChecks: (limit = 10, offset = 0, timeout) => api.get('/portfolio/strategy-checks', { params: { limit, offset }, ...(timeout ? { timeout } : {}) }),
  getStrategyCheckDetail: (id) => api.get(`/portfolio/strategy-checks/${id}`),
  applyPortfolioDesign: (design) => api.post('/portfolio/apply-design', design),
  listDesigns: (limit = 10, offset = 0, timeout) => api.get('/portfolio/designs', { params: { limit, offset }, ...(timeout ? { timeout } : {}) }),
  getDesign: (id) => api.get(`/portfolio/designs/${id}`),
  getPnLHistory: (type, period = 'all') => api.get('/portfolio/pnl-history', { params: { portfolio_type: type, period } }),
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
  getDriftCheck: (type) => api.get('/portfolio/drift-check', { params: type ? { portfolio_type: type } : {} }),
}

export const analysisApi = {
  llmAdvice: (query, context) => api.post('/analysis/llm-advice', context, { params: { query }, timeout: 180000 }),
}

export const newsApi = {
  headlines: () => api.get('/news/headlines'),
  newsImpact: (payload) => api.post('/analysis/news-impact', payload),
}

export const adminApi = {
  tokenUsage: () => api.get('/admin/token-usage'),
  tokenTimeseries: (granularity = 'day', days = 30) => api.get('/admin/token-usage/timeseries', { params: { granularity, days } }),
  tokenFailures: (limit = 50) => api.get('/admin/token-usage/failures', { params: { limit } }),
}
