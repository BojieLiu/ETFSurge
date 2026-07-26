// Visual regression tests — screenshot baselines for key pages.
// Run `npm run test:e2e:visual` to generate/update baseline snapshots.
// Run `npm run test:e2e` to compare against existing baselines.
// @visual tag: runs with backend mock data for consistent snapshots.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Visual Regression', { tag: '@visual' }, () => {
  test('Dashboard 完整页面截图 — 初始加载状态', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')

    // 等待基础 UI 渲染完成
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('.dashboard-tabs')).toBeVisible({ timeout: 10000 })

    // 等待 GlobalIndicesStrip 和 SummaryCards 渲染
    await expect(page.locator('.summary-grid').first()).toBeVisible({ timeout: 10000 }).catch(() => {
      // summary 卡片可能因无数据不渲染，不阻塞
    })
    await expect(page.locator('.global-indices, .index-scroll').first()).toBeVisible({ timeout: 10000 }).catch(() => {
      // 全球指数可能因无数据不渲染
    })

    // 等待图表和数据渲染完成
    await page.waitForTimeout(2000)

    await expect(page).toHaveScreenshot('dashboard-loaded.png', {
      maxDiffPixelRatio: 0.02,
      threshold: 0.2,
    })
    assertNoConsoleErrors(errors)
  })

  test('Dashboard 加载骨架屏截图', async ({ page }) => {
    const errors = setupConsoleCapture(page)

    // 拦截所有 portfolio API 请求，模拟 loading 状态
    await page.route('**/api/v1/portfolio/**', async (route) => {
      // 延迟响应以捕获骨架屏状态
      await new Promise(r => setTimeout(r, 5000))
      await route.continue()
    })

    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 15000 })

    // 检查骨架屏元素可见（Skeleton 组件或 loading-grid）
    const skeleton = page.locator('.skeleton-card, .loading-grid, [class*="skeleton"]').first()
    await expect(skeleton).toBeVisible({ timeout: 5000 }).catch(() => {
      // 可能已渲染完成，不阻塞
    })

    await expect(page).toHaveScreenshot('dashboard-loading.png', {
      maxDiffPixelRatio: 0.02,
      threshold: 0.2,
    })
    assertNoConsoleErrors(errors)
  })

  test('PortfolioAnalysis 页面截图', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')

    // 等待页面主体渲染
    await expect(page.locator('.portfolio-analysis, main, .page').first()).toBeVisible({ timeout: 15000 })

    // 等待 tab 栏渲染
    const tabBar = page.locator('.tabs, [class*="tab"]').first()
    await expect(tabBar).toBeVisible({ timeout: 10000 }).catch(() => {
      // tab 可能使用不同 class 名
    })

    await page.waitForTimeout(1500)

    await expect(page).toHaveScreenshot('portfolio-analysis.png', {
      maxDiffPixelRatio: 0.02,
      threshold: 0.2,
    })
    assertNoConsoleErrors(errors)
  })

  test('MarketAnalysis 页面截图', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')

    // 等待页面主体渲染
    await expect(page.locator('.market-analysis, main, .page').first()).toBeVisible({ timeout: 15000 })

    // 等待市场 tab 渲染
    const marketTabs = page.locator('.market-tabs, .tabs, [class*="tab"]').first()
    await expect(marketTabs).toBeVisible({ timeout: 10000 }).catch(() => {
      // tab 可能使用不同选择器
    })

    await page.waitForTimeout(1500)

    await expect(page).toHaveScreenshot('market-analysis.png', {
      maxDiffPixelRatio: 0.02,
      threshold: 0.2,
    })
    assertNoConsoleErrors(errors)
  })
})
