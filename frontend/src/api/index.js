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
  // O28 (round7 §7 P28②): 单标的资金流端点封装（热点股票技术分析弹窗资金流区块）
  fundFlow: (symbol) => api.get(`/market/fund-flow/${symbol}`),
  realtimePortfolio: () => api.get('/market/realtime/portfolio'),
  history: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/history/${symbol}`, { params: { asset_type: assetType, period } }),
  search: (keyword, options = {}, config = {}) => api.get('/market/search', { params: { keyword, ...options }, ...config }),
  indicesMeta: () => api.get('/market/indices/meta'),
  indicators: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/indicators/${symbol}`, { params: { asset_type: assetType, period } }),
  signal: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/signal/${symbol}`, { params: { asset_type: assetType, period } }),
  chart: (symbol, assetType = 'A', period = 'daily') => api.get(`/market/chart/${symbol}`, { params: { asset_type: assetType, period } }),
  indicesGlobal: () => api.get('/market/indices/global'),
  getWatchlist: (params = {}) => api.get('/market/watchlist', { params }),
  addWatchlist: (data) => api.post('/market/watchlist', data),
  updateWatchlist: (id, data) => api.put(`/market/watchlist/${id}`, data),
  removeWatchlist: (id) => api.delete(`/market/watchlist/${id}`),
  batchRemoveWatchlist: (ids) => api.delete('/market/watchlist', { data: { ids } }),
  // F16 (round6 §16.4): 三热点端点透传 market（A/HK/US）——切港股后热点不再显示 A 股数据
  getHotPlates: (limit = 15, market = 'A') => api.get('/market/hot-plates', { params: { limit, market } }),
  getSectorHeat: (limit = 20, market = 'A') => api.get('/market/sectors/heat', { params: { limit, market } }),
  getStockHotRank: (limit = 50, market = 'A') => api.get('/market/stock-hot-rank', { params: { limit, market } }),
  // 说明（F2-4）：symbol/sector 分析是 SSE 流式端点（/analysis/*-analysis/stream），
  // 前端经 useLLMStream（fetch + ReadableStream）消费，因此不在 marketApi 定义
  // axios 方法 —— check_api_usage 门禁要求方法必有调用点，无调用点即删除。
}

export const portfolioApi = {
  list: (type) => api.get('/portfolio/etfs', { params: type ? { portfolio_type: type } : {} }),
  add: (data) => api.post('/portfolio/etfs', data),
  update: (symbol, data) => api.put(`/portfolio/etfs/${symbol}`, data),
  remove: (symbol) => api.delete(`/portfolio/etfs/${symbol}`),
  dailyPnl: (totalCapital, type) => api.post('/portfolio/daily-pnl', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  getAllocation: (type, totalCapital) => api.post('/portfolio/calculate', { total_capital: totalCapital }, { params: type ? { portfolio_type: type } : {} }),
  // round23 §6.2: getPnl 与 dailyPnl 重复（入参顺序相反）已合并——统一用 dailyPnl(totalCapital, type)
  strategyCheck: (data) => api.post('/portfolio/strategy-check-async', data),
  getStrategyCheckResult: (taskId) => api.get(`/portfolio/strategy-check-result/${taskId}`),
  getStrategyCheckDetail: (id) => api.get(`/portfolio/strategy-checks/${id}`),
  applyPortfolioDesign: (design) => api.post('/portfolio/apply-design', design),
  getDesign: (id) => api.get(`/portfolio/designs/${id}`),
  getPnLHistory: (type, period = 'all', totalCapital = 0) => api.get('/portfolio/pnl-history', { params: { portfolio_type: type, period, total_capital: totalCapital } }),
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
    const { capital = 500000, constraints, market = 'A' } = params || {}
    return api.post('/portfolio/design-async', { capital, constraints, market })
  },
  getTask: (taskId) => api.get(`/portfolio/tasks/${taskId}`),
  listTasks: (limit = 20, offset = 0) => api.get('/portfolio/tasks', { params: { limit, offset } }),
  getDriftCheck: (type) => api.get('/portfolio/drift-check', { params: type ? { portfolio_type: type } : {} }),
  getTimeline: (limit = 20, offset = 0) => api.get('/portfolio/timeline', { params: { limit, offset } }),
}

export const newsApi = {
  headlines: () => api.get('/news/headlines'),
  // F29 (round23 §2.4 A4): 资讯页接入 macro/global/stock/research 四端点——
  // 旧实现仅 headlines 可达，其余 4 端点 UI 不可达（事实死功能）。
  macro: () => api.get('/news/macro'),
  globalNews: () => api.get('/news/global'),
  stockNews: (symbol) => api.get(`/news/stock/${encodeURIComponent(symbol)}`),
  research: (symbol) => api.get(`/news/research/${encodeURIComponent(symbol)}`),
  newsImpact: (payload) => api.post('/analysis/news-impact', payload),
}

export const factorsApi = {
  getActive: () => api.get('/factors/active'),
}

export const systemApi = {
  warmup: () => api.get('/system/warmup'),
}

export const adminApi = {
  tokenUsage: () => api.get('/admin/token-usage'),
  tokenTimeseries: (params = {}) => api.get('/admin/token-usage/timeseries', { params }),
  tokenFailures: (limit = 50) => api.get('/admin/token-usage/failures', { params: { limit } }),
  sourcesHealth: () => api.get('/admin/sources/health'),
  sourcesTimeline: (hours = 1) => api.get('/admin/sources/events/timeline', { params: { hours } }),
  sourcesFailures: (limit = 10) => api.get('/admin/sources/events/failures', { params: { limit } }),
  sourcesCircuitBreakers: () => api.get('/admin/sources/circuit-breakers'),
  getConfig: () => api.get('/admin/config'),
  updateConfig: (payload) => api.put('/admin/config', payload),
  // R18 (round24): 重置单个 override 回 .env 值（闭环 DELETE /admin/config/{key} 生命周期）
  resetConfigKey: (key) => api.delete(`/admin/config/${encodeURIComponent(key)}`),
}
