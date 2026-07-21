// Playwright globalTeardown — CommonJS version for Playwright compatibility
const { stopServers } = require('./server.cjs')

module.exports = async function globalTeardown() {
  console.log('[globalTeardown] Stopping servers…')
  await stopServers()
  console.log('[globalTeardown] Servers stopped.')
}
