import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../components/Dashboard.vue'
import PortfolioAnalysis from '../components/PortfolioAnalysis.vue'
import MarketAnalysis from '../components/MarketAnalysis.vue'
import NewsView from '../components/NewsView.vue'
import TokenMonitor from '../components/TokenMonitor.vue'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard },
  { path: '/portfolio-analysis', name: 'portfolio-analysis', component: PortfolioAnalysis },
  { path: '/market-analysis', name: 'market-analysis', component: MarketAnalysis },
  { path: '/news', name: 'news', component: NewsView },
  { path: '/token-monitor', name: 'token-monitor', component: TokenMonitor },
]

export default createRouter({ history: createWebHistory(), routes })
