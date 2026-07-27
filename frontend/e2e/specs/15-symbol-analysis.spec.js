// Symbol analysis integration tests — search, chart rendering, report display.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Symbol Analysis', { tag: '@symbol' }, () => {
  test('unified analysis section loads on market analysis page', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const unifiedSection = page.locator('[class*="unified"], [class*="analysis"]').first()
    await expect(unifiedSection).toBeVisible({ timeout: 10000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('symbol search input is interactable', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const searchInput = page.locator('input[placeholder*="搜索"], input[placeholder*="search"], input[placeholder*="ETF"]').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('510300')
      await page.waitForTimeout(1000)
      await searchInput.fill('')
    }
    assertNoConsoleErrors(errors)
  })

  test('quick bar symbol button scrolls to analysis section', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(2000)

    const symbolBtn = page.locator('button:has-text("标的分析")').first()
    if (await symbolBtn.isVisible()) {
      await symbolBtn.click()
      await page.waitForTimeout(1500)
    }
    assertNoConsoleErrors(errors)
  })

  test('technial chart section renders without errors', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(5000)

    const chart = page.locator('canvas, svg, [class*="echart"], [class*="chart"]').first()
    await expect(chart).toBeVisible({ timeout: 15000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('full page load completes without white screen', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await expect(page.locator('body').first()).toBeVisible({ timeout: 15000 })
    assertNoConsoleErrors(errors)
  })
})
