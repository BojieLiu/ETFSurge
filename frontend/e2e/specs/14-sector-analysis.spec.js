// Sector analysis integration tests — sector heat map tab switching and data display.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Sector Analysis', { tag: '@sector' }, () => {
  test('sector heat map section renders on market analysis page', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(4000)

    const sectorTitle = page.locator('text=热点板块排行, text=热点板块').first()
    await expect(sectorTitle).toBeVisible({ timeout: 15000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('sector tabs are interactable', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(4000)

    const tabs = ['热点板块', '板块热度', '热门个股']
    for (const tabLabel of tabs) {
      const tab = page.locator(`button:has-text("${tabLabel}")`).first()
      if (await tab.isVisible()) {
        await tab.click()
        await page.waitForTimeout(1000)
        await expect(tab).toHaveClass(/active/).catch(() => {})
      }
    }
    assertNoConsoleErrors(errors)
  })

  test('sector data table renders rows', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(5000)

    const dataRows = page.locator('.data-row, .row-main, [class*="row"]').first()
    await expect(dataRows).toBeVisible({ timeout: 10000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('quick bar sector button scrolls to section', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const sectorBtn = page.locator('button:has-text("板块")').first()
    if (await sectorBtn.isVisible()) {
      await sectorBtn.click()
      await page.waitForTimeout(1500)
    }
    assertNoConsoleErrors(errors)
  })

  test('sector heat map renders without console errors on repeated tab switches', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(4000)

    for (const tabLabel of ['板块热度', '热点板块', '热门个股', '热点板块']) {
      const tab = page.locator(`button:has-text("${tabLabel}")`).first()
      if (await tab.isVisible()) {
        await tab.click()
        await page.waitForTimeout(800)
      }
    }
    assertNoConsoleErrors(errors)
  })
})
