import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1', timeout: 60000 })

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
  strategyCheck: (totalCapital) => api.post('/portfolio/strategy-check', { total_capital: totalCapital }),
}

export const analysisApi = {
  llmReport: (symbols) => api.post('/analysis/llm-report', symbols),
  llmAdvice: (query, context) => api.post('/analysis/llm-advice', context, { params: { query } }),
  llmNewsAnalysis: () => api.post('/analysis/llm-news-analysis'),
  portfolioDesign: (params) => api.post('/analysis/portfolio-design', params),
}

export const newsApi = {
  headlines: () => api.get('/news/headlines'),
  macro: () => api.get('/news/macro'),
  global: () => api.get('/news/global'),
  stockNews: (symbol) => api.get(`/news/stock/${symbol}`),
  research: (symbol) => api.get(`/news/research/${symbol}`),
}
