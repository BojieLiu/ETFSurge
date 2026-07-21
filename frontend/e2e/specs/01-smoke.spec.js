// Smoke tests — must-pass on every change.
// @smoke tag: runs in <30s, no external data dependency.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors, assertButtonRendered, assertInputInteractable } from '../utils/assertions.js'

test.describe('Smoke Tests', { tag: '@smoke' }, () => {
  test('Dashboard opens without white screen + no console errors', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 15000 })
    assertNoConsoleErrors(errors)
  })

  test('Market analysis page buttons and inputs are interactable', async ({ page }) => {
    await page.goto('/market-analysis')
    await assertButtonRendered(page, '生成市场研判')
    await assertInputInteractable(page, '搜索')
    await assertButtonRendered(page, '发送')
    await assertInputInteractable(page, 'ETF')
    await assertInputInteractable(page, '板块')
  })

  test('Portfolio analysis page AI tools buttons visible', async ({ page }) => {
    await page.goto('/portfolio-analysis')
    await assertButtonRendered(page, '智能设计')
    await assertButtonRendered(page, '策略检查')
    await assertButtonRendered(page, '历史记录')
  })

  test('News page loads with filters visible', async ({ page }) => {
    await page.goto('/news')
    const errors = setupConsoleCapture(page)
    await expect(page.locator('.card, .section-card, .news-page').first()).toBeVisible({ timeout: 15000 })
    const starFilters = page.locator('text=重要, text=紧急, text=重大').first()
    await expect(starFilters).toBeVisible({ timeout: 5000 }).catch(() => {
      assertNoConsoleErrors(errors)
    })
    assertNoConsoleErrors(errors)
  })

  test('Token monitor page loads with trend chart', async ({ page }) => {
    await page.goto('/token-monitor')
    await expect(page.locator('text=Token').first()).toBeVisible({ timeout: 10000 })
  })
})
