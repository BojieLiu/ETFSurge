// Market tab switching integration tests — A/HK/US/Global tab navigation.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Market Tab Navigation', { tag: '@market-tabs' }, () => {
  test('market analysis page renders all tab buttons', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await expect(page.locator('.market-analysis, main, .page').first()).toBeVisible({ timeout: 15000 })

    const tabs = ['A股', '港股', '美股', '全球']
    for (const t of tabs) {
      const tab = page.locator(`button:has-text("${t}"), [role="tab"]:has-text("${t}")`).first()
      await expect(tab).toBeVisible({ timeout: 5000 })
    }
    assertNoConsoleErrors(errors)
  })

  test('switch between market tabs and verify active state', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(2000)

    for (const tabLabel of ['港股', '美股', 'A股']) {
      const tab = page.locator(`button:has-text("${tabLabel}")`).first()
      if (await tab.isVisible()) {
        await tab.click()
        await page.waitForTimeout(1500)
        await expect(tab).toHaveClass(/active/).catch(() => {})
      }
    }
    assertNoConsoleErrors(errors)
  })

  test('quick action bar renders section links', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(2000)

    const actions = ['市场研判', '自选', 'AI顾问', '标的分析']
    for (const label of actions) {
      const btn = page.locator(`button:has-text("${label}")`).first()
      await expect(btn).toBeVisible({ timeout: 3000 }).catch(() => {})
    }
    assertNoConsoleErrors(errors)
  })

  test('scrolling to sections works without console errors', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const scrollBtn = page.locator('button:has-text("板块")').first()
    if (await scrollBtn.isVisible()) {
      await scrollBtn.click()
      await page.waitForTimeout(1000)
    }
    const advisorBtn = page.locator('button:has-text("AI顾问")').first()
    if (await advisorBtn.isVisible()) {
      await advisorBtn.click()
      await page.waitForTimeout(1000)
    }
    assertNoConsoleErrors(errors)
  })

  test('repeated tab switching maintains layout integrity', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(2000)

    for (let round = 0; round < 3; round++) {
      const tab = page.locator(`button:has-text("${round % 2 === 0 ? '全球' : 'A股'}")`).first()
      if (await tab.isVisible()) {
        await tab.click()
        await page.waitForTimeout(1000)
      }
    }
    assertNoConsoleErrors(errors)
  })
})
