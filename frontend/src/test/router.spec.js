import { describe, it, expect, vi } from 'vitest'

// Lightweight stubs so importing the router does not pull in echarts / vue-echarts.
const stub = (name) => ({ default: { name, template: '<div/>' } })
vi.mock('../views/Dashboard.vue', () => stub('Dashboard'))
vi.mock('../views/PortfolioAnalysis.vue', () => stub('PortfolioAnalysis'))
vi.mock('../views/MarketAnalysis.vue', () => stub('MarketAnalysis'))
vi.mock('../views/NewsView.vue', () => stub('NewsView'))
vi.mock('../views/system/TokenMonitor.vue', () => stub('TokenMonitor'))
vi.mock('../views/system/SourceMonitor.vue', () => stub('SourceMonitor'))
vi.mock('../views/system/ConfigView.vue', () => stub('ConfigView'))
vi.mock('../views/NotFound.vue', () => stub('NotFound'))

const router = (await import('../router/index.js')).default

describe('router structure (round34-B7 C1)', () => {
  const routes = router.options.routes
  const paths = routes.map((r) => r.path)
  const names = routes.map((r) => r.name)

  it('has core content routes', () => {
    expect(paths).toContain('/')
    expect(paths).toContain('/news')
    expect(paths).toContain('/portfolio-analysis')
    expect(paths).toContain('/market-analysis')
  })

  it('does NOT have the old separate /portfolio and /analysis routes', () => {
    expect(paths).not.toContain('/portfolio')
    expect(paths).not.toContain('/analysis')
  })

  it('groups system pages under /system/*', () => {
    expect(paths).toContain('/system/token')
    expect(paths).toContain('/system/sources')
    expect(paths).toContain('/system/config')
    // 旧路径仅允许以重定向记录存在，不得再有独立页面路由
    const componentPaths = routes.filter((r) => r.component).map((r) => r.path)
    expect(componentPaths).not.toContain('/token-monitor')
    expect(componentPaths).not.toContain('/source-monitor')
    expect(componentPaths).not.toContain('/admin/config')
  })

  it('redirects legacy bookmarks to the system group', () => {
    const byPath = Object.fromEntries(routes.map((r) => [r.path, r]))
    expect(byPath['/token-monitor'].redirect).toEqual({ name: 'system-token' })
    expect(byPath['/source-monitor'].redirect).toEqual({ name: 'system-sources' })
    expect(byPath['/admin/config'].redirect).toEqual({ name: 'system-config' })
  })

  it('has a catch-all not-found route as last resort', () => {
    const nf = routes.find((r) => r.name === 'not-found')
    expect(nf).toBeTruthy()
    expect(nf.path).toContain(':pathMatch(.*)')
    expect(routes[routes.length - 1].name).toBe('not-found')
  })

  it('every component route has a non-empty meta.title (B7 批复⑥)', () => {
    for (const r of routes.filter((x) => x.component)) {
      expect(r.meta?.title, `meta.title of ${r.path}`).toBeTruthy()
    }
  })
})
