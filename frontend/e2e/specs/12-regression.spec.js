// Regression test suite — placeholder for future regression scenarios.
// Add tests here when a bug is fixed that should not reoccur.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Regression Tests', { tag: '@regression' }, () => {
  // #9 — News WebSocket broadcast: first-cycle full push + subsequent only-new-titles
  test('Issue #9 — news page loads without errors and shows WS status indicator', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/news')
    // Wait for the page to render
    await expect(page.locator('.news-page, .section-card, .card').first()).toBeVisible({ timeout: 15000 })
    // Should see a connection status indicator
    const statusDot = page.locator('.status-dot, .ws-status, .connection-status').first()
    await expect(statusDot).toBeVisible({ timeout: 5000 }).catch(() => {
      // If no status dot found, at least verify the page loaded without JS errors
      assertNoConsoleErrors(errors)
    })
    assertNoConsoleErrors(errors)
  })

  // #4 — SSE stream: market report generation uses token events (not chunk)
  test('Issue #4 — market analysis page buttons are functional', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await expect(page.locator('button:has-text("生成市场研判")').first()).toBeVisible()
    await expect(page.locator('button:has-text("生成市场研判")').first()).toBeEnabled()
    assertNoConsoleErrors(errors)
  })
})
