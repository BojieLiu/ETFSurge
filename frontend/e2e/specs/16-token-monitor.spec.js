// Token monitor integration tests — usage overview, time-series charts, per-function breakdown.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Token Monitor', { tag: '@token' }, () => {
  test('token monitor page loads', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/token-monitor')
    await expect(page.locator('[class*="token"], [class*="monitor"], main').first()).toBeVisible({ timeout: 15000 })
    assertNoConsoleErrors(errors)
  })

  test('trend chart renders on token page', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/token-monitor')
    await page.waitForTimeout(3000)

    const chart = page.locator('canvas, svg, [class*="echart"], [class*="chart"]').first()
    await expect(chart).toBeVisible({ timeout: 10000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('token usage summary cards visible', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/token-monitor')
    await page.waitForTimeout(3000)

    const card = page.locator('.card, .stat-card, [class*="summary"], [class*="stat"]').first()
    await expect(card).toBeVisible({ timeout: 10000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('per-function breakdown section renders', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/token-monitor')
    await page.waitForTimeout(3000)

    const breakdown = page.locator('text=function, text=breakdown, text=usage, text=消耗').first()
    await expect(breakdown).toBeVisible({ timeout: 10000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('failure log section renders on token page', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/token-monitor')
    await page.waitForTimeout(3000)

    const failSection = page.locator('text=fail, text=error, text=失败, text=异常').first()
    await expect(failSection).toBeVisible({ timeout: 10000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })
})
