import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('../components/Dashboard.vue'),
    meta: { title: 'Dashboard', description: '实时行情监控、组合概览与智能策略分析' },
  },
  {
    path: '/portfolio-analysis',
    name: 'portfolio-analysis',
    component: () => import('../components/PortfolioAnalysis.vue'),
    meta: { title: '组合与分析', description: '管理场内/场外 ETF 组合，查看技术分析与买卖信号' },
  },
  {
    path: '/market-analysis',
    name: 'market-analysis',
    component: () => import('../components/MarketAnalysis.vue'),
    meta: { title: '行情分析', description: '市场宏观研判、板块轮动分析与标的深度解读' },
  },
  {
    path: '/news',
    name: 'news',
    component: () => import('../components/NewsView.vue'),
    meta: { title: '资讯监控', description: '实时推送重要资讯，AI 智能分析对组合的影响' },
  },
  {
    path: '/token-monitor',
    name: 'token-monitor',
    component: () => import('../components/TokenMonitor.vue'),
    meta: { title: 'Token 用量监控', description: 'DeepSeek API Token 使用统计与趋势变化' },
  },
]

export default createRouter({ history: createWebHistory(), routes })
