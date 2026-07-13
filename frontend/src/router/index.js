import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../components/Dashboard.vue'
import PortfolioManager from '../components/PortfolioManager.vue'
import AnalysisView from '../components/AnalysisView.vue'
import MarketAnalysis from '../components/MarketAnalysis.vue'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard },
  { path: '/portfolio', name: 'portfolio', component: PortfolioManager },
  { path: '/analysis', name: 'analysis', component: AnalysisView },
  { path: '/market-analysis', name: 'market-analysis', component: MarketAnalysis },
]

export default createRouter({ history: createWebHistory(), routes })
