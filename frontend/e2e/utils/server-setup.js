// Playwright globalSetup — start backend + frontend servers before all tests.
import { startServers } from './server.js'

/**
 * @returns {Promise<void>}
 */
export async function globalSetup() {
  console.log('[globalSetup] Starting servers…')
  await startServers()
  console.log('[globalSetup] Servers are ready.')
}
