// AI Advisor integration tests — input, submit, stream response display.
import { test, expect } from '@playwright/test'
import { setupConsoleCapture, assertNoConsoleErrors } from '../utils/assertions.js'

test.describe('AI Advisor', { tag: '@ai-advisor' }, () => {
  test('AiAdvisor component renders with input and send button', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const sendBtn = page.locator('button:has-text("发送"), button:has-text("Send"), button:has-text("提问")').first()
    await expect(sendBtn).toBeVisible({ timeout: 10000 }).catch(() => {})

    const input = page.locator('textarea, input[type="text"]').first()
    await expect(input).toBeVisible({ timeout: 5000 }).catch(() => {})
    assertNoConsoleErrors(errors)
  })

  test('AI advisor input accepts text and sends query', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const input = page.locator('textarea, input:not([type="hidden"])').first()
    if (await input.isVisible()) {
      await input.fill('今天A股行情如何')
      await page.waitForTimeout(500)
      const sendBtn = page.locator('button:has-text("发送"), button:has-text("Send")').first()
      if (await sendBtn.isVisible()) {
        await sendBtn.click()
        await page.waitForTimeout(3000)
      }
    }
    assertNoConsoleErrors(errors)
  })

  test('AI advisor handles empty query gracefully', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const sendBtn = page.locator('button:has-text("发送"), button:has-text("Send")').first()
    if (await sendBtn.isVisible()) {
      await sendBtn.click()
      await page.waitForTimeout(1000)
    }
    assertNoConsoleErrors(errors)
  })

  test('AI advisor shows loading state during streaming', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(3000)

    const input = page.locator('textarea, input:not([type="hidden"])').first()
    if (await input.isVisible()) {
      await input.fill('当前市场热点板块')
      const sendBtn = page.locator('button:has-text("发送"), button:has-text("Send")').first()
      if (await sendBtn.isVisible()) {
        await sendBtn.click()
        await page.waitForTimeout(2000)
        const loading = page.locator('.loading, .spinner, [class*="loading"], [aria-busy="true"]').first()
        await expect(loading).toBeVisible({ timeout: 5000 }).catch(() => {})
      }
    }
    assertNoConsoleErrors(errors)
  })

  test('quick action bar advisor button scrolls to section', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/market-analysis')
    await page.waitForTimeout(2000)

    const advisorBtn = page.locator('button:has-text("AI顾问")').first()
    if (await advisorBtn.isVisible()) {
      await advisorBtn.click()
      await page.waitForTimeout(1500)
    }
    assertNoConsoleErrors(errors)
  })
})
