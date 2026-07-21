// Custom assertion helpers for E2E tests
// Must register console capture before page.goto to catch early errors.
import { expect } from '@playwright/test'

/**
 * Register console listeners to capture JS errors and page-errors.
 * Call this in `test.beforeEach` and pass the returned array to `assertNoConsoleErrors`.
 *
 * @param {import('@playwright/test').Page} page
 * @returns {Array<{text: string, location?: {url?: string, lineNumber?: number}}>}
 */
export function setupConsoleCapture(page) {
  const errors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push({ text: msg.text(), location: msg.location() })
    }
  })
  page.on('pageerror', (err) => {
    errors.push({ text: err.message, stack: err.stack })
  })
  return errors
}

/**
 * Assert that no console errors were captured during the test.
 *
 * @param {Array<{text: string}>} errors
 */
export function assertNoConsoleErrors(errors) {
  expect(errors).toHaveLength(0)
}

/**
 * Assert that an element matching `selector` is visible on the page.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} selector
 */
export async function assertVisible(page, selector) {
  await expect(page.locator(selector)).toBeVisible()
}

/**
 * Assert that a `<button>` with the given text is rendered with proper button styling
 * (tagName, padding, border-radius) so we can detect CSS scoping regressions.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} text
 */
export async function assertButtonRendered(page, text) {
  const btn = page.locator(`button:has-text("${text}")`)
  await expect(btn).toBeVisible()

  // Ensure it is a <button> element (not a <div> pretending)
  const tag = await btn.evaluate((el) => el.tagName.toLowerCase())
  expect(tag).toBe('button')

  // Padding should be > 0 (lost CSS means 0px)
  const padTop = await btn.evaluate((el) => parseFloat(getComputedStyle(el).paddingTop))
  expect(padTop).toBeGreaterThan(0)

  // Border-radius for button appearance (plain text would have 0)
  const radius = await btn.evaluate((el) => parseFloat(getComputedStyle(el).borderRadius))
  expect(radius).toBeGreaterThanOrEqual(2)
}

/**
 * Assert that an `<input>` matching a placeholder substring is enabled,
 * can be filled, and retains the typed value.
 *
 * @param {import('@playwright/test').Page} page
 * @param {string} placeholder
 */
export async function assertInputInteractable(page, placeholder) {
  const input = page.locator(`input[placeholder*="${placeholder}"]`)
  await expect(input).toBeEnabled()
  await input.fill('test input')
  await expect(input).toHaveValue('test input')
}
