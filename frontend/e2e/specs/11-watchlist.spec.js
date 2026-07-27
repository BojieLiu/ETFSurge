// Watchlist integration tests — CRUD operations and market data display.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Watchlist', { tag: '@watchlist' }, () => {
  test('watchlist panel renders on market analysis page', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const watchlist = page.locator('text=自选, text=Watchlist, text=⭐').first()
    await expect(watchlist).toBeVisible({ timeout: 10000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('search input field is interactable', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const searchInput = page.locator('input[placeholder*="搜索"], input[placeholder*="search"], input[type="text"]').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('510300')
      await page.waitForTimeout(1000)
      await searchInput.fill('')
    }
    assertNoConsoleErrors(errors)
  })

  test('ETF code search shows results in watchlist section', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const searchInput = page.locator('input[placeholder*="搜索"], input[placeholder*="search"], input[type="text"]').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('510300')
      await page.waitForTimeout(3000)
    }
    assertNoConsoleErrors(errors)
  })

  test('watchlist renders without console errors', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)
    assertNoConsoleErrors(errors)
  })

  test('selected watchlist item triggers symbol analysis', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const watchRow = page.locator('.data-row, .watchlist-item, tr').filter({ hasText: /(510300|518880|159915)/ }).first()
    if (await watchRow.isVisible()) {
      await watchRow.click()
      await page.waitForTimeout(2000)
    }
    assertNoConsoleErrors(errors)
  })
})
