import { createRouter, createWebHistory } from 'vue-router'

// round34-B7 全域 IA 重组（C1 结构归位）：
// - 页面组件统一收敛到 views/（页面）与 components/portfolio/（组合页分区件）
// - 系统组四页挂 /system/*，旧路径 301 式重定向保书签
// - catch-all 404 兜底；所有路由补齐非空 meta.title
// 注：/ai（AI 设计独立路由）在 C3 提交引入——本表暂不含。
const routes = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('../views/Dashboard.vue'),
    meta: { title: '市场概览', description: '实时行情监控、组合摘要与市场总览' },
  },
  {
    path: '/portfolio-analysis',
    name: 'portfolio-analysis',
    component: () => import('../views/PortfolioAnalysis.vue'),
    meta: { title: '组合分析', description: '持仓管理、仓位分配、每日盈亏与历史分析' },
  },
  {
    path: '/market-analysis',
    name: 'market-analysis',
    component: () => import('../views/MarketAnalysis.vue'),
    meta: { title: '行情分析', description: '市场宏观研判、板块轮动分析与标的深度解读' },
  },
  {
    path: '/news',
    name: 'news',
    component: () => import('../views/NewsView.vue'),
    meta: { title: '资讯监控', description: '实时推送重要资讯，AI 智能分析对组合的影响' },
  },
  {
    path: '/system/token',
    name: 'system-token',
    component: () => import('../views/system/TokenMonitor.vue'),
    meta: { title: 'Token 用量监控', description: 'DeepSeek API Token 使用统计与趋势变化' },
  },
  {
    path: '/system/sources',
    name: 'system-sources',
    component: () => import('../views/system/SourceMonitor.vue'),
    meta: { title: '数据源监控', description: '数据源健康状态、事件趋势与失败记录' },
  },
  {
    path: '/system/config',
    name: 'system-config',
    component: () => import('../views/system/ConfigView.vue'),
    meta: { title: '系统配置', description: '管理 API 密钥与服务配置' },
  },

  // ── 旧路径重定向（保书签）─────────────────────────────
  { path: '/token-monitor', redirect: { name: 'system-token' } },
  { path: '/source-monitor', redirect: { name: 'system-sources' } },
  { path: '/admin/config', redirect: { name: 'system-config' } },

  // ── 兜底 404 ─────────────────────────────────────
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('../views/NotFound.vue'),
    meta: { title: '页面不存在', description: '请求的页面不存在' },
  },
]

export default createRouter({ history: createWebHistory(), routes })
