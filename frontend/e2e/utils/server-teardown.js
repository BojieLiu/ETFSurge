// Playwright globalTeardown — stop backend + frontend servers after all tests.
import { stopServers } from './server.js'

/**
 * @returns {Promise<void>}
 */
export async function globalTeardown() {
  console.log('[globalTeardown] Stopping servers…')
  await stopServers()
  console.log('[globalTeardown] Servers stopped.')
}
