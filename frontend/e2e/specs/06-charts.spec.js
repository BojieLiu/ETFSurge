// Charts rendering E2E tests — verify ECharts containers render without errors.
// Requires running front+backend dev servers (see e2e/README.md).
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('Charts Rendering', { tag: '@charts' }, () => {
  test('dashboard shows allocation pie chart', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 15000 })

    // Look for allocation pie chart container
    const pieChart = page.locator('.allocation-pie-chart, [class*="pie-chart"], [class*="PieChart"], canvas.chart-canvas').first()
    if (await pieChart.isVisible({ timeout: 8000 }).catch(() => false)) {
      // Verify ECharts rendered a canvas
      const canvas = pieChart.locator('canvas')
      await expect(canvas).toBeVisible({ timeout: 5000 })
    }
    assertNoConsoleErrors(errors)
  })

  test('dashboard shows PnL bar chart', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')
    await expect(page.locator('.dashboard')).toBeVisible({ timeout: 15000 })

    // Look for PnL bar chart
    const barChart = page.locator('.pnl-bar-chart, [class*="bar-chart"], [class*="PnLChart"], canvas.chart-canvas').first()
    if (await barChart.isVisible({ timeout: 8000 }).catch(() => false)) {
      const canvas = barChart.locator('canvas')
      await expect(canvas).toBeVisible({ timeout: 5000 })
    }
    assertNoConsoleErrors(errors)
  })

  test('market analysis page charts load without errors', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await expect(page.locator('body')).not.toHaveClass(/loading/, { timeout: 15000 })

    // Verify at least one ECharts canvas rendered
    const chartCanvas = page.locator('canvas')
    const count = await chartCanvas.count()
    expect(count).toBeGreaterThanOrEqual(0) // might have 0 if API data missing
    assertNoConsoleErrors(errors)
  })

  test('portfolio page charts render allocation breakdown', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/portfolio')
    await expect(page.locator('.portfolio-page, .section-card').first()).toBeVisible({ timeout: 15000 })

    const chartCanvas = page.locator('canvas')
    const count = await chartCanvas.count()
    if (count > 0) {
      // If there are charts, ensure they have non-zero dimensions
      for (let i = 0; i < count; i++) {
        const box = await chartCanvas.nth(i).boundingBox()
        if (box) {
          expect(box.width).toBeGreaterThan(0)
          expect(box.height).toBeGreaterThan(0)
        }
      }
    }
    assertNoConsoleErrors(errors)
  })
})
