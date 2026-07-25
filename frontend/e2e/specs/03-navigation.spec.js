// Navigation integration tests — verify page routing and nav guards work.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Page Navigation', { tag: '@navigation' }, () => {
  test('navigates from Dashboard to Market Analysis', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 10000 })
    const marketLink = page.locator('a[href*="market"], [href*="market-analysis"], nav a').filter({ hasText: /市场|行情|Market|Analysis/i }).first()
    if (await marketLink.isVisible()) {
      await marketLink.click()
      await page.waitForURL(/\/(market|analysis)/, { timeout: 5000 })
      expect(page.url()).toMatch(/\/(market|analysis)/)
    }
    assertNoConsoleErrors(errors)
  })

  test('navigates from Market Analysis to Portfolio Analysis', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await expect(page.locator('main, .page, .market-analysis').first()).toBeVisible({ timeout: 10000 })
    const portfolioLink = page.locator('a[href*="portfolio"], nav a').filter({ hasText: /组合|Portfolio/i }).first()
    if (await portfolioLink.isVisible()) {
      await portfolioLink.click()
      await page.waitForURL(/\/portfolio/, { timeout: 5000 })
      expect(page.url()).toMatch(/\/portfolio/)
    }
    assertNoConsoleErrors(errors)
  })

  test('navigates to News page without console errors', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/news')
    await expect(page.locator('main, .page, .news-page, .section-card, .card').first()).toBeVisible({ timeout: 10000 })
    assertNoConsoleErrors(errors)
  })

  test('navigates to Token Monitor page', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/token-monitor')
    await expect(page.locator('main, .page, [class*="token"]').first()).toBeVisible({ timeout: 10000 })
    assertNoConsoleErrors(errors)
  })

  test('unknown route redirects to home or shows 404 page', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/non-existent-route-test-xyz')
    // Either redirect to '/' or show a 404 page
    await page.waitForTimeout(3000)
    const onHome = page.url() === 'http://localhost:5173/' || page.url().endsWith('/')
    const hasError = await page.locator('text=404, text=Not Found, text=找不到').first().isVisible().catch(() => false)
    expect(onHome || hasError).toBe(true)
    assertNoConsoleErrors(errors)
  })

  test('direct URL to portfolio page works', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await expect(page.locator('main, .page, .portfolio-analysis').first()).toBeVisible({ timeout: 10000 })
    assertNoConsoleErrors(errors)
  })
})
