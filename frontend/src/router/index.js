import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../components/Dashboard.vue'
import PortfolioAnalysis from '../components/PortfolioAnalysis.vue'
import MarketAnalysis from '../components/MarketAnalysis.vue'
import NewsView from '../components/NewsView.vue'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard },
  { path: '/portfolio-analysis', name: 'portfolio-analysis', component: PortfolioAnalysis },
  { path: '/market-analysis', name: 'market-analysis', component: MarketAnalysis },
  { path: '/news', name: 'news', component: NewsView },
]

export default createRouter({ history: createWebHistory(), routes })
