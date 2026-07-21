// @smoke 鈥?quick smoke tests for every major page.
// Run after every change to catch white-screen, broken buttons, and dead inputs.
import { test, expect } from '@playwright/test'
import {
  setupConsoleCapture,
  assertNoConsoleErrors,
  assertButtonRendered,
  assertInputInteractable,
  assertVisible,
} from '../utils/assertions.js'

test.describe('Smoke Tests', { tag: '@smoke' }, () => {
  test('Dashboard loads without white screen and no console errors', async ({ page }) => {
    const errors = setupConsoleCapture(page)
    await page.goto('/')
    // The dashboard container should be present
    await assertVisible(page, '.dashboard')
    assertNoConsoleErrors(errors)
  })

  test('Market analysis page 鈥?buttons render and inputs are interactable', async ({ page }) => {
    await page.goto('/market-analysis')
    // Market report button
    await assertButtonRendered(page, '鐢熸垚甯傚満鐮斿垽')
    // AI advisor input
    await assertInputInteractable(page, '杈撳叆鎮ㄧ殑鎶曡祫闂')
    // Send button
    await assertButtonRendered(page, '鍙戦€佹彁闂?)
    // Stock search
    await assertInputInteractable(page, '鎼滅储 ETF 鎴栬偂绁?)
    // Sector search
    await assertInputInteractable(page, '鎼滅储鏉垮潡/姒傚康')
  })

  test('Portfolio analysis page 鈥?AI tools buttons visible', async ({ page }) => {
    await page.goto('/portfolio-analysis')
    await assertButtonRendered(page, '鏅鸿兘璁捐ETF缁勫悎鏂规')
    await assertButtonRendered(page, '绛栫暐妫€鏌ュ垎鏋?)
    await assertButtonRendered(page, '鍘嗗彶璁板綍')
  })

  test('News page loads with star filters visible', async ({ page }) => {
    await page.goto('/news')
    // Importance filter labels (1-5 stars)
    for (const label of ['1 涓€鑸?, '2 鍏虫敞', '3 閲嶈', '4 绱ф€?, '5 閲嶅ぇ']) {
      await expect(page.locator(`text=${label}`).first()).toBeVisible()
    }
  })

  test('Token monitor page loads', async ({ page }) => {
    await page.goto('/token-monitor')
    await expect(page.locator("text=Token 娑堣€楄秼鍔?)).toBeVisible()
  })
})
