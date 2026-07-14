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
  strategyCheck: (data) => api.post('/portfolio/strategy-check', data),
  applyStrategy: (suggestions) => api.post('/portfolio/apply-strategy', suggestions),
  applyPortfolioDesign: (design) => api.post('/portfolio/apply-design', design),
}

export const analysisApi = {
  llmReport: (symbols) => api.post('/analysis/llm-report', symbols, { timeout: 180000 }),
  llmAdvice: (query, context) => api.post('/analysis/llm-advice', context, { params: { query }, timeout: 180000 }),
  llmNewsAnalysis: () => api.post('/analysis/llm-news-analysis', {}, { timeout: 180000 }),
  portfolioDesign: (params) => api.post('/analysis/portfolio-design', params, { timeout: 180000 }),
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
