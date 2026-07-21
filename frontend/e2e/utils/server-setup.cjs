// Playwright globalSetup — CommonJS version for Playwright compatibility
// Detects if servers are already running before attempting to start.
const net = require('net')
const { startServers } = require('./server.cjs')

function portOpen(port) {
  return new Promise((resolve) => {
    const s = new net.Socket()
    s.setTimeout(500)
    s.on('connect', () => { s.destroy(); resolve(true) })
    s.on('error', () => resolve(false))
    s.on('timeout', () => { s.destroy(); resolve(false) })
    s.connect(port, '127.0.0.1')
  })
}

module.exports = async function globalSetup() {
  const beRunning = await portOpen(8000)
  const feRunning = await portOpen(5173)
  if (beRunning && feRunning) {
    console.log('[globalSetup] Servers already running — skipping start.')
    return
  }
  console.log('[globalSetup] Starting servers…')
  await startServers()
  console.log('[globalSetup] Servers are ready.')
}
