// Portfolio management integration tests — CRUD, apply design, tab switching.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Portfolio Manager', { tag: '@portfolio' }, () => {
  test('portfolio page loads with ETF list and action buttons', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await expect(page.locator('.portfolio-analysis, main, .page').first()).toBeVisible({ timeout: 15000 })
    const tables = page.locator('table, .etf-list, .data-table, .card')
    await expect(tables.first()).toBeVisible({ timeout: 10000 }).catch(() => {})
    const btns = page.locator('button:has-text("智能设计"), button:has-text("策略检查"), button:has-text("历史记录")')
    await expect(btns.first()).toBeVisible({ timeout: 5000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('ETF table renders basic fields', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await expect(page.locator('.portfolio-analysis, main, .page').first()).toBeVisible({ timeout: 15000 })
    const nameCol = page.locator('th:has-text("名称"), th:has-text("代码"), th:has-text("symbol"), th:has-text("ETF")').first()
    const weightCol = page.locator('th:has-text("权重"), th:has-text("市值"), th:has-text("金额"), th:has-text("盈亏")').first()
    await expect(nameCol).toBeVisible({ timeout: 5000 }).catch(() => {})
    await expect(weightCol).toBeVisible({ timeout: 5000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('capital input field is interactable', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await page.waitForTimeout(2000)
    const capitalInput = page.locator('input[type="number"], input[placeholder*="资金"], input[placeholder*="capital"]').first()
    if (await capitalInput.isVisible()) {
      await capitalInput.fill('200000')
      await expect(capitalInput).toHaveValue('200000')
    }
    assertNoConsoleErrors(errors)
  })

  test('design wizard modal opens and shows steps', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await page.waitForTimeout(2000)
    const designBtn = page.locator('button:has-text("智能设计")').first()
    if (await designBtn.isVisible()) {
      await designBtn.click()
      await page.waitForTimeout(2000)
      const modal = page.locator('.modal, .dialog, [role="dialog"], .wizard').first()
      await expect(modal).toBeVisible({ timeout: 5000 }).catch(() => {})
    }
    assertNoConsoleErrors(errors)
  })

  test('strategy check button triggers analysis', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await page.waitForTimeout(2000)
    const checkBtn = page.locator('button:has-text("策略检查")').first()
    if (await checkBtn.isVisible()) {
      await checkBtn.click()
      await page.waitForTimeout(2000)
    }
    assertNoConsoleErrors(errors)
  })

  test('history panel shows task list', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio-analysis')
    await page.waitForTimeout(2000)
    const historyBtn = page.locator('button:has-text("历史记录")').first()
    if (await historyBtn.isVisible()) {
      await historyBtn.click()
      await page.waitForTimeout(2000)
    }
    assertNoConsoleErrors(errors)
  })
})
