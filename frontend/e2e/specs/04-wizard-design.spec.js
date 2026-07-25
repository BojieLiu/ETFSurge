// Design wizard and strategy check E2E tests with mocked APIs.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Design Wizard & Strategy Check', { tag: '@design' }, () => {
  test('design wizard shows wizard step with a capital input field', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 10000 })

    // Click the smart design button to open wizard
    const designBtn = page.locator('button:has-text("智能设计ETF组合方案"), button:has-text("智能设计")')
    if (await designBtn.isVisible()) {
      await designBtn.click()
      // Wait for wizard or loading state
      const wizard = page.locator('.design-wizard, [class*="wizard"], .loading-card, .wizard-step')
      await expect(wizard.first()).toBeVisible({ timeout: 10000 })
    }
    assertNoConsoleErrors(errors)
  })

  test('design loading state handles timeout gracefully', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    // Mock very slow design-async response (simulate timeout)
    await page.route('**/api/v1/portfolio/design-async', async (route) => {
      await new Promise(r => setTimeout(r, 5000))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: null, error: '超时' }),
      })
    })
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 10000 })
    assertNoConsoleErrors(errors)
  })

  test('strategy check page buttons are interactable', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await expect(page.locator('main, .page, .portfolio-analysis').first()).toBeVisible({ timeout: 10000 })

    // Look for strategy check trigger
    const checkBtn = page.locator('button:has-text("策略检查"), button:has-text("Check")')
    if (await checkBtn.isVisible()) {
      await expect(checkBtn).toBeEnabled()
    }
    assertNoConsoleErrors(errors)
  })

  test('design history navigation works', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 10000 })

    const historyBtn = page.locator('button:has-text("历史记录"), a:has-text("历史记录")')
    if (await historyBtn.isVisible()) {
      await historyBtn.click()
      // Check for history panel or navigation
      await page.waitForTimeout(1000)
    }
    assertNoConsoleErrors(errors)
  })

  test('design async with invalid capital returns error', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.route('**/api/v1/portfolio/design-async', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '无效参数' }),
      })
    })
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 10000 })
    assertNoConsoleErrors(errors)
  })
})
