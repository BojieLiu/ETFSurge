import { describe, it, expect, vi } from 'vitest'

// Lightweight stubs so importing the router does not pull in echarts / vue-echarts.
const stub = (name) => ({ default: { name, template: '<div/>' } })
vi.mock('../components/Dashboard.vue', () => stub('Dashboard'))
vi.mock('../components/PortfolioAnalysis.vue', () => stub('PortfolioAnalysis'))
vi.mock('../components/MarketAnalysis.vue', () => stub('MarketAnalysis'))
vi.mock('../components/NewsView.vue', () => stub('NewsView'))

const router = (await import('../router/index.js')).default

describe('router structure', () => {
  const paths = router.options.routes.map((r) => r.path)

  it('has the /news route', () => {
    expect(paths).toContain('/news')
  })

  it('has the merged /portfolio-analysis route', () => {
    expect(paths).toContain('/portfolio-analysis')
  })

  it('does NOT have the old separate /portfolio and /analysis routes', () => {
    expect(paths).not.toContain('/portfolio')
    expect(paths).not.toContain('/analysis')
  })

  it('keeps /market-analysis and / (dashboard)', () => {
    expect(paths).toContain('/market-analysis')
    expect(paths).toContain('/')
  })
})
